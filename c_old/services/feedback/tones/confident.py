from .base import BaseTone


class ConfidentTone(BaseTone):
    """
    Уверенный, энергичный тон для сильных студентов.
    """

    def praise(self):
        return "Отличный результат! Ты уверенно движешься вперёд."

    def support(self):
        return "Чуть сложнее, но тебе это по силам."

    def retry(self):
        return "Небольшая пауза и закрепление — и пойдём дальше."
