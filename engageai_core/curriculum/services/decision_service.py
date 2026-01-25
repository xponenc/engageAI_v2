# curriculum/services/learning_process/decision_service.py

from django.utils import timezone
from curriculum.models.student.enrollment import Enrollment
from curriculum.models.content.lesson import Lesson
from curriculum.models.student.skill_delta import SkillDelta
import logging

from curriculum.services.notification_service import NotificationService
from curriculum.services.path_generation_service import PathGenerationService
from users.models import CEFRLevel

logger = logging.getLogger(__name__)


class DecisionService:
    """
    Сервис принятия решений по адаптации учебного пути.
    Запускается после оценки урока (в assess_lesson_tasks).
    """

    @staticmethod
    def evaluate_and_adapt_path(enrollment: Enrollment, completed_lesson: Lesson):
        """
        Главный метод: анализирует результаты урока и адаптирует путь.
        """
        if not hasattr(enrollment, 'learning_path'):
            logger.warning(f"Нет LearningPath для enrollment {enrollment.pk}")
            return

        path = enrollment.learning_path
        student = enrollment.student

        # Получаем последние delta (например, за 5 уроков)
        recent_deltas = SkillDelta.objects.filter(
            enrollment=enrollment,
            lesson__order__lte=completed_lesson.order
        ).order_by('-calculated_at')[:5]

        if not recent_deltas.exists():
            logger.info(f"Нет delta для анализа адаптации {enrollment.pk}")
            return

        # Агрегируем последние изменения
        overall_trend = sum(d.deltas.get('overall', 0) for d in recent_deltas) / len(recent_deltas)
        skill_trends = {}
        for delta in recent_deltas:
            for skill, value in delta.deltas.items():
                skill_trends.setdefault(skill, []).append(value)

        adapted = False

        # Правило 1: Слабый прогресс по ключевым навыкам → remedial
        weak_skills = []
        for skill, values in skill_trends.items():
            avg = sum(values) / len(values)
            if avg < -0.03:  # порог падения
                weak_skills.append(skill)

        if weak_skills:
            remedial_lessons = Lesson.objects.filter(
                is_remedial=True,
                skill_focus__overlap=weak_skills,
                level=student.english_level
            ).order_by('order')[:2]  # 1–2 remedial-урока

            for remedial in remedial_lessons:
                new_node = {
                    "node_id": len(path.nodes) + 1,
                    "lesson_id": remedial.id,
                    "title": f"Дополнительно: {remedial.title} ({', '.join(weak_skills)})",
                    "reason": f"Устранение слабых мест после урока {completed_lesson.title}",
                    "estimated_minutes": remedial.duration_minutes,
                    "type": "remedial",
                    "prerequisites": [path.current_node_index + 1],
                    "status": "recommended",
                    "adaptive_trigger": "weak_skill_delta"
                }
                path.nodes.insert(path.current_node_index + 1, new_node)
                adapted = True
                logger.info(f"Добавлен remedial-узел {remedial.title} для {enrollment.pk}")

        # Правило 2: Сильный прогресс → skip практики или ускорение
        if overall_trend > 0.15 and path.next_node:
            next_node = path.next_node
            if "practice" in next_node.get("type", "").lower():
                next_index = path.current_node_index + 1
                path.nodes[next_index]["status"] = "skipped"
                path.nodes[next_index]["skip_reason"] = "Сильный прогресс в навыке"
                adapted = True
                logger.info(f"Пропущен practice-узел {next_node['title']} для {enrollment.pk}")

        # Правило 3: Низкий engagement (<5) → упрощение пути
        if student.engagement_level < 5 and path.path_type != "PERSONALIZED":
            # Можно перегенерировать путь с меньшей сложностью
            PathGenerationService.generate_personalized_path(enrollment)  # с флагом low_engagement=True
            path.metadata["adaptation_reason"] = "low_engagement"
            adapted = True

        # Правило 4: Устойчивый прогресс → повышение уровня (редко!)
        if len(recent_deltas) >= 5 and overall_trend > 0.12:
            avg_min_skill = min(
                sum(d.deltas.get(skill, 0) for d in recent_deltas) / len(recent_deltas)
                for skill in ["grammar", "vocabulary", "speaking"]
            )
            if avg_min_skill > 0.08 and min(student.current_skills.values()) > 0.75:
                new_level = CEFRLevel.get_next(student.english_level)
                if new_level != student.english_level:
                    student.english_level = new_level
                    student.save(update_fields=['english_level'])
                    # Перегенерируем путь с новым уровнем
                    PathGenerationService.generate_personalized_path(enrollment)
                    path.metadata["adaptation_reason"] = "level_up"
                    adapted = True
                    logger.info(f"Повышен уровень до {new_level} для {enrollment.pk}")

        if adapted:
            path.metadata["last_adaptation"] = timezone.now().isoformat()
            path.metadata["adapted_after_lesson"] = completed_lesson.pk
            path.save()
            logger.info(f"Путь адаптирован для enrollment {enrollment.pk}")

            # Отправляем nudge студенту
            NotificationService.send_adaptive_nudge(student, path)