from .base import BaseTone


class GentleTone(BaseTone):
    """
    Мягкий, поддерживающий тон для студентов
    с серией неудач или низкой уверенностью.
    """

    def praise(self):
        return "Ты стараешься, и это видно. Отличная работа."

    def support(self):
        return "Ошибки — часть обучения. Давай разберёмся спокойно."

    def retry(self):
        return "Ничего страшного. Повтор поможет закрепить материал."
