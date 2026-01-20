# curriculum/services/skills/skill_update_service.py
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional
from django.db import transaction
from django.utils import timezone

from curriculum.models import Task
from curriculum.models.skills.skill_delta import SkillDelta
from curriculum.models.skills.skill_snapshot import SkillSnapshot
from curriculum.models.skills.skill_trajectory import SkillTrajectory
from curriculum.models.student.enrollment import Enrollment
from curriculum.models.assessment.assessment import Assessment
from curriculum.models.skills.skill_profile import CurrentSkillProfile
from curriculum.services.skills.skill_delta_calculator import SkillDeltaCalculator
from curriculum.services.skills.skill_trajectory_updater import SkillTrajectoryUpdater

logger = logging.getLogger(__name__)


@dataclass
class SkillUpdateResult:
    """
    Результат обновления навыков после оценки задания.
    Используется для передачи данных между сервисами.
    """
    updated_skills: Dict[str, float]
    deltas: Dict[str, float]
    snapshot: Optional[SkillSnapshot] = None
    error_events: List[str] = None

    def __post_init__(self):
        if self.error_events is None:
            self.error_events = []


@dataclass
class LessonSkillSnapshotResult:
    """
    Результат создания снимка навыков по уроку

    Используется для:
    - DecisionService
    - TransitionRecorder
    - Explainability
    - Аудита и аналитики
    """
    snapshot: SkillSnapshot
    trajectories: List[SkillTrajectory]
    aggregated_scores: Dict[str, float]
    skill_progress: Dict[str, Dict[str, float]]  # {skill: {before, after, delta}}
    error_events: List[str]


