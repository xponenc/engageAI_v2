from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy

from utils.setup_logger import setup_logger
from .forms import QuestionAnswerForm
from .models import QuestionInstance, TestSession, SessionSourceType
from .services.assessment_service import start_assessment_for_user, get_next_question_for_session, submit_answer, \
    finish_assessment
from .services.test_flow import MAIN_QUESTIONS_LIMIT

assessment_logger = setup_logger(name=__file__, log_dir="logs/core/assessment", log_file="assessment.log")


class StartAssessmentView(LoginRequiredMixin, View):
    """Запуск базового теста на определение уровня языка"""

    def get(self, request):
        return render(request, template_name="assessment/start.html", context={})

    def post(self, request):
        session, expired_flag = start_assessment_for_user(request.user)
        redirect_url = reverse_lazy(
            "assessment:question_view",
            kwargs={"session_id": session.id}
        )
        if expired_flag:
            redirect_url += "?expired_flag=True"
        return redirect(redirect_url)


class QuestionView(LoginRequiredMixin, View):
    """Выдача вопроса и обработка ответа на него"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.presentation_service = QuestionPresentationService()
        self.progress_service = AssessmentProgressService()

    def get(self, request, session_id):
        session = get_object_or_404(TestSession, id=session_id, user_id=request.user.id)
        next_question, status = get_next_question_for_session(
            session=session,
            source_question_request=SessionSourceType.WEB
        )
        if status == "expired":
            return redirect(reverse("assessment:start_test"))
        if not next_question:
            return redirect(reverse("assessment:finish_view", args=[str(session.id)]))

        form = QuestionAnswerForm(initial={
            "session_id": session.id,
            "question_instance_id": next_question.id
        })

        formatted_question = self.presentation_service.format_for_web(next_question)
        question_number = self.progress_service.get_question_number(session)

        context = {
            "total_questions": MAIN_QUESTIONS_LIMIT,
            "question": next_question.question_json,
            "question_number": question_number,
            "session": session,
            "question_inst": next_question,
            "text_content": formatted_question["text_content"],
            "question_content": formatted_question["question_content"],
            "form": form
        }

        return render(request, "assessment/question.html", context)

    def post(self, request, session_id):
        form = QuestionAnswerForm(request.POST)
        if not form.is_valid():
            return render(request, "assessment/error.html", {"message": "Некорректная форма."})

        session = get_object_or_404(TestSession, id=session_id, user_id=request.user.id)
        qinst = form.cleaned_data["qinst"]

        # Проверяем, не был ли уже дан ответ на этот вопрос
        if not self.progress_service.has_existing_answer(qinst):
            answer_text = form.cleaned_data["answer_text"]
            submit_answer(session, qinst, answer_text)

        return redirect(reverse("assessment:question_view", args=[str(session.id)]))

#
# class QuestionView(LoginRequiredMixin, View):
#     """Выдача вопроса и обработка ответа на него"""
#
#     def get(self, request, session_id):
#         session = get_object_or_404(TestSession, id=session_id, user_id=request.user.id)
#         next_question, status = get_next_question_for_session(
#             session=session,
#             source_question_request=SessionSourceType.WEB
#         )
#
#         if status == "expired":
#             return redirect(reverse("assessment:start_test"))
#         if not next_question:
#             return redirect(reverse("assessment:finish_view", args=[str(session.id)]))
#
#         form = QuestionAnswerForm(initial={
#             "session_id": session.id,
#             "question_instance_id": next_question.id
#         })
#
#         question_text = next_question.question_json.get("question_text", "")
#         text_content = ""
#         question_content = question_text
#         if "Text:" in question_text and "Question:" in question_text:
#             try:
#                 text_part = question_text.split("Text:")[1]
#                 text_content = text_part.split("Question:")[0].strip()
#                 question_content = text_part.split("Question:")[1].strip()
#             except IndexError:
#                 pass
#
#         question_number = QuestionInstance.objects.filter(session=session).exclude(answer__isnull=True).count() + 1
#         return render(request, "assessment/question.html", {
#             "total_questions": MAIN_QUESTIONS_LIMIT,
#             "question": next_question.question_json,
#             "question_number": question_number,
#             "session": session,
#             "question_inst": next_question,
#             "text_content": text_content,
#             "question_content": question_content,
#             "form": form
#         })
#
#     def post(self, request, session_id):
#         form = QuestionAnswerForm(request.POST)
#         if not form.is_valid():
#             return render(request, "assessment/error.html", {"message": "Некорректная форма."})
#
#         session = get_object_or_404(TestSession, id=session_id, user_id=request.user.id)
#         qinst = form.cleaned_data["qinst"]
#         if not hasattr(qinst, "answer"):  # вопрос уже имеет ответ - из другого источника тестирования web/tg
#             answer_text = form.cleaned_data["answer_text"]
#             submit_answer(session, qinst, answer_text)
#
#         return redirect(reverse("assessment:question_view", args=[str(session.id)]))


class FinishView(LoginRequiredMixin, View):
    """Завершение теста"""

    def get(self, request, session_id):
        test_session_qs = TestSession.objects.prefetch_related("questions__answer")
        session = get_object_or_404(test_session_qs, id=session_id, user_id=request.user.id)
        protocol = finish_assessment(session)

        return render(request, "assessment/finish.html", {"protocol": protocol, "session": session})
