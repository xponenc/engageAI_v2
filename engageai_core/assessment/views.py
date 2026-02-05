import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.utils import timezone
from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy

from utils.setup_logger import setup_logger
from .forms import QuestionAnswerForm
from .models import TestSession, SessionSourceType, QuestionInstance, TestAnswer, TestAnswerMedia
from .services.assessment_service import start_assessment_for_user, get_next_question_for_session, submit_answer, \
    finish_assessment
from .services.presentation_service import AssessmentProgressService
from .services.test_flow import MAIN_QUESTIONS_LIMIT
from .tasks import evaluate_answer_to_test_task

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
        }, task=next_question.task
        )

        question_number = self.progress_service.get_question_number(session)

        context = {
            "total_questions": MAIN_QUESTIONS_LIMIT,
            "question": next_question.task,
            "question_number": question_number,
            "task": next_question.task,
            "session": session,
            "question_inst": next_question,
            "form": form
        }

        return render(request, "assessment/question.html", context)

    def post(self, request, session_id):
        qinst_id = request.POST.get("question_instance_id")

        qinst = get_object_or_404(
            QuestionInstance.objects.select_related("task", "session"),
            id=qinst_id,
            session_id=session_id,
        )

        form = QuestionAnswerForm(
            data=request.POST,
            files=request.FILES,
            task=qinst.task,
        )
        if not form.is_valid():
            question_number = self.progress_service.get_question_number(qinst.session)

            context = {
                "total_questions": MAIN_QUESTIONS_LIMIT,
                "question": qinst.task,
                "question_number": question_number,
                "task": qinst.task,
                "session": qinst.session,
                "question_inst": qinst,
                "form": form
            }
            return render(request, "assessment/question.html", context)

        session = get_object_or_404(TestSession, id=session_id, user_id=request.user.id)

        # Проверяем, не был ли уже дан ответ на этот вопрос
        if not self.progress_service.has_existing_answer(qinst):
            task = qinst.task
            if task.response_format == "audio":
                audio_file = form.cleaned_data["answer"]  # UploadedFile
                test_answer = TestAnswer.objects.create(
                    question=qinst,
                    audio_file=audio_file,
                )

                # TODO: постановка задачи на транскрибацию
                # enqueue_audio_transcription(answer.id)

            else:
                if task.response_format == 'multiple_choice':
                    answer = json.dumps(form.cleaned_data["answer"])
                else:
                    answer = form.cleaned_data["answer"].strip()
                test_answer = TestAnswer.objects.create(
                    question=qinst,
                    response_text=answer,
                    answered_at=timezone.now()
                )

                result = evaluate_answer_to_test_task.delay(
                    test_answer_id=test_answer.pk,
                    user_id=request.user.id,
                    test_session_id=session.id
                )

        return redirect(
            reverse("assessment:question_view", args=[str(session_id)])
        )


class FinishView(LoginRequiredMixin, View):
    """Завершение теста"""

    def get(self, request, session_id):
        test_session_qs = TestSession.objects.prefetch_related("questions__answer")
        session = get_object_or_404(test_session_qs, id=session_id, user_id=request.user.id)
        protocol = finish_assessment(session)

        return render(request, "assessment/finish.html", {"protocol": protocol, "session": session})
