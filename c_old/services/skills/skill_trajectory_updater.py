# curriculum/services/skills/skill_trajectory_updater.py
import logging

from django.utils import timezone
from typing import List, Dict, Any, Optional
from curriculum.models.skills.skill_trajectory import SkillTrajectory
from curriculum.models.skills.skill_snapshot import SkillSnapshot
from users.models import Student

logger = logging.getLogger(__name__)


class SkillTrajectoryUpdater:
    """
    Обновляет траектории навыков студентов в двух режимах:

    1. SINGLE_SNAPSHOT_MODE (update_from_snapshot):
       - Обновление на основе одного снимка (после завершения урока)
       - Быстрый расчет трендов и стабильности
       - Используется в фоновых задачах оценки

    2. HISTORICAL_MODE (update):
       - Глубокий анализ на основе всей истории (минимум 3 снимка)
       - Статистически значимые тренды и стабильность
       - Используется для периодических пересчетов и аналитики
    """

    MIN_SNAPSHOTS_FOR_HISTORICAL = 3

    def update_from_snapshot(
            self,
            student: Student,
            snapshot: SkillSnapshot,
            metrics: Optional[Dict[str, Any]] = None
    ) -> List[SkillTrajectory]:
        """
        Обновляет траектории на основе одного снимка (режим SINGLE_SNAPSHOT_MODE).

        Используется:
        - После завершения урока в фоновой задаче
        - Для немедленного отражения прогресса

        Алгоритм:
        1. Для каждого навыка обновляем текущее значение
        2. Рассчитываем простой тренд (разница с предыдущим значением)
        3. Устанавливаем начальную стабильность
        4. Обновляем историю

        Args:
            student: Студент
            snapshot: Новый снимок навыков
            metrics: Дополнительные метрики для расчета (опционально)

        Returns:
            List[SkillTrajectory]: Список обновленных траекторий
        """
        trajectories = []
        skills = ['grammar', 'vocabulary', 'listening', 'reading', 'writing', 'speaking']

        for skill in skills:
            current_value = getattr(snapshot, skill, 0.5)

            # Получаем существующую траекторию или создаем новую
            trajectory, created = SkillTrajectory.objects.get_or_create(
                student=student,
                skill=skill,
                defaults={
                    'trend': 0.0,
                    'stability': 0.8,  # Начальная стабильность
                }
            )
            # TODO разобраться с траекторией
            # Сохраняем предыдущее значение
            # previous_value = trajectory.current_value
            #
            # # Обновляем текущее значение
            # trajectory.current_value = current_value
            # trajectory.last_updated = timezone.now()
            #
            # # Рассчитываем тренд
            # if created:
            #     trajectory.trend = 0.0  # Новая траектория - нет тренда
            # else:
            #     # Простой тренд: разница между текущим и предыдущим значением
            #     trajectory.trend = current_value - previous_value
            #
            #     # Сглаживаем резкие изменения
            #     if abs(trajectory.trend) > 0.3:
            #         trajectory.trend *= 0.5

            # Обновляем стабильность
            if created:
                trajectory.stability = 0.8  # Начальное значение для новых навыков
            else:
                # Сохраняем часть предыдущей стабильности
                trajectory.stability = max(0.3, trajectory.stability * 0.9)

            # Обновляем историю
            self._append_to_history(trajectory, current_value, snapshot.snapshot_at)

            # Сохраняем траекторию
            trajectory.save()
            trajectories.append(trajectory)

        return trajectories

    def update(self, student: Student) -> List[SkillTrajectory]:
        """
        Глубокое обновление траекторий на основе всей истории (режим HISTORICAL_MODE).

        Требования:
        - Минимум 3 снимка для статистической значимости
        - Использует сложные алгоритмы расчета трендов

        Используется:
        - Для периодических пересчетов (раз в день/неделю)
        - В аналитических отчетах
        - При ручном запросе преподавателя

        Args:
            student: Студент

        Returns:
            List[SkillTrajectory]: Список обновленных траекторий
        """
        snapshots = SkillSnapshot.objects.filter(
            student=student
        ).order_by("snapshot_at")

        if snapshots.count() < self.MIN_SNAPSHOTS_FOR_HISTORICAL:
            logger.info(
                f"Skipping historical update for student {student.pk}: "
                f"only {snapshots.count()} snapshots available, "
                f"need at least {self.MIN_SNAPSHOTS_FOR_HISTORICAL}"
            )
            return []  # недостаточно данных

        # Группируем значения по навыкам
        skill_values = {
            "grammar": [],
            "vocabulary": [],
            "listening": [],
            "reading": [],
            "writing": [],
            "speaking": [],
        }

        # Собираем исторические данные
        for snap in snapshots:
            for skill in skill_values.keys():
                skill_values[skill].append(getattr(snap, skill))

        # Обновляем траектории для каждого навыка
        trajectories = []
        for skill, values in skill_values.items():
            if len(values) < self.MIN_SNAPSHOTS_FOR_HISTORICAL:
                continue

            # Рассчитываем сложные метрики
            trend = self._calculate_historical_trend(values)
            stability = self._calculate_historical_stability(values)

            # Обновляем или создаем траекторию
            obj, _ = SkillTrajectory.objects.get_or_create(
                student=student,
                skill=skill
            )

            obj.trend = trend
            obj.stability = stability
            obj.last_updated = timezone.now()
            obj.save()

            trajectories.append(obj)

        return trajectories

    def _append_to_history(
            self,
            trajectory: SkillTrajectory,
            new_value: float,
            timestamp: timezone.datetime
    ) -> None:
        """
        Добавляет новое значение в историю траектории.

        Оптимизация:
        - Ограничиваем историю 20 последними значениями
        - Храним только timestamp и значение
        """
        if not hasattr(trajectory, 'history') or trajectory.history is None:
            trajectory.history = {'timestamps': [], 'values': []}

        # Добавляем новое значение
        trajectory.history['timestamps'].append(timestamp.isoformat())
        trajectory.history['values'].append(new_value)

        # Ограничиваем размер истории
        max_history = 20
        if len(trajectory.history['timestamps']) > max_history:
            trajectory.history['timestamps'] = trajectory.history['timestamps'][-max_history:]
            trajectory.history['values'] = trajectory.history['values'][-max_history:]

    def _calculate_historical_trend(self, values: List[float]) -> float:
        """
        Рассчитывает статистически значимый тренд на основе исторических данных.

        Использует метод линейной регрессии для определения направления тренда.
        """
        if len(values) < 2:
            return 0.0

        # Простая линейная регрессия: y = a + b*x
        n = len(values)
        x = list(range(n))

        # Средние значения
        x_mean = sum(x) / n
        y_mean = sum(values) / n

        # Коэффициенты регрессии
        numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, values))
        denominator = sum((xi - x_mean) ** 2 for xi in x)

        if denominator == 0:
            return 0.0

        b = numerator / denominator  # Наклон линии тренда
        return max(-0.5, min(0.5, b))  # Ограничиваем разумные значения

    def _calculate_historical_stability(self, values: List[float]) -> float:
        """
        Рассчитывает стабильность на основе стандартного отклонения.

        Стабильность = 1 - нормализованное стандартное отклонение
        """
        if len(values) < 2:
            return 1.0

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        std_dev = variance ** 0.5

        # Нормализуем стандартное отклонение
        normalized_std = std_dev / max(0.1, mean)  # Избегаем деления на ноль

        # Преобразуем в стабильность (0-1)
        stability = max(0.0, min(1.0, 1.0 - normalized_std))

        # Добавляем минимальную стабильность
        return max(0.2, stability)
