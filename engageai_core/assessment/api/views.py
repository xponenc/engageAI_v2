from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.conf import settings

from engageai_core.mixins import InternalBotAuthMixin, core_api_logger, TelegramUserMixin
from ..mixins import AssessmentTestSessionMixin, QuestionInstanceMixin
from ..models import TestSession, QuestionInstance, SessionSourceType
from ..services.assessment_service import start_assessment_for_user, \
    get_next_question_for_session, submit_answer, finish_assessment
from ..services.test_flow import MAIN_QUESTIONS_LIMIT


class StartAssessmentAPI(
    InternalBotAuthMixin,
    TelegramUserMixin,
    APIView
):
    """Запуск теста через API с проверкой ключа"""

    def post(self, request):
        bot = getattr(request, "internal_bot", None)
        bot_tag = f"[bot:{bot}]"

        user = self.get_telegram_user(request)
        if isinstance(user, Response):
            return user  # ошибка уже возвращена

        core_api_logger.info(f"{bot_tag} Start TestSession for user={user.id}")

        session, expired_flag = start_assessment_for_user(
            user,
            source=SessionSourceType.TELEGRAM
        )

        if expired_flag:
            core_api_logger.info(
                f"{bot_tag} Previous session expired → new created | user={user.id}"
            )

        # --- Получаем первый вопрос ---
        question, status_ = get_next_question_for_session(
            session=session,
            source_question_request=SessionSourceType.TELEGRAM
        )

        if not question:
            core_api_logger.error(f"{bot_tag} Failed to generate first question | session={session.id}")
            return Response(
                {"success": False, "detail": "Failed to generate question"},
                status=500
            )

        question_number = QuestionInstance.objects.filter(session=session).exclude(answer__isnull=True).count() + 1

        return Response(
            {
                "success": True,
                "expired_previous": expired_flag,
                "session_id": session.id,

                "question": {
                    "id": question.id,
                    "text": question.question_json["question_text"],
                    "type": question.question_json["type"],
                    "options": question.question_json.get("options"),
                    "number": question_number,
                    "total_questions": MAIN_QUESTIONS_LIMIT,
                }
            },
            status=201
        )

#
# class QuestionAPI(
#     InternalBotAuthMixin,
#     TelegramUserMixin,
#     AssessmentTestSessionMixin,
#     APIView
# ):
#     """Получение следующего вопроса"""
#
#     def post(self, request, session_id):
#         bot = getattr(request, "internal_bot", None)
#         bot_tag = f"[bot:{bot}]"
#
#         user = self.get_telegram_user(request)
#         if isinstance(user, Response):
#             return user
#
#         session = self.get_user_session(session_id, user, bot_tag)
#         if isinstance(session, Response):
#             return session
#
#         core_api_logger.info(f"{bot_tag} Get next question | session={session_id}")
#
#         question, status_ = get_next_question_for_session(session)
#
#         if status_ == "expired":
#             core_api_logger.info(
#                 f"{bot_tag} Session expired during GET | session={session_id}"
#             )
#             return Response(
#                 {"success": False, "detail": "Session expired"},
#                 status=400
#             )
#
#         if not question:
#             return Response(
#                 {"success": True, "no_more_questions": True},
#                 status=200
#             )
#
#         question_number = QuestionInstance.objects.filter(session=session).exclude(answer__isnull=True).count() + 1
#
#         return Response(
#             {
#                 "success": True,
#                 "question": {
#                     "id": question.id,
#                     "text": question.question_json["question_text"],
#                     "type": question.question_json["type"],
#                     "options": question.question_json.get("options"),
#                     "number": question_number,
#                     "total_questions": MAIN_QUESTIONS_LIMIT,
#                 }
#             }
#         )


class AnswerAPI(
    InternalBotAuthMixin,
    TelegramUserMixin,
    AssessmentTestSessionMixin,
    QuestionInstanceMixin,
    APIView
):
    def post(self, request, session_id, question_id):
        bot = getattr(request, "internal_bot", None)
        bot_tag = f"[bot:{bot}]"

        telegram_id = request.data.get("telegram_id")
        answer_text = request.data.get("answer_text")
        if not answer_text:
            return Response({"detail": "answer_text missing"}, status=400)

        user = self.get_telegram_user(request)
        if isinstance(user, Response):
            return user

        session = self.get_user_session(session_id, user, bot_tag)
        if isinstance(session, Response):
            return session

        qinst = self.get_question_instance(question_id, session, bot_tag)
        if isinstance(qinst, Response):
            return qinst

        if not hasattr(qinst, "answer"):  # вопрос уже имеет ответ - из другого источника тестирования web/tg
            submit_answer(session, qinst, answer_text)

            core_api_logger.info(
                f"{bot_tag} Answer received | {session} qinst={qinst} text='{answer_text}'"
            )

        # получаем следующий вопрос
        next_q, status_ = get_next_question_for_session(
            session=session,
            source_question_request=SessionSourceType.TELEGRAM
        )

        if status_ == "expired":
            return Response(
                {"success": False, "detail": "Session expired"},
                status=400
            )

        if not next_q:
            # конец теста
            protocol = finish_assessment(session)
            level = protocol.get("estimated_level")

            view_url = (
                # f"{settings.SITE_URL}/assessment/result/{session.id}/"
                f"http://127.0.0.1:8000/assessment/result/{session.id}/"
            )

            core_api_logger.info(
                f"{bot_tag} Test finished | session={session_id} user={user.id}"
            )

            return Response(
                {
                    "finished": True,
                    "level": level,
                    "session_id": str(session.id),
                    "view_url": view_url
                }
            )

        question_number = QuestionInstance.objects.filter(session=session).exclude(answer__isnull=True).count() + 1

        return Response(
            {
                "success": True,
                "next_question": {
                    "id": next_q.id,
                    "text": next_q.question_json["question_text"],
                    "type": next_q.question_json["type"],
                    "options": next_q.question_json.get("options"),
                    "number": question_number,
                    "total_questions": MAIN_QUESTIONS_LIMIT,
                }
            }
        )

#
# class FinishAssessmentAPI(
#     InternalBotAuthMixin,
#     TelegramUserMixin,
#     AssessmentTestSessionMixin,
#     APIView
# ):
#
#     def post(self, request, session_id):
#         bot = getattr(request, "internal_bot", None)
#         bot_tag = f"[bot:{bot}]"
#
#         user = self.get_telegram_user(request)
#         if isinstance(user, Response):
#             return user
#
#         session = self.get_user_session(session_id, user, bot_tag)
#         if isinstance(session, Response):
#             return session
#
#         protocol = finish_assessment(session)
#
#         core_api_logger.info(f"{bot_tag} Manual finish | session={session_id}")
#
#         return Response(
#             {
#                 "success": True,
#                 "finished": True,
#                 "protocol": protocol
#             }
#         )
