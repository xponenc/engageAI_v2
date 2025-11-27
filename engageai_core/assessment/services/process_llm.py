import json
import os
import re
from typing import Optional, Dict, Any

from celery import shared_task
from django.utils import timezone
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from users.models import StudyProfile
from utils.setup_logger import setup_logger
from ..models import TestSession, QuestionInstance, TestAnswer
from users.models import CEFRLevel

load_dotenv()

assessment_logger = setup_logger(name=__file__, log_dir="logs/core/assessment", log_file="assessment.log")


def _llm():
    """
    Возвращает объект ChatOpenAI.
    Модель: gpt-4o-mini
    """
    return ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.2,
        api_key=os.getenv("OPENAI_API_KEY")
    )

def extract_json_from_llm_response(text: str) -> Optional[Dict[str, Any]]:
    """
    Пытается извлечь первый валидный JSON-объект (словарь) из текста.
    Возвращает dict или None.
    """
    if not isinstance(text, str):
        return None

    text = text.strip()
    if not text:
        return None

    # 1. Пробуем распарсить всё как есть
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Убираем возможные markdown-блоки
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)

    # 3. Ищем блоки {...} с поддержкой одного уровня вложенности
    pattern = re.compile(r'\{(?:[^{}]|\{[^{}]*\})*\}', re.DOTALL)
    candidates = [m.group(0) for m in pattern.finditer(text)]

    # 4. Fallback: от первого { до последнего }
    if not candidates:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and start < end:
            candidates = [text[start:end + 1]]

    # 5. Пробуем распарсить кандидатов
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            continue

    return None


def evaluate_open_answer(answer_text, question_json):
    """
    Оценка открытого вопроса.
    На основе LLM.
    """
    model = _llm()

    prompt = [
        ("system", "Ты преподаватель английского языка уровня C2."),
        ("user", f"""
Оцени ответ ученика на вопрос. 
Дай числовую оценку 0.0–1.0, 
и краткий фидбэк.

Вопрос:
{question_json.get("question_text")}

Ответ ученика:
{answer_text}

Формат ответа:
{{"score": float, "feedback": "text"}}
        """)
    ]

    response = model.invoke(prompt)
    # TODO подсчет токенов и цены, запись в ответ
    data = extract_json_from_llm_response(response.content)
    if data:
        return data

    return  {"score": 0.0, "feedback": "Не удалось распарсить ответ модели"}  # TODO 0 или Выставить какой то Alarm?


@shared_task(bind=True, max_retries=3)
def task_evaluate_open_answer(self, answer_id: str):
    """
    Celery-задача для оценки открытого ответа.
    Вызывает LLM → записывает результат в TestAnswer.
    """
    from assessment.models import TestAnswer  # локальный импорт

    try:
        answer = TestAnswer.objects.get(id=answer_id)
    except TestAnswer.DoesNotExist:
        assessment_logger.error(f"[LLM] answer {answer_id} not found")
        return

    qi = answer.question
    question_json = qi.question_json

    try:
        result = evaluate_open_answer(answer.answer_text, question_json)
    except Exception as exc:
        assessment_logger.exception(
            f"[LLM] error evaluating answer {answer_id}: {exc}"
        )
        raise self.retry(exc=exc, countdown=5)

    # Сохраняем ответ
    answer.score = float(result.get("score", 0.0))
    answer.ai_feedback = result.get("feedback")
    answer.save(update_fields=["score", "ai_feedback"])

    assessment_logger.info(
        f"[LLM] evaluated answer {answer_id} score={answer.score}"
    )

    return {"score": answer.score, "feedback": answer.ai_feedback}


