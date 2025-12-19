import random

from feedback.services.tone_adapter import ToneAdapter

from curriculum.services.decisions import LessonOutcome
from curriculum.services.feedback.template_loader import FeedbackTemplateLoader


class FeedbackBuilder:
    """
    Формирует мотивационную и объясняющую обратную связь для студента
    на основе результатов урока и принятого решения.

    Использует:
    - решение адаптивного движка (LessonOutcome)
    - метрики урока (LessonMetrics)
    - тон общения (ToneAdapter)

    Не влияет на логику обучения.

    {
      "title": "Хорошая работа!",
      "message": "Ты уверенно справился с заданием и можешь двигаться дальше.",
      "highlights": [
        "Грамматика: стабильно",
        "Словарный запас: выше среднего"
      ],
      "next_step_hint": "Следующий урок будет чуть сложнее."
    }
    """

    def __init__(self):
        self.templates = FeedbackTemplateLoader()

    def _build(self, template_name, tone, highlights):
        tpl = self.templates.load(template_name)

        return {
            "title": tpl["title"],
            "message": f"{tone} {random.choice(tpl['messages'])}",
            "highlights": highlights,
            "next_step_hint": random.choice(tpl["next_step"]),
        }

    def _success_feedback(self, tone, metrics):
        return self._build(
            template_name="success",
            tone=tone.praise(),
            highlights=metrics.top_skills(),
        )

    def _supportive_feedback(self, tone, metrics):
        return self._build(
            template_name="simplify",
            tone=tone.support(),
            highlights=metrics.weak_spots(limit=2),
        )

    def _retry_feedback(self, tone, metrics):
        return self._build(
            template_name="retry",
            tone=tone.retry(),
            highlights=metrics.weak_spots(limit=1),
        )

    def _neutral_feedback(self, tone):
        return self._build(
            template_name="neutral",
            tone=tone.neutral(),
            highlights=[],
        )


    #
    #
    # # версия без yaml
    # def build(self, student, lesson, metrics, decision, assessment=None) -> dict:
    #     tone = ToneAdapter().select(student, metrics)
    #
    #     if decision == LessonOutcome.ADVANCE:
    #         return self._success_feedback(tone, metrics)
    #
    #     if decision == LessonOutcome.SIMPLIFY:
    #         return self._supportive_feedback(tone, metrics)
    #
    #     if decision == LessonOutcome.REPEAT:
    #         return self._retry_feedback(tone, metrics)
    #
    #     return self._neutral_feedback(tone)
    #
    # def _success_feedback(self, tone, metrics):
    #     return {
    #         "title": "Отлично!",
    #         "message": tone.praise(),
    #         "highlights": metrics.top_skills(),
    #         "next_step_hint": "Следующий урок будет чуть сложнее."
    #     }
    #
    # def _supportive_feedback(self, tone, metrics):
    #     return {
    #         "title": "Ничего страшного",
    #         "message": tone.support(),
    #         "highlights": metrics.weak_spots(limit=2),
    #         "next_step_hint": "Мы немного упростим следующий шаг."
    #     }
    #
    # def _retry_feedback(self, tone, metrics):
    #     return {
    #         "title": "Давай закрепим",
    #         "message": tone.retry(),
    #         "highlights": metrics.weak_spots(limit=1),
    #         "next_step_hint": "Повторим этот урок с новыми примерами."
    #     }
    #
    # def _neutral_feedback(self, tone):
    #     return {
    #         "title": "Продолжаем",
    #         "message": tone.neutral(),
    #         "highlights": [],
    #         "next_step_hint": "Идём дальше."
    #     }
