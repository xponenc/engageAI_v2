from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.conf import settings

from engageai_core.mixins import BotAuthenticationMixin, TelegramUserResolverMixin

from utils.setup_logger import setup_logger
from ..mixins import AssessmentTestSessionMixin, QuestionInstanceMixin
from ..models import SessionSourceType
from ..services.assessment_service import start_assessment_for_user, \
    get_next_question_for_session, submit_answer, finish_assessment
from ..services.presentation_service import AssessmentProgressService
from ..services.telegram_service import TelegramAssessmentService
from ..services.test_flow import MAIN_QUESTIONS_LIMIT


core_api_logger = setup_logger(name=__file__, log_dir="logs/core_api", log_file="core_api.log")

#
# class StartAssessmentAPI(BotAuthenticationMixin, TelegramUserResolverMixin, APIView):
#     """Запуск теста через API с проверкой ключа"""
#
#     def post(self, request):
#         bot = getattr(request, "internal_bot", None)
#         bot_tag = f"[bot:{bot}]"
#
#         user_resolve_result = self.resolve_telegram_user(request)
#         if isinstance(user_resolve_result, dict):
#             result = user_resolve_result
#             return Response(result["payload"], status=result["response_status"])
#         user = user_resolve_result
#
#         incoming_message_id = str(request.data.get("telegram_message_id")) if request.data.get(
#             "telegram_message_id") else None
#
#         core_api_logger.info(f"{bot_tag} Start TestSession for user={user.id}")
#
#         session, expired_flag = start_assessment_for_user(
#             user,
#             source=SessionSourceType.TELEGRAM
#         )
#
#         if expired_flag:
#             core_api_logger.info(
#                 f"{bot_tag} Previous session expired → new created | user={user.id}"
#             )
#
#         # Получаем первый вопрос
#         question, status_ = get_next_question_for_session(
#             session=session,
#             source_question_request=SessionSourceType.TELEGRAM
#         )
#
#         if not question:
#             core_api_logger.error(f"{bot_tag} Failed to generate first question | session={session.id}")
#             return Response(
#                 {"success": False, "detail": "Failed to generate question"},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )
#         # TODO нужно получать от бота assistant_slug
#         assistant_slug = "main_orchestrator"
#         try:
#             assistant = AIAssistant.objects.get(slug=assistant_slug, is_active=True)
#         except AIAssistant.DoesNotExist:
#             return Response(
#                 {"success": False, "detail": f"Failed to find AIAssistant with slug={assistant_slug}"},
#                 status=500
#             )
#
#         chat, created = Chat.get_or_create_ai_chat(
#             user=user,
#             ai_assistant=assistant,
#             platform=ChatPlatform.TELEGRAM,
#         )
#
#         reply_to_msg = None
#
#         if incoming_message_id:
#             reply_to_msg = Message.objects.filter(
#                 source_type=MessageSource.TELEGRAM,
#                 metadata__telegram__message_id=incoming_message_id,
#                 chat=chat
#             ).first()
#         ai_message = Message.objects.create(
#             chat=chat,
#             content=question.question_json["question_text"],
#             is_ai=True,
#             source_type=MessageSource.TELEGRAM,
#             sender=None,
#             reply_to=reply_to_msg,
#             external_id=None,
#         )
#
#         question_number = QuestionInstance.objects.filter(session=session).exclude(answer__isnull=True).count() + 1
#
#         return Response(
#             {
#                 "expired_previous": expired_flag,
#                 "session_id": session.id,
#                 "question": {
#                     "id": question.id,
#                     "text": question.question_json["question_text"],
#                     "type": question.question_json["type"],
#                     "options": question.question_json.get("options"),
#                     "number": question_number,
#                     "total_questions": MAIN_QUESTIONS_LIMIT,
#                 },
#                 "core_message_id": ai_message.id
#             },
#             status=201
#         )