def generate_final_recommendations(test_session_id: str) -> Dict[str, Any]:
    """
    Полная версия: собираем данные сессии, формируем строгий русскоязычный промпт,
    вызываем LLM через LangChain ChatOpenAI, парсим и сохраняем результат.
    Возвращаем словарь с распарсенным отчётом или fallback-структуру.
    """

    # 1) Получаем сессию
    try:
        session = TestSession.objects.get(id=test_session_id)
    except TestSession.DoesNotExist:
        return {"error": "session_not_found", "session_id": str(test_session_id)}

    # 2) Собираем компактный протокол (для prompt)
    compact = _compact_protocol_for_prompt(session)

    # 3) Формируем схему ответа (как текст) и пример структуры — вставляем в prompt
    schema_text = """
ОЖИДАЕМЫЙ ФОРМАТ JSON (строго!):
{
  "estimated_level": "A1|A2|B1|B2|C1|C2",
  "overall_score": 0.0,                     // число 0.0-1.0
  "score_summary": {                        // числа 0.0-1.0
     "grammar": 0.0,
     "vocabulary": 0.0,
     "listening": 0.0,
     "speaking": 0.0,
     "writing": 0.0
  },
  "strengths": ["...","..."],
  "weaknesses": ["...","..."],
  "recommendations": ["короткое действие 1","короткое действие 2"],
  "study_plan": ["День 1: ...","День 2: ...", "...", "День 7: ..."],  // ровно 7 строк
  "confidence": 0.0,                        // 0.0-1.0
  "notes": "optional text",
  "raw_model_output": "optional full text for debug"
}
"""

    # 4) Построение сообщений для LangChain
    system_msg = SystemMessage(content=(
        "Ты — экспертный преподаватель английского языка и экзаменатор. "
        "Твоя задача — проанализировать компактный протокол тестовой сессии и вернуть строго валидный JSON, "
        "строго соответствующий указанной структуре. Никаких дополнительных объяснений, только JSON, "
        "заполненный ответами на русском языке"
    ))

    user_parts = [
        "Ниже — краткая компактация пар «вопрос — ответ» (только необходимые поля):",
        json.dumps(compact, ensure_ascii=False, indent=2),
        "",
        "Дополнительно: используй следующие правила сопоставления overall_score -> CEFR:",
        "- overall_score >= 0.90 -> C2",
        "- 0.80 <= overall_score < 0.90 -> C1",
        "- 0.70 <= overall_score < 0.80 -> B2",
        "- 0.55 <= overall_score < 0.70 -> B1",
        "- 0.40 <= overall_score < 0.55 -> A2",
        "- overall_score < 0.40 -> A1",
        "",
        "ВНИМАНИЕ: Ответ должен быть только один JSON-объект, как в схеме ниже:",
        schema_text,
        "",
        "Если данных недостаточно для точного определения или они отсутствуют, то выставь оценки и уверенность строго"
        " исходя из предоставленных данных, и верни поле 'notes' с пояснением, но всё равно верни JSON."
        " Ставь оценку ноль  - если данных нет или не хватает для объективного анализа. ЭТО ВАЖНО"
    ]
    user_msg = HumanMessage(content="\n".join(user_parts))

    # 5) Вызов модели
    try:
        model = _llm()
    except Exception as ex:
        return {"error": "llm_init_failed", "exception": str(ex)}

    try:
        response = model.invoke([system_msg, user_msg])  # возвращает AIMessage или подобный объект
        print(f"{response=}")
        model_output = getattr(response, "content", None) or getattr(response, "text", None) or str(response)
        print(f"{model_output=}")
    except Exception as ex:
        return {"error": "llm_call_failed", "exception": str(ex)}

    # 6) Парсинг JSON (сначала пробуем json.loads по всей строке, затем _extract_json_from_text)
    parsed = extract_json_from_llm_response(response.content)
    print(f"{parsed=}")

    if parsed:
        return parsed
    return {
            "estimated_level": None,
            "overall_score": None,
            "score_summary": {},
            "strengths": [],
            "weaknesses": [],
            "recommendations": [],
            "study_plan": [],
            "confidence": 0.0,
            "notes": "Не удалось распарсить JSON-ответ от LLM. См. raw_model_output",
            "raw_model_output": model_output
        }


@shared_task(bind=True, max_retries=2)
def task_generate_final_report(self, session_id: str):
    """
    Celery-задача для финального отчёта LLM.
    """
    try:
        report = generate_final_recommendations(session_id)
    except Exception as exc:
        assessment_logger.exception(
            f"[LLM] final report failed for session={session_id}: {exc}"
        )
        raise self.retry(exc=exc, countdown=10)

    # сохраняем в модель TestSession
    try:
        session = TestSession.objects.get(id=session_id)
    except TestSession.DoesNotExist:
        return {"error": "not_found"}

    # session.final_report_json = report
    # session.save(update_fields=["final_report_json"])

    llm_result = generate_final_recommendations(test_session_id=session.id)
    # session.protocol_json = protocol

    if llm_result and "error" not in llm_result:
        try:
            # привести строки к нужным типам, если возможно
            if "overall_score" in llm_result:
                llm_result["overall_score"] = float(llm_result["overall_score"])
            if "confidence" in llm_result:
                llm_result["confidence"] = float(llm_result["confidence"])
            # гарантируем наличие study_plan как списка из 7 строк (если нет — не ломаем, но логируем)
            if "study_plan" in llm_result and isinstance(llm_result["study_plan"], list):
                pass
        except Exception as ex:
            assessment_logger.exception("generate_final_recommendations: normalization error: %s", str(ex))

        session.protocol_json["llm_report"] = llm_result
        session.protocol_json["analysis_generated_at"] = timezone.now().isoformat()
        session.save(update_fields=["protocol_json"])
        estimated_level = llm_result.get("estimated_level")

        if estimated_level in CEFRLevel.values:
            StudyProfile.objects.update_or_create(
                user=session.user,
                defaults={"english_level": estimated_level}
            )

    assessment_logger.info(
        f"[LLM] final report generated for session={session_id}"
    )

    return report


def _compact_protocol_for_prompt(session: TestSession) -> Dict[str, Any]:
    """
    Формируем компактную версию протокола (для экономии токенов),
    содержащую только нужные поля: question_text, level, type, answer_text, score, ai_feedback.
    """
    compact = []
    q_instances = QuestionInstance.objects.filter(session=session).order_by("created_at")
    for qi in q_instances:
        main_answer = TestAnswer.objects.filter(question=qi).order_by("answered_at").first()
        qa = {
            "question_instance_id": str(qi.id),
            "level": qi.question_json.get("level"),
            "type": qi.question_json.get("type"),
            "question_text": qi.question_json.get("question_text"),
            "answer_text": main_answer.answer_text if main_answer else None,
            "score": float(main_answer.score) if main_answer and main_answer.score is not None else None,
            "ai_feedback": main_answer.ai_feedback if main_answer else None
        }
        compact.append(qa)
    return {"questions": compact, "questions_count": len(compact)}
