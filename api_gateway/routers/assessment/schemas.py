"""
Схемы данных для Assessment API.
Используются для валидации входящих и исходящих запросов.
"""

from pydantic import BaseModel
from typing import Optional, List


# -------------------------------
# Основные структуры
# -------------------------------

class Question(BaseModel):
    """
    Структура вопроса, который отдаётся фронту или боту.
    """
    id: str
    level: str
    type: str
    question_text: str
    options: Optional[List[str]] = None


# -------------------------------
# /assessment/start
# -------------------------------

class StartRequest(BaseModel):
    """
    Запрос на запуск тестовой сессии.
    """
    telegram_id: Optional[int] = None
    user_id: Optional[int] = None


class StartResponse(BaseModel):
    session_id: str
    question: Question


# -------------------------------
# /assessment/answer
# -------------------------------

class AnswerRequest(BaseModel):
    session_id: str
    answer: str
    question_instance_id: Optional[str] = None
    telegram_id: Optional[int] = None
    user_id: Optional[int] = None


class AnswerResponse(BaseModel):
    finish: bool
    level: Optional[str] = None
    question: Optional[Question] = None


# -------------------------------
# /assessment/next
# -------------------------------

class NextQuestionResponse(BaseModel):
    session_id: str
    question: Optional[Question]


# -------------------------------
# /assessment/final-report
# -------------------------------

class FinalReport(BaseModel):
    summary: str
    estimated_level: str
    weaknesses: List[str]
    recommendations: List[str]
    study_plan: List[str]


class FinalReportResponse(BaseModel):
    report: FinalReport
