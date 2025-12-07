"""
Сервисный слой для теста на определение уровня языка.
Содержит функции для запуска сессии, выдачи вопросов, обработки ответов и финализации.
Может использоваться как веб-вью, так и DRF или ботами.
"""

from django.utils import timezone

from users.models import StudyProfile, CEFRLevel
from utils.setup_logger import setup_logger
from ..models import TestSession, QuestionInstance, TestAnswer, SessionSourceType
from .test_flow import (
    create_diagnostic_questions,
    get_next_unanswered_question,
    determine_range_from_diagnostic,
    load_questions_for_range,
    can_generate_next_main_packet,
    finalize_session,
)
from .process_llm import evaluate_open_answer, generate_final_recommendations, task_evaluate_open_answer, \
    task_generate_final_report

assessment_logger = setup_logger(name=__file__, log_dir="logs/core/assessment", log_file="assessment.log")


def start_assessment_for_user(user, source=SessionSourceType.WEB):
    """
    Создает новую сессию, если старая истекла.
    Возвращает (session, expired_flag)
    """
    assessment_logger.debug(f"[assessment] Старт теста для user={user.id}")

    expired_flag = False

    session = TestSession.objects.filter(user=user, finished_at__isnull=True).first()

    if session and session.is_active:
        expires_at = session.started_at + timezone.timedelta(minutes=session.time_limit_minutes)
        if timezone.now() > expires_at:
            assessment_logger.info(
                f"[assessment] TestSession {session.id} истекла по времени. "
                f"limit={session.time_limit_minutes}m user={user.id}"
            )
            session.mark_expired()
            expired_flag = True
            session = None

    if not session:
        session = TestSession.objects.create(user=user, locked_by=source)
        create_diagnostic_questions(session)
        assessment_logger.info(
            f"[assessment] Создана новая TestSession {session.id} для user={user.id}"
        )

    return session, expired_flag


def get_next_question_for_session(session: TestSession, source_question_request: SessionSourceType ):
    """Возвращает следующий вопрос и статус (None если нет)"""
    if session.is_active:
        expires_at = session.started_at + timezone.timedelta(minutes=session.time_limit_minutes)
        if timezone.now() > expires_at:

            assessment_logger.debug(f"TestSession {session.id} закрыта по истечению"
                                    f" заданного времени: {session.time_limit_minutes}")

            session.mark_expired()
            return None, "expired"

    next_question = get_next_unanswered_question(session)

    if session.locked_by != source_question_request:
        assessment_logger.debug(f"{session} locked_by={session.locked_by} запрос на вопрос пришел из другого "
                                f"источника {source_question_request}")
    if not next_question and can_generate_next_main_packet(session):
        low, high = determine_range_from_diagnostic(session)
        load_questions_for_range(session, low, high)
        next_question = get_next_unanswered_question(session)

    assessment_logger.debug(f"TestSession {session.id} выдан вопрос {next_question}")

    return next_question, None


def submit_answer(session, qinst, answer_text):
    """Сохраняет ответ пользователя и оценивает его (MCQ или open-вопрос)"""
    answer_text = answer_text.strip()
    ans = TestAnswer.objects.create(question=qinst, answer_text=answer_text, answered_at=timezone.now())

    qj = qinst.question_json
    qtype = qj.get("type")
    if qtype == "mcq":
        options = qj.get("options") or []
        try:
            user_index = options.index(answer_text)
        except ValueError:
            user_index = None
        correct = qj.get("correct_answer", {}).get("index")
        if user_index is not None and correct is not None:
            ans.score = 1.0 if user_index == correct else 0.0
    else:
        # open-вопрос: LLM оценивает ответ

        task_evaluate_open_answer.delay(str(ans.id))
        # eval_result = evaluate_open_answer(answer_text, qj)
        # assessment_logger.info(f"{session} LLM score for {ans}: {eval_result}")
        # ans.score = eval_result.get("score")
        # ans.ai_feedback = eval_result.get("feedback")

    ans.save()

    assessment_logger.info(f"{session} сохранен ответ {ans}")

    return ans


def finish_assessment(session):
    """Финализирует сессию и генерирует рекомендации через LLM"""
    if not session.finished_at:
        protocol = finalize_session(session)
        session.protocol_json = protocol
        session.finished_at = timezone.now()
        session.save(update_fields=["protocol_json", "finished_at"])

        estimated_level = protocol.get("estimated_level")

        if estimated_level in CEFRLevel.values:
            StudyProfile.objects.update_or_create(
                user=session.user,
                defaults={"english_level": estimated_level}
            )

        task_generate_final_report.delay(str(session.id))

    else:
        protocol = session.protocol_json
    return protocol
