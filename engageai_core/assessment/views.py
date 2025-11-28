# from django.contrib.auth.mixins import LoginRequiredMixin
# from django.views import View
# from django.shortcuts import render, redirect, get_object_or_404
# from django.urls import reverse
# from django.utils import timezone
#
# from .forms import QuestionAnswerForm
# from .models import TestSession, QuestionInstance, TestAnswer, SessionSourceType
# from . import services
# from .services.process_llm import evaluate_open_answer, generate_final_recommendations
# from .services.test_flow import create_diagnostic_questions, get_next_unanswered_question, \
#     determine_range_from_diagnostic, load_questions_for_range, can_generate_next_main_packet, finalize_session, \
#     MAIN_QUESTIONS_LIMIT
#
#
# class StartAssessmentView(LoginRequiredMixin, View):
#     """Запуск базового теста на определение уровня языка"""
#
#     def get(self, request):
#         user = request.user
#         session = TestSession.objects.filter(
#             user=user, finished_at__isnull=True
#         ).first()
#         if not session:
#             session = TestSession.objects.create(user=user, locked_by=SessionSourceType.WEB)
#             create_diagnostic_questions(session)
#         return redirect("assessment:question_view", session_id=session.id)
#
#
# class QuestionView(LoginRequiredMixin, View):
#     """Выдача вопроса и обработка ответа на него"""
#     def get(self, request, session_id):
#         session = get_object_or_404(TestSession, id=session_id, user_id=request.user.id)
#
#         # Если Тестовая сессия истекла по времени — пометить и редирект на старт
#         if session.is_active:
#             expires_at = session.started_at + timezone.timedelta(minutes=session.time_limit_minutes)
#             if timezone.now() > expires_at:
#                 session.mark_expired()
#                 return redirect(reverse("assessment:start_test"))
#
#         next_question = get_next_unanswered_question(session)
#
#         if next_question:
#             form = QuestionAnswerForm(
#                 initial={
#                     "session_id": session.id,
#                     "question_instance_id": next_question.id,
#                 }
#             )
#             session_source_changed = ""
#             if session.locked_by != SessionSourceType.WEB:
#                 session_source_changed = session.get_locked_by_display()
#
#             question_number = QuestionInstance.objects.filter(session=session).exclude(answers__isnull=True).count() + 1
#             # Обрабатываем текст вопроса
#             question_text = next_question.question_json.get("question_text")
#             text_content = ""
#             question_content = question_text
#
#             # Разбиваем на текст и вопрос
#             if "Text:" in question_text and "Question:" in question_text:
#                 try:
#                     text_part = question_text.split("Text:")[1]
#                     text_content = text_part.split("Question:")[0].strip()
#                     question_content = text_part.split("Question:")[1].strip()
#                 except IndexError:
#                     # Если разбиение не удалось, используем оригинальный текст
#                     pass
#             return render(
#                 request,
#                 "assessment/question.html",
#                 {
#                     "total_questions": MAIN_QUESTIONS_LIMIT,
#                     "question": next_question.question_json,
#                     "question_number": question_number,
#                     "session": session,
#                     "session_source_changed": session_source_changed,
#                     "question_inst": next_question,
#                     "text_content": text_content,
#                     "question_content": question_content,
#                     "form": form,
#                 },
#             )
#
#         if can_generate_next_main_packet(session):
#             low, high = determine_range_from_diagnostic(session)
#             load_questions_for_range(session, low, high)
#             return redirect("assessment:question_view", session_id=session.id)
#
#         return redirect(reverse("assessment:finish_view", args=[str(session.id)]))
#
#     def post(self, request, session_id):
#         form = QuestionAnswerForm(request.POST)
#
#         if not form.is_valid():
#             # Безопасный отказ — запрещенный ответ
#             return render(
#                 request,
#                 "assessment/error.html",
#                 {"message": "Некорректная форма или попытка подделки данных."}
#             )
#
#         session = get_object_or_404(TestSession, id=session_id, user_id=request.user.id)
#
#         if session.locked_by != SessionSourceType.WEB:
#             session.locked_by = SessionSourceType.WEB
#             session.save()
#         # Примем данные из формы
#         qinst = form.cleaned_data["qinst"]
#         answer_text = form.cleaned_data["answer_text"].strip()
#
#         # Снова проверяем принадлежность для надёжности (двойная защита)
#         if qinst.session_id != session.id:
#             return render(
#                 request,
#                 "assessment/error.html",
#                 {"message": "Попытка подделки данных. Ответ не принят."}
#             )
#
#         ans = TestAnswer.objects.create(question=qinst, answer_text=answer_text, answered_at=timezone.now())
#
#         qj = qinst.question_json
#         qtype = qj.get("type")
#         if qtype == "mcq":
#             options = qj.get("options") or []
#             try:
#                 user_index = options.index(answer_text)
#             except ValueError:
#                 user_index = None
#             correct = qj.get("correct_answer", {}).get("index")
#             if user_index is not None and correct is not None:
#                 ans.score = 1.0 if user_index == correct else 0.0
#         else:
#             # open-question: требуется оценка LLM
#             # TODO запаковать в Celery
#             eval_result = evaluate_open_answer(answer_text, qj)
#             ans.score = eval_result.get("score")
#             ans.ai_feedback = eval_result.get("feedback")
#
#         ans.save()
#
#         return redirect(reverse("assessment:question_view", args=[str(session.id)]))
#
#
# class FinishView(LoginRequiredMixin, View):
#     """Завершение сессии тестирования на определения уровня знания языка"""
#     def get(self, request, session_id):
#         session = get_object_or_404(TestSession, id=session_id, user_id=request.user.id)
#         if not session.finished_at:
#             protocol = finalize_session(session)
#             llm_result = generate_final_recommendations(test_session_id=session.id)  # TODO запаковать в Celery
#             print(llm_result)
#             llm_estimated_level = llm_result.get("estimated_level")
#             if llm_estimated_level:
#                 print(f"{llm_estimated_level=}")
#                 protocol["estimated_level"] = llm_estimated_level
#
#             protocol["llm"] = llm_result
#             session.protocol_json = protocol
#             session.save(update_fields=["protocol_json"])
#         else:
#             protocol = session.protocol_json
#
#         return render(request, "assessment/finish.html", {"protocol": protocol, "session": session})


