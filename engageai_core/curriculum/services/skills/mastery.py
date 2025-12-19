# engageai_core/learning/skills/mastery.py
from curriculum.models import SkillProfile


class SkillMasteryDetector:
    """
    Определяет, достиг ли студент устойчивого владения навыком.
    """

    def is_mastered(self, profile: SkillProfile) -> bool:
        return profile.score >= 0.85 and profile.confidence >= 0.75
