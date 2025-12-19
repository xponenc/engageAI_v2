from .tones.confident import ConfidentTone
from .tones.gentle import GentleTone
from .tones.neutral import NeutralTone


class ToneAdapter:
    """
    Выбирает эмоциональный тон на основе метрик урока.
    """

    def select(self, student, metrics):
        if metrics.failure_streak >= 3:
            return GentleTone()

        if metrics.success_ratio > 0.9:
            return ConfidentTone()

        return NeutralTone()