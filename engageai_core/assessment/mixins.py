from rest_framework.response import Response

from assessment.models import TestSession, QuestionInstance
from engageai_core.mixins import core_api_logger


class AssessmentTestSessionMixin:
    """Проверяет, что TestSession принадлежит user."""

    def get_user_session(self, session_id, user, bot_tag):
        try:
            session = TestSession.objects.get(id=session_id, user=user)
            return session

        except TestSession.DoesNotExist:
            core_api_logger.error(
                f"{bot_tag} Session not found or does not belong to user | session_id={session_id}, user_id={user.id}"
            )
            return Response(
                {"success": False, "detail": "Session not found"},
                status=404
            )


class QuestionInstanceMixin:
    def get_question_instance(self, qinst_id, session, bot_tag):
        try:
            return QuestionInstance.objects.get(id=qinst_id, session=session)

        except QuestionInstance.DoesNotExist:
            core_api_logger.error(
                f"{bot_tag} QuestionInstance not found | qinst_id={qinst_id}, session={session.id}"
            )
            return Response(
                {"success": False, "detail": "Invalid question instance"},
                status=404
            )