class SkillUpdateService:
    """
    SkillUpdateService обновляет состояние навыков студента
    на основе результатов оценки.

    Основные режимы работы:
    1. Single-task: обновление по одному заданию
    2. Lesson-batch: агрегирование по всему уроку

    Архитектурные принципы:
    1. Инвариант: один snapshot = один урок
    2. Атомарность: все обновления в одной транзакции
    3. Отказоустойчивость: частичное сохранение при ошибках
    """

    def __init__(self):
        self.trajectory_updater = SkillTrajectoryUpdater()
        self.delta_calculator = SkillDeltaCalculator()

    # В SkillUpdateService или отдельном SkillDeltaService

    # TODO новый метод
    @staticmethod
    def calculate_and_save_delta(enrollment, lesson):
        # POST — только что созданный снимок
        post_snapshot = SkillSnapshot.objects.filter(
            enrollment=enrollment,
            associated_lesson=lesson,
            snapshot_context="POST_LESSON"
        ).first()

        if not post_snapshot:
            return None

        # PRE — последний снимок ДО текущего урока
        pre_snapshot = SkillSnapshot.objects.filter(
            enrollment=enrollment,
            snapshot_at__lt=post_snapshot.snapshot_at
        ).order_by("-snapshot_at").first()

        if not pre_snapshot:
            return None  # Первый урок — нет delta

        # Расчёт delta
        deltas = {}
        all_skills = set(pre_snapshot.skills.keys()) | set(post_snapshot.skills.keys())
        for skill in all_skills:
            pre_val = pre_snapshot.skills.get(skill, 0.0)
            post_val = post_snapshot.skills.get(skill, 0.0)
            deltas[skill] = round(post_val - pre_val, 3)

        if deltas:
            deltas["overall"] = round(sum(deltas.values()) / len(deltas), 3)

        # Сохраняем
        SkillDelta.objects.update_or_create(
            student=enrollment.student,
            lesson=lesson,
            defaults={
                "enrollment": enrollment,
                "pre_snapshot": pre_snapshot,
                "post_snapshot": post_snapshot,
                "deltas": deltas,
                "metadata": {
                    "duration_min": post_snapshot.metadata.get("duration_min"),
                    "lesson_score": post_snapshot.metadata.get("lesson_score")
                }
            }
        )

    def create_lesson_snapshot(
            self,
            enrollment: Enrollment,
            assessments: List[Assessment],
            lesson_context: Optional[dict] = None
    ) -> LessonSkillSnapshotResult:
        """
        Создает снимок навыков по всему уроку на основе множественных оценок.

        Алгоритм:
        1. Загружаем текущий профиль навыков
        2. Агрегируем оценки по всему уроку
        3. Рассчитываем дельты для каждого навыка
        4. Создаем snapshot и обновляем траектории
        5. Генерируем метрики прогресса

        Args:
            enrollment: Зачисление студента
            assessments: Список оценок по всем заданиям урока
            lesson_context: Контекст урока (опционально)

        Returns:
            LessonSkillSnapshotResult: Результат с созданным снимком
        """
        try:
            with transaction.atomic():
                # 1. Получаем текущий профиль навыков
                skill_profile, _ = CurrentSkillProfile.objects.get_or_create(
                    student=enrollment.student
                )

                # 2. Вычисляем агрегированные метрики по уроку
                aggregated_metrics = self._calculate_lesson_metrics(
                    assessments=assessments,
                    skill_profile=skill_profile
                )

                # 3. Создаем snapshot на основе агрегированных данных
                snapshot = SkillSnapshot.objects.create(
                    student=enrollment.student,
                    grammar=aggregated_metrics['aggregated_scores'].get('grammar', 0.5),
                    vocabulary=aggregated_metrics['aggregated_scores'].get('vocabulary', 0.5),
                    listening=aggregated_metrics['aggregated_scores'].get('listening', 0.5),
                    reading=aggregated_metrics['aggregated_scores'].get('reading', 0.5),
                    writing=aggregated_metrics['aggregated_scores'].get('writing', 0.5),
                    speaking=aggregated_metrics['aggregated_scores'].get('speaking', 0.5),

                )

                # 4. Обновляем траектории навыков
                trajectories = self.trajectory_updater.update_from_snapshot(
                    student=enrollment.student,
                    snapshot=snapshot,
                    metrics=aggregated_metrics
                )

                # 5. Генерируем детальный прогресс по навыкам
                skill_progress = self._calculate_skill_progress(
                    before_snapshot=skill_profile.to_dict(),
                    after_snapshot=snapshot,
                    metrics=aggregated_metrics
                )

                return LessonSkillSnapshotResult(
                    snapshot=snapshot,
                    trajectories=trajectories,
                    aggregated_scores=aggregated_metrics['aggregated_scores'],
                    skill_progress=skill_progress,
                    error_events=[]
                )

        except Exception as e:
            logger.error(f"Error creating lesson snapshot for enrollment {enrollment.pk}: {str(e)}", exc_info=True)
            raise

    def _calculate_lesson_metrics(
            self,
            assessments: List[Assessment],
            skill_profile: CurrentSkillProfile
    ) -> dict:
        """
        Рассчитывает агрегированные метрики по всему уроку.

        Обрабатывает:
        - Средние оценки по навыкам
        - Взвешенные оценки по сложности заданий
        - Процент правильных ответов
        - Прогресс по сравнению с предыдущим состоянием
        """
        skill_scores = {
            'grammar': [],
            'vocabulary': [],
            'listening': [],
            'reading': [],
            'writing': [],
            'speaking': []
        }

        task_metadata = []
        error_tags = []

        # Собираем все оценки из всех заданий
        for assessment in assessments:
            feedback = assessment.structured_feedback or {}
            skill_evaluation = feedback.get('skill_evaluation', {})

            # Собираем оценки по навыкам
            for skill, skill_data in skill_evaluation.items():
                score = skill_data.get("score")
                if isinstance(score, (int, float)):  # включает 0.0, 1.0, 0.5 и т.д.
                    skill_scores[skill].append(score)

            # Собираем теги ошибок
            if 'errors' in feedback:
                for error in feedback['errors']:
                    error_tags.append(error.get('type', 'unknown'))

        # Вычисляем агрегированные оценки
        aggregated_scores = {}
        for skill, scores in skill_scores.items():
            if scores:
                # Взвешенная оценка с учетом текущего уровня студента
                current_level = getattr(skill_profile, skill, 0.5)
                # Чем ниже текущий уровень — тем больше вес новых (даже нулевых!) оценок
                weight_new = 0.3 + 0.7 * (1 - current_level)

                avg_score = sum(scores) / len(scores)
                # Применяем вес: больше влияния на слабые навыки
                aggregated_scores[skill] = current_level * (1 - weight_new) + avg_score * weight_new
                # Альтернатива: просто взять avg_score, если не нужна взвешенность по уровню
                # aggregated_scores[skill] = avg_score
            else:
                # Используем текущий уровень если нет данных
                aggregated_scores[skill] = getattr(skill_profile, skill, 0.5)

        return {
            'aggregated_scores': aggregated_scores,
            'task_metadata': task_metadata,
            'error_tags': list(set(error_tags)),  # Уникальные теги ошибок
            'completion_rate': len(assessments) / max(1, len(skill_scores['grammar'])),  # Упрощенно
            'lesson_difficulty': self._estimate_lesson_difficulty(task_metadata),
            'skill_gaps': self._identify_skill_gaps(aggregated_scores, skill_profile)
        }

    def _create_snapshot_from_metrics(
            self,
            enrollment: Enrollment,
            metrics: dict,
            context: dict
    ) -> SkillSnapshot:
        """
        Создает SkillSnapshot из агрегированных метрик.
        """
        snapshot = SkillSnapshot.objects.create(
            student=enrollment.student,
            lesson=enrollment.current_lesson,
            enrollment=enrollment,
            grammar=metrics['aggregated_scores'].get('grammar', 0.5),
            vocabulary=metrics['aggregated_scores'].get('vocabulary', 0.5),
            listening=metrics['aggregated_scores'].get('listening', 0.5),
            reading=metrics['aggregated_scores'].get('reading', 0.5),
            writing=metrics['aggregated_scores'].get('writing', 0.5),
            speaking=metrics['aggregated_scores'].get('speaking', 0.5),
            context_data={
                'metrics': metrics,
                'context': context,
                'created_at': timezone.now().isoformat()
            }
        )
        return snapshot

    def _estimate_lesson_difficulty(self, task_metadata: list) -> float:
        """Оценивает сложность урока на основе метаданных заданий"""
        if not task_metadata:
            return 0.5

        scores = [item.get('overall_score', 0.5) for item in task_metadata]
        avg_score = sum(scores) / len(scores)

        # Сложность обратно пропорциональна среднему баллу
        difficulty = 1.0 - avg_score
        return max(0.1, min(0.9, difficulty))

    def _identify_skill_gaps(self, aggregated_scores: dict, skill_profile: CurrentSkillProfile) -> list:
        """Определяет пробелы в навыках на основе отклонений от целевых уровней"""
        gaps = []
        target_level = 0.7  # Целевой уровень для большинства студентов

        for skill, score in aggregated_scores.items():
            current = getattr(skill_profile, skill, 0.5)
            if current < target_level and score < target_level:
                gaps.append({
                    'skill': skill,
                    'current_level': current,
                    'lesson_score': score,
                    'gap': target_level - max(current, score)
                })

        return sorted(gaps, key=lambda x: x['gap'], reverse=True)

    def _calculate_skill_progress(
            self,
            before_snapshot: dict,
            after_snapshot: SkillSnapshot,
            metrics: dict
    ) -> dict:
        """Рассчитывает детальный прогресс по каждому навыку"""
        progress = {}
        for skill in ['grammar', 'vocabulary', 'listening', 'reading', 'writing', 'speaking']:
            before_value = before_snapshot.get(skill, 0.5)
            after_value = getattr(after_snapshot, skill, 0.5)
            delta = after_value - before_value

            progress[skill] = {
                'before': round(before_value, 3),
                'after': round(after_value, 3),
                'delta': round(delta, 3),
                'lesson_score': round(metrics['aggregated_scores'].get(skill, 0.5), 3)
            }
        return progress