from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy

from users.models import StudyProfile
from utils.setup_logger import setup_logger
from .forms import QuestionAnswerForm
from .models import QuestionInstance, TestSession, SessionSourceType
from .services.assessment_service import start_assessment_for_user, get_next_question_for_session, submit_answer, \
    finish_assessment
from .services.test_flow import MAIN_QUESTIONS_LIMIT
from users.models import CEFRLevel

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

        question_text = next_question.question_json.get("question_text", "")
        text_content = ""
        question_content = question_text
        if "Text:" in question_text and "Question:" in question_text:
            try:
                text_part = question_text.split("Text:")[1]
                text_content = text_part.split("Question:")[0].strip()
                question_content = text_part.split("Question:")[1].strip()
            except IndexError:
                pass

        question_number = QuestionInstance.objects.filter(session=session).exclude(answer__isnull=True).count() + 1
        return render(request, "assessment/question.html", {
            "total_questions": MAIN_QUESTIONS_LIMIT,
            "question": next_question.question_json,
            "question_number": question_number,
            "session": session,
            "question_inst": next_question,
            "text_content": text_content,
            "question_content": question_content,
            "form": form
        })

    def post(self, request, session_id):
        form = QuestionAnswerForm(request.POST)
        if not form.is_valid():
            return render(request, "assessment/error.html", {"message": "Некорректная форма."})

        session = get_object_or_404(TestSession, id=session_id, user_id=request.user.id)
        qinst = form.cleaned_data["qinst"]
        if not hasattr(qinst, "answer"): # вопрос уже имеет ответ - из другого источника тестирования web/tg
            answer_text = form.cleaned_data["answer_text"]
            submit_answer(session, qinst, answer_text)

        return redirect(reverse("assessment:question_view", args=[str(session.id)]))


class FinishView(LoginRequiredMixin, View):
    """Завершение теста"""

    def get(self, request, session_id):
        test_session_qs = TestSession.objects.prefetch_related("questions__answer")
        session = get_object_or_404(test_session_qs, id=session_id, user_id=request.user.id)
        protocol = finish_assessment(session)


        return render(request, "assessment/finish.html", {"protocol": protocol, "session": session})
