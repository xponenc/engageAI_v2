"""
LearningObjectiveEvaluationService
=================================

Сервис агрегации результатов урока на уровне LearningObjective.

Назначение:
- Собирает результаты оценки заданий (TaskAssessment)
- Агрегирует skill-оценки по LearningObjective
- Формирует каноническую структуру данных для LearningPathAdaptationService

ВАЖНЫЕ ИНВАРИАНТЫ:
- В системе НЕТ повторных попыток заданий (attempts)
- Одна сессия урока = одна попытка по каждой LearningObjective
- Попытки LearningObjective считаются на уровне уроков, а не заданий

Место в пайплайне:

TaskAssessments
    ↓
LearningObjectiveEvaluationService
    ↓
LessonOutcomeContext
    ↓
LearningPathAdaptationService
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List

from curriculum.models import LearningObjective


# ============================================================
# DTO
# ============================================================

@dataclass
class LearningObjectiveEvaluation:
    """
    Результат агрегации по одной LearningObjective.
    """

    identifier: str
    avg_score: float
    attempts: int = 1  # MVP: всегда 1 (один урок = одна попытка)


# ============================================================
# Service
# ============================================================

class LearningObjectiveEvaluationService:
    """
    Сервис оценки LearningObjective по результатам урока.

    Вход:
    - список TaskResponse / TaskAssessment

    Выход:
    - Dict[learning_objective.identifier, LearningObjectiveEvaluation]

    Принципы:
    - Мы НЕ оцениваем LearningObjective напрямую через LLM
    - Мы агрегируем skill scores задач, привязанных к LearningObjective
    - Если LO не получила ни одной оценки → она игнорируется
    """

    @staticmethod
    def evaluate(
        task_assessments: List[dict],
    ) -> Dict[str, LearningObjectiveEvaluation]:
        """
        Основной метод агрегации.

        task_assessments — список словарей вида:
        {
            "learning_objectives": ["grammar-B1-01", "grammar-B1-02"],
            "skill_evaluation": {
                "grammar": {"score": 0.6},
                "vocabulary": None,
                ...
            }
        }
        """

        # Временное хранилище score-ов по LO
        lo_scores: Dict[str, List[float]] = defaultdict(list)

        for assessment in task_assessments:
            lo_ids = assessment.get("learning_objectives", [])
            skill_eval = assessment.get("skill_evaluation", {})

            # Берём только числовые score
            numeric_scores = [
                v.get("score")
                for v in skill_eval.values()
                if isinstance(v, dict) and isinstance(v.get("score"), (int, float))
            ]

            if not numeric_scores:
                continue

            task_avg_score = sum(numeric_scores) / len(numeric_scores)

            for lo_id in lo_ids:
                lo_scores[lo_id].append(task_avg_score)

        # Формируем итоговую структуру
        results: Dict[str, LearningObjectiveEvaluation] = {}

        for lo_id, scores in lo_scores.items():
            results[lo_id] = LearningObjectiveEvaluation(
                identifier=lo_id,
                avg_score=sum(scores) / len(scores),
                attempts=1,  # MVP: всегда 1
            )

        return results


# ============================================================
# Пример использования
# ============================================================

"""
lesson_task_assessments = [
    {
        "learning_objectives": ["grammar-B1-01"],
        "skill_evaluation": {
            "grammar": {"score": 0.6},
            "vocabulary": None,
        }
    },
    {
        "learning_objectives": ["grammar-B1-01", "grammar-B1-02"],
        "skill_evaluation": {
            "grammar": {"score": 0.4},
        }
    }
]

lo_results = LearningObjectiveEvaluationService.evaluate(lesson_task_assessments)
"""