def update(
        self,
        enrollment: Enrollment,
        task: Task,
        assessment_result: Assessment,
) -> SkillUpdateResult:
    """
    Основной метод обновления навыков.
    Алгоритм (v1):
    1. Загружаем текущий SkillProfile
    2. Интерпретируем assessment → skill deltas
    3. Обновляем профиль
    4. Фиксируем snapshot и trajectory
    5. Логируем ошибки
    """
    # Получаем текущий профиль
    skill_profile, _ = CurrentSkillProfile.objects.get_or_create(
        student=enrollment.student
    )

    # Получаем текущие навыки как словарь
    current_skills = skill_profile.to_dict()

    # Рассчитываем дельты
    deltas = self.delta_calculator.calculate(
        assessment=assessment_result,
        task=task,
        enrollment=enrollment,
    )

    # Обновляем навыки
    updated_skills = {}
    for skill_name, delta in deltas.items():
        if skill_name in current_skills:
            new_value = max(0.0, min(1.0, current_skills[skill_name] + delta))
            current_skills[skill_name] = new_value
            updated_skills[skill_name] = new_value

    # Сохраняем обновленные навыки
    skill_profile.update_from_dict(current_skills)
    skill_profile.save()

    # Создаем snapshot
    snapshot = SkillSnapshot.objects.create(
        student=enrollment.student,
        **current_skills
    )

    # Обновляем траекторию
    self.trajectory_updater.update(enrollment.student)

    return SkillUpdateResult(
        updated_skills=updated_skills,
        deltas=deltas,
        snapshot=snapshot,
        error_events=[]
    )
