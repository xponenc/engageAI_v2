
from curriculum.models.content.lesson import Lesson
from curriculum.models.learning_process.learning_path import LearningPath
from curriculum.models.learning_process.path_generation_service import PathGenerationService


class DecisionService:
    """
    Полная логика роутинга: анализ SkillDelta + профиля → адаптация LearningPath.
    Правила охватывают все сценарии: слабый/сильный прогресс, цели (career/IT), engagement.
    Вызывается после COMPLETE урока (из LessonEventService).
    """

    @staticmethod
    def evaluate_and_adapt_path(enrollment, completed_lesson):
        if not hasattr(enrollment, "learning_path"):
            return

        path = enrollment.learning_path
        student = enrollment.student
        latest_delta = enrollment.skill_deltas.filter(lesson=completed_lesson).first()
        if not latest_delta:
            return

        deltas = latest_delta.deltas
        overall_delta = deltas.get("overall", 0)
        weak_skills = [s for s, v in deltas.items() if v < -0.03]  # Слабые с падением
        strong_skills = [s for s, v in deltas.items() if v > 0.15]  # Сильные с ростом

        adapted = False

        # Правило 1: Слабый общий прогресс (overall < 0) → remedial уроки
        if overall_delta < 0:
            remedial_lessons = Lesson.objects.filter(
                skill_focus__overlap=weak_skills,
                level=student.english_level,
                is_remedial=True
            )[:2]  # 1–2 дополнительных
            for remedial in remedial_lessons:
                new_node = {
                    "node_id": len(path.nodes) + 1,
                    "lesson_id": remedial.id,
                    "title": f"Дополнительно: {remedial.title} ({', '.join(weak_skills)} Practice)",
                    "reason": f"Устранение слабых мест: delta {overall_delta:.2f}",
                    "estimated_minutes": remedial.estimated_time or 20,
                    "type": "remedial",
                    "prerequisites": [path.current_node["node_id"] if path.current_node else None],
                    "triggers": [],
                    "status": "recommended"
                }
                path.nodes.insert(path.current_node_index + 1, new_node)
            path.path_type = "ADAPTIVE" if path.path_type == "LINEAR" else path.path_type
            adapted = True

        # Правило 2: Сильный прогресс (overall > 0.15) → пропуск урока или ускорение
        elif overall_delta > 0.15 and path.next_node:
            if "practice" in path.next_node.get("type", ""):  # Пропустить практику, если сильный
                path.nodes[path.current_node_index + 1]["status"] = "skipped"
                path.current_node_index += 1
                path.metadata["skips"] = path.metadata.get("skips", 0) + 1
                adapted = True

        # Правило 3: Падение в ключевых навыках по целям (e.g., speaking для career/IT)
        if "career" in student.learning_goals or "IT_interview" in student.learning_goals:
            if "speaking" in weak_skills or "pronunciation" in weak_skills:
                # Добавляем AI-собеседование как remedial
                interview_lesson = Lesson.objects.filter(skill_focus__contains=["speaking"], type="interview").first()
                if interview_lesson:
                    new_node = {
                        "node_id": len(path.nodes) + 1,
                        "lesson_id": interview_lesson.id,
                        "title": "AI-Собеседование: Practice Speaking",
                        "reason": f"Для цели {student.learning_goals}: delta speaking {deltas.get('speaking', 0):.2f}",
                        "type": "remedial",
                        "prerequisites": [path.current_node["node_id"]],
                        "status": "recommended"
                    }
                    path.nodes.append(new_node)  # В конец, чтобы не нарушать текущий
                    adapted = True

        # Правило 4: Низкий engagement ( <5 ) → упрощение пути или nudges
        if student.engagement_level < 5 and path.path_type != "PERSONALIZED":
            # Перегенерировать путь с меньшим временем
            PathGenerationService.generate_personalized_path(enrollment)
            path.metadata["reason"] = "Low engagement — simplified path"
            adapted = True

        # Правило 5: Правило перехода уровня — только после устойчивого прогресса
        recent_deltas = enrollment.skill_deltas.order_by("-calculated_at")[:8]  # Последние 8 уроков
        if len(recent_deltas) >= 5:
            avg_overall = sum(d.deltas.get("overall", 0) for d in recent_deltas) / len(recent_deltas)
            latest_snapshot = enrollment.skill_snapshots.latest("snapshot_at")

            if (avg_overall > 0.12 and
                    latest_snapshot and
                    min(latest_snapshot.skills.values()) > 0.75):
                new_level = Lesson.get_next_cefr_level(student.english_level)

                # Обновляем уровень студента
                student.english_level = new_level
                student.save(update_fields=["english_level"])

                # Большое событие — регенерируем весь путь
                PathGenerationService.generate_personalized_path(enrollment)

                # Геймификация и nudge
                # GamificationService.award_badge(student, "LEVEL_UP", f"Переход на {new_level}")
                # NotificationService.send_level_up_congratulations(student, new_level)

                adapted = True

        # Правило 6: Нет прогресса (overall ~0 в 3+ уроках) → регенерация пути
        recent_deltas = enrollment.skill_deltas.order_by("-calculated_at")[:3]
        if all(abs(d.deltas.get("overall", 0)) < 0.05 for d in recent_deltas):
            PathGenerationService.generate_personalized_path(enrollment)
            path.metadata["reason"] = "Stagnation detected — regenerated path"
            adapted = True

        # Правило 7: Высокий engagement (>8) → добавление бонусных практик
        if student.engagement_level > 8:
            bonus_lesson = Lesson.objects.filter(skill_focus__overlap=strong_skills, type="practice").first()
            if bonus_lesson:
                new_node = {
                    "node_id": len(path.nodes) + 1,
                    "lesson_id": bonus_lesson.id,
                    "title": f"Бонус: {bonus_lesson.title} ({', '.join(strong_skills)})",
                    "reason": f"Высокая вовлечённость: используем сильные навыки",
                    "type": "bonus",
                    "prerequisites": [],
                    "status": "recommended"
                }
                path.nodes.insert(path.current_node_index + 1, new_node)
                adapted = True

        if adapted:
            path.save()
            # Отправка nudges о изменениях
            # from curriculum.services.notification_service import NotificationService
            # NotificationService.send_path_update_nudge(student, path)