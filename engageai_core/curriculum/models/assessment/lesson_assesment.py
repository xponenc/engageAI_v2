from typing import Any, Dict, Optional, List

from django.db import models

from curriculum.models.content.lesson import Lesson
from curriculum.models.student.enrollment import Enrollment
from curriculum.validators import SkillDomain


class AssessmentStatus(models.TextChoices):
    PENDING = "PENDING", "Ожидание оценки"
    PROCESSING = "PROCESSING", "Оценка в процессе"
    COMPLETED = "COMPLETED", "Оценка завершена"
    ERROR = "ERROR", "Ошибка оценки"


class LessonAssessmentResult(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name='assessment_results')
    lesson = models.ForeignKey(Lesson, on_delete=models.SET_NULL, null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    overall_score = models.FloatField(null=True, blank=True)  # 0.0–1.0
    structured_feedback = models.JSONField(default=dict)  # {'grammar': 0.85, 'speaking': 0.62, ...}
    llm_summary = models.TextField(blank=True)  # Итоговое резюме LLM
    llm_recommendations = models.TextField(blank=True)  # "Рекомендуем больше практики speaking"
    status = models.CharField(max_length=20, default=AssessmentStatus.PENDING, choices=AssessmentStatus)
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ['enrollment', 'lesson']

    @classmethod
    def aggregate_skill_feedback(cls, task_assessments: List["TaskAssessmentResult"]) -> Dict[str, Optional[dict]]:
        """
        Агрегирует оценки навыков по всем заданиям урока с учётом confidence.

        Ожидается, что в TaskAssessmentResult.structured_feedback лежит:
        {
            "skill_evaluation": {
                "grammar": {"score": 0.8, "confidence": 0.9, "evidence": [...]},
                ...
            },
            "summary": {...},
            ...
        }

        Результат:
        {
            "grammar": {
                "score": 0.85,
                "confidence": 0.92,
                "evidence": ["...", "..."],
                "tasks_count": 3
            },
            ...
        }
        """
        skills = list(SkillDomain.values)

        aggregates: Dict[str, Dict[str, Any]] = {
            skill: {
                "weighted_sum": 0.0,
                "weight_sum": 0.0,
                "confidences": [],
                "evidence": [],
                "tasks_count": 0,
            }
            for skill in skills
        }

        for ta in task_assessments:
            sf = ta.structured_feedback or {}
            skill_eval = sf.get("skill_evaluation", {})

            for skill_name in skills:
                data = skill_eval.get(skill_name)
                if not isinstance(data, dict):
                    continue

                score = cls._to_float(data.get("score"))
                confidence = cls._to_float(data.get("confidence"))

                if score is None:
                    continue

                # Если confidence нет, считаем его равным 1.0 (равный вес)
                weight = confidence if confidence is not None else 1.0

                agg = aggregates[skill_name]
                agg["weighted_sum"] += score * weight
                agg["weight_sum"] += weight
                agg["tasks_count"] += 1

                if confidence is not None:
                    agg["confidences"].append(confidence)

                evidence = data.get("evidence") or []
                if isinstance(evidence, list):
                    agg["evidence"].extend(evidence)

        # Формируем итог
        result: Dict[str, Optional[dict]] = {}

        for skill_name, agg in aggregates.items():
            if agg["tasks_count"] == 0 or agg["weight_sum"] == 0.0:
                # Навык не оценивался в этом уроке
                result[skill_name] = None
                continue

            weighted_avg_score = agg["weighted_sum"] / agg["weight_sum"]

            if agg["confidences"]:
                avg_confidence = sum(agg["confidences"]) / len(agg["confidences"])
            else:
                # если confidence нигде не было, можно интерпретировать как 1.0
                avg_confidence = 1.0

            result[skill_name] = {
                "score": round(weighted_avg_score, 3),
                "confidence": round(avg_confidence, 3),
                "evidence": agg["evidence"][:5],
                "tasks_count": agg["tasks_count"],
            }

        return result

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            value = value.replace(",", ".")
            try:
                return float(value)
            except ValueError:
                return None
        return None


    @staticmethod
    def calculate_overall_score(task_assessments: list, strategy: str = 'hybrid') -> float:
        """
        Рассчитывает общий балл урока.

        Стратегии:
        - 'simple': простое среднее по всем заданиям
        - 'hybrid': комбинация (0.5 * средний балл + 0.5 * доля правильных)
        - 'weighted': взвешенное среднее по сложности заданий
        """
        if not task_assessments:
            return 0.0

        if strategy == 'simple':
            # Простое среднее
            scores = [ta.score for ta in task_assessments if ta.score is not None]
            return sum(scores) / len(scores) if scores else 0.0

        elif strategy == 'hybrid':
            # Комбинированная оценка
            scores = [ta.score for ta in task_assessments if ta.score is not None]
            avg_score = sum(scores) / len(scores) if scores else None

            correct_flags = [ta.is_correct for ta in task_assessments if ta.is_correct is not None]
            correct_ratio = (
                sum(1 for f in correct_flags if f) / len(correct_flags)
                if correct_flags else None
            )

            if avg_score is not None and correct_ratio is not None:
                return 0.5 * avg_score + 0.5 * correct_ratio
            elif avg_score is not None:
                return avg_score
            else:
                return correct_ratio if correct_ratio is not None else 0.0

        elif strategy == 'weighted':
            # Взвешенное среднее по сложности
            total_weight = sum(ta.task.get_difficulty_weight() for ta in task_assessments if ta.score is not None)
            if total_weight == 0:
                return 0.0

            weighted_sum = sum(
                ta.score * ta.task.get_difficulty_weight()
                for ta in task_assessments
                if ta.score is not None
            )
            return weighted_sum / total_weight
