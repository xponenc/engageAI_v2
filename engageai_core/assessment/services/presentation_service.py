from django.db.models import Count
from assessment.models import QuestionInstance, TestSession

#
# class QuestionPresentationService:
#     """Сервис для форматирования вопросов для разных платформ"""
#
#     def format_for_web(self, question_instance):
#         """
#         Форматирует question_json для отображения в веб-интерфейсе.
#         Разделяет текст на контекст и сам вопрос при наличии маркеров "Text:" и "Question:".
#         """
#         question_text = question_instance.question_json.get("question_text", "")
#         text_content = ""
#         question_content = question_text
#
#         if "Text:" in question_text and "Question:" in question_text:
#             try:
#                 text_part = question_text.split("Text:", 1)[1]
#                 parts = text_part.split("Question:", 1)
#                 text_content = parts[0].strip()
#                 question_content = parts[1].strip() if len(parts) > 1 else ""
#             except (IndexError, ValueError):
#                 pass
#
#         return {
#             "full_text": question_text,
#             "text_content": text_content,
#             "question_content": question_content,
#         }


class AssessmentProgressService:
    """Сервис для работы с прогрессом тестирования"""

    def get_question_number(self, session: TestSession) -> int:
        """
        Возвращает номер текущего вопроса (1-индексированный).
        Основывается на количестве вопросов с ответами в сессии.
        """
        answered_count = QuestionInstance.objects.filter(
            session=session
        ).annotate(has_answer=Count("answer")).filter(has_answer__gt=0).count()
        return answered_count + 1

    def has_existing_answer(self, question_instance: QuestionInstance) -> bool:
        """
        Проверяет, был ли уже дан ответ на этот вопрос.
        """
        return hasattr(question_instance, "answer") and question_instance.answer is not None
