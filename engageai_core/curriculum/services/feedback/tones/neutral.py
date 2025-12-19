from .base import BaseTone


class NeutralTone(BaseTone):
    """
    Нейтральный, спокойный тон по умолчанию.
    """

    def praise(self):
        return "Хорошая работа."

    def support(self):
        return "Давай продолжим шаг за шагом."

    def retry(self):
        return "Повторим материал для закрепления."