class StartAssessmentTestAPIView(BotAuthenticationMixin, TelegramUserResolverMixin, APIView):
    """Запуск TestSession"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.telegram_service = TelegramAssessmentService()
        self.progress_service = AssessmentProgressService()

    def post(self, request):
        bot = getattr(request, "internal_bot", None)
        bot_tag = f"[bot:{bot}]"

        # Разрешение пользователя
        user_resolve_result = self.resolve_telegram_user(request)
        if isinstance(user_resolve_result, Response):
            response = user_resolve_result
            return response

        user = user_resolve_result

        incoming_message_id = str(request.data.get("telegram_message_id")) if request.data.get(
            "telegram_message_id") else None
        core_api_logger.info(f"{bot_tag} Start TestSession for user={user.id}")

        session, expired_flag = start_assessment_for_user(
            user,
            source=SessionSourceType.TELEGRAM
        )

        if expired_flag:
            core_api_logger.info(f"{bot_tag} Previous session expired → new created | user={user.id}")

        # Получаем первый вопрос
        question, status_ = get_next_question_for_session(
            session=session,
            source_question_request=SessionSourceType.TELEGRAM
        )
        if not question:
            core_api_logger.error(f"{bot_tag} Failed to generate first question | session={session.id}")
            return Response(
                {"success": False, "detail": "Failed to generate question"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Создаем сообщение в чате
        ai_message = self.telegram_service.create_question_message(
            user=user,
            session=session,
            question=question,
            incoming_message_id=incoming_message_id,
            bot=bot
        )

        if isinstance(ai_message, Response):
            return ai_message

        question_number = self.progress_service.get_question_number(session)

        task = question.task
        print(task.content)
        text = task.content.get("prompt")
        options = task.content.get("options")
        q_response_format = task.response_format
        return Response(
            {
                "expired_previous": expired_flag,
                "session_id": session.id,
                "question": {
                    "id": question.id,
                    "text": text,
                    "type": q_response_format,
                    "options": options,
                    "number": question_number,
                    "total_questions": MAIN_QUESTIONS_LIMIT,
                },
                "core_answer": {
                    "core_message_id": ai_message.id,
                    "reply_to_message_id": incoming_message_id,
                },
            },
            status=201
        )


class AnswerAPIView(
    BotAuthenticationMixin, TelegramUserResolverMixin, AssessmentTestSessionMixin,
    QuestionInstanceMixin, APIView
):
    """Обработка ответа на вопрос и выдача следующего вопроса"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.telegram_service = TelegramAssessmentService()
        self.progress_service = AssessmentProgressService()

    def post(self, request, session_id, question_id):
        bot = getattr(request, "internal_bot", None)
        bot_tag = f"[bot:{bot}]"
        answer_text = request.data.get("answer_text")

        if not answer_text:
            return Response({"detail": "answer_text missing"}, status=400)

        # Разрешение пользователя
        user_resolve_result = self.resolve_telegram_user(request)
        if isinstance(user_resolve_result, Response):
            response = user_resolve_result
            return response

        user = user_resolve_result

        session = self.get_user_session(session_id, user, bot_tag)
        if isinstance(session, Response):
            return session

        qinst = self.get_question_instance(question_id, session, bot_tag)
        if isinstance(qinst, Response):
            return qinst

        incoming_message_id = str(request.data.get("telegram_message_id")) if request.data.get(
            "telegram_message_id") else None

        # Сохраняем ответ, если он еще не был дан
        if not self.progress_service.has_existing_answer(qinst):
            submit_answer(
                user=user,
                session=session,
                qinst=qinst,
                answer_text=answer_text)
            core_api_logger.info(
                f"{bot_tag} Answer received | {session} qinst={qinst} text='{answer_text}'"
            )

        # Получаем следующий вопрос
        question, expired_flag = get_next_question_for_session(
            session=session,
            source_question_request=SessionSourceType.TELEGRAM
        )

        if expired_flag == "expired":  # TODO тут не совсем правильный ответ
            return Response(
                data={"success": False, "detail": "Session expired"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Если следующего вопроса нет, завершаем тест
        if not question:
            protocol = finish_assessment(session)
            level = protocol.get("estimated_level")
            view_url = f"{settings.SITE_URL}/assessment/result/{session.id}/"

            core_api_logger.info(f"{bot_tag} Test finished | session={session_id} user={user.id}")

            ai_message = self.telegram_service.create_finish_message(
                user=user,
                session=session,
                level=level,
                view_url=view_url,
                incoming_message_id=incoming_message_id,
                bot=bot
            )

            if isinstance(ai_message, Response):
                return ai_message

            return Response(
                {
                    "finished": True,
                    "session_id": str(session.id),
                    "level": level,
                    "view_url": view_url,
                    "core_answer": {
                        "core_message_id": ai_message.id,
                        "reply_to_message_id": incoming_message_id,
                    }
                }
            )

        # Создаем сообщение для следующего вопроса
        ai_message = self.telegram_service.create_question_message(
            user=user,
            session=session,
            question=question,
            incoming_message_id=incoming_message_id,
            bot=bot
        )

        if isinstance(ai_message, Response):
            return ai_message

        question_number = self.progress_service.get_question_number(session)

        task = question.task
        print(task.content)
        text = task.content.get("prompt")
        options = task.content.get("options")
        q_response_format = task.response_format
        return Response(
            {
                "expired_previous": expired_flag,
                "session_id": session.id,
                "question": {
                    "id": question.id,
                    "text": text,
                    "type": q_response_format,
                    "options": options,
                    "number": question_number,
                    "total_questions": MAIN_QUESTIONS_LIMIT,
                },
                "core_answer": {
                    "core_message_id": ai_message.id,
                    "reply_to_message_id": incoming_message_id,
                },
            },
            status=status.HTTP_200_OK
        )
