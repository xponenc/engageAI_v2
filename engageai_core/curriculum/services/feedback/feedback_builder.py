import random

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

    📍 Это оперативная обратная связь, а не объяснение логики.
    Он отвечает на вопрос студента:
    «Как я справился и что дальше?»
    ❗ Он НЕ отвечает:
    почему система приняла именно это решение
    почему урок упростился / повторился
    что это значит в долгосрочном плане
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
