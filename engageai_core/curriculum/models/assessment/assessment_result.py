from dataclasses import dataclass
from typing import Optional, List, Dict, Any


@dataclass(frozen=True)
class AssessmentResult:
    """
    Чистый доменный объект результата оценки.
    Не зависит от Django или базы данных.
    Хранит результаты по навыкам и краткое резюме с советами.
    """
    task_id: int
    is_correct: bool
    cefr_target: str
    skill_evaluation: Dict[str, Dict[str, Any]]
    summary: Dict[str, Any]
    error_tags: List[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        # Проверяем ключи skill_evaluation
        expected_skills = ["grammar", "vocabulary", "reading", "listening", "writing", "speaking"]
        for skill in expected_skills:
            if skill not in self.skill_evaluation:
                raise ValueError(f"Missing skill evaluation for '{skill}'")
            eval_data = self.skill_evaluation[skill]
            # Проверка score и confidence
            score = eval_data.get("score")
            confidence = eval_data.get("confidence")
            if score is not None and not (0.0 <= score <= 1.0):
                raise ValueError(f"Score for '{skill}' must be between 0.0 and 1.0")
            if confidence is not None and not (0.0 <= confidence <= 1.0):
                raise ValueError(f"Confidence for '{skill}' must be between 0.0 and 1.0")
            # Инициализация пустых списков
            if "evidence" not in eval_data or eval_data["evidence"] is None:
                eval_data["evidence"] = []

        # Проверка summary
        if not isinstance(self.summary, dict):
            raise ValueError("Summary must be a dictionary")
        if "text" not in self.summary or "advice" not in self.summary:
            raise ValueError("Summary must contain 'text' and 'advice'")
        if not isinstance(self.summary["advice"], list):
            raise ValueError("'advice' in summary must be a list")

        # Инициализация дополнительных полей
        if self.error_tags is None:
            object.__setattr__(self, "error_tags", [])
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})
