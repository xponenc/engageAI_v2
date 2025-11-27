"""
Маршруты Assessment API.
Точка входа для Telegram-бота и Web UI.
"""

from fastapi import APIRouter, Depends, Request
from utils.setup_logger import setup_logger

from .schemas import (
    StartRequest, StartResponse,
    AnswerRequest, AnswerResponse,
    NextQuestionResponse,
    FinalReportResponse
)
from .dependencies import verify_internal_or_web



logger = setup_logger(
    __name__,
    log_dir="logs/backend",
    log_file="assessment.log",
    logger_level=10,
    file_level=10,
    console_level=20
)

router = APIRouter(prefix="/assessment", tags=["assessment"])


# -----------------------------------------
# /start
# -----------------------------------------

@router.post("/start", response_model=StartResponse)
async def start(payload: StartRequest, request: Request,
                _auth=Depends(verify_internal_or_web)):
    """
    Создаёт новую или возобновляет существующую сессию.
    """
    session, question = await start_test_session(payload)
    return StartResponse(session_id=str(session.id), question=question)


# -----------------------------------------
# /answer
# -----------------------------------------

@router.post("/answer", response_model=AnswerResponse)
async def answer(payload: AnswerRequest, request: Request,
                 _auth=Depends(verify_internal_or_web)):
    """
    Принимает ответ пользователя и возвращает следующий вопрос.
    """
    resp = await submit_answer(payload)
    return resp


# -----------------------------------------
# /next
# -----------------------------------------

@router.get("/next", response_model=NextQuestionResponse)
async def next_question(session_id: str, request: Request,
                        _auth=Depends(verify_internal_or_web)):
    """
    Отдаёт следующий неотвеченный вопрос.
    """
    q = await get_next_question(session_id)
    return NextQuestionResponse(session_id=session_id, question=q)


# -----------------------------------------
# /final-report
# -----------------------------------------

@router.get("/final-report", response_model=FinalReportResponse)
async def final_report(session_id: str, request: Request,
                       _auth=Depends(verify_internal_or_web)):
    """
    Генерирует финальный отчёт с использованием LLM.
    """
    report = await generate_final_recommendations(session_id)
    return FinalReportResponse(report=report)
