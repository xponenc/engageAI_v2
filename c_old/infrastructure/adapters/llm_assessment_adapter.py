import asyncio
import json
import logging
from pprint import pprint

from ai.llm.llm_factory import llm_factory
from curriculum.application.ports.assessment_port import AssessmentPort
from curriculum.domain.value_objects.assessment_result import AssessmentResult
from curriculum.models.assessment.student_response import StudentTaskResponse
from curriculum.models.content.task import Task, ResponseFormat

logger = logging.getLogger(__name__)

SYSTEM_BLOCK = (
    """Вы — эксперт по оценке английского языка по шкале CEFR. Оцените ответ студента **только по навыкам,
     проверяемым заданием**. Используйте шкалу 0.0–1.0. Если навык не проверялся — укажите null.
      Верните ТОЛЬКО валидный JSON по схеме:
{
  "task_id": число,
  "cefr_target": "уровень (например, B1)",
  "skill_evaluation": {
    "grammar": {"score": число|null, "confidence": число|null, "evidence": []},
    "vocabulary": {"score": число|null, "confidence": число|null, "evidence": []},
    "reading": {"score": число|null, "confidence": число|null, "evidence": []},
    "listening": {"score": число|null, "confidence": число|null, "evidence": []},
    "writing": {"score": число|null, "confidence": число|null, "evidence": []},
    "speaking": {"score": число|null, "confidence": число|null, "evidence": []}
  },
  "summary": {
    "text": "1–3 предложения",
    "advice": ["практический совет", "..."]
  }
}
Никаких пояснений вне JSON. Только JSON."""
)

#
# SKILL_GUIDELINES = (
#     "SKILL DOMAINS\n\n"
#     "You may assign scores ONLY to the following skill domains:\n"
#     "- grammar\n"
#     "- vocabulary\n"
#     "- reading\n"
#     "- listening\n"
#     "- writing\n"
#     "- speaking\n\n"
#     "Guidelines:\n"
#     "- Writing tasks usually measure: writing, grammar, vocabulary.\n"
#     "- Speaking tasks usually measure: speaking, grammar, vocabulary.\n"
#     "- Reading tasks usually measure: reading, vocabulary.\n"
#     "- Listening tasks usually measure: listening, vocabulary.\n"
#     "- Grammar or vocabulary tasks usually measure only that specific skill.\n"
#     "- Do NOT infer skills that are not directly evidenced by the task."
# )

#
# RESPONSE_FORMAT = (
#     "OUTPUT CONTRACT\n\n"
#     "You MUST return a JSON object that STRICTLY conforms to the schema below.\n"
#     "This is a machine contract, not an example.\n"
#     "If a value cannot be determined, use null.\n"
#     "Do NOT rename fields.\n"
#     "Do NOT add fields.\n"
#     "Do NOT omit fields.\n\n"
#
#     "JSON SCHEMA:\n"
#     "{\n"
#     '  "task_id": number,\n'
#     '  "cefr_target": string,\n'
#     '  "skill_evaluation": {\n'
#     '    "grammar":   {"score": number|null, "confidence": number|null, "evidence": []},\n'
#     '    "vocabulary":{"score": number|null, "confidence": number|null, "evidence": []},\n'
#     '    "reading":   {"score": number|null, "confidence": number|null, "evidence": []},\n'
#     '    "listening": {"score": number|null, "confidence": number|null, "evidence": []},\n'
#     '    "writing":   {"score": number|null, "confidence": number|null, "evidence": []},\n'
#     '    "speaking":  {"score": number|null, "confidence": number|null, "evidence": []}\n'
#     "  },\n"
#     '  "summary": {\n'
#     '    "text": string,\n'
#     '    "advice": [string]\n'
#     "  }\n"
#     "}\n\n"
#
#     "VALIDATION RULES:\n"
#     "- All numbers MUST be between 0.0 and 1.0.\n"
#     "- Evidence MUST be an array (may be empty).\n"
#     "- Summary.text MUST be 1–3 sentences.\n"
#     "- Advice items MUST be short and actionable.\n"
#     "- Output MUST be valid JSON and NOTHING else.\n"
# )



class LLMAssessmentAdapter(AssessmentPort):
    """
    Адаптер для оценки с использованием LLM через llm_factory
    """

    def __init__(self):
        # Используем глобальный экземпляр llm_factory
        self.llm_factory = llm_factory

    def assess_task(self, task: Task, response: StudentTaskResponse) -> AssessmentResult:
        """
        Main entry point: assess a single task with LLM.
        """
        try:
            prompt = self._build_prompt(task, response)
            return self._call_llm(task, prompt)
        except Exception as exc:
            raise RuntimeError(f"LLM assessment failed: {exc}") from exc

    # PROMPT CONSTRUCTION

    def _build_context_block(self, task: Task, response: StudentTaskResponse) -> str:
        prompt = task.content.get("prompt", "").strip()
        expected_skills = set(task.content.get("expected_skills", []))

        # Определяем текст ответа
        student_text = response.response_text
        if task.response_format == ResponseFormat.AUDIO:
            student_text = getattr(response, "transcript", None)

        # Обработка отсутствующего/некорректного ответа
        if not student_text or not student_text.strip():
            student_text = "[No valid student response provided]"

        # Формируем контекст, ориентируясь на то, что модельу действительно нужно
        lines = [
            f"CEFR target level: {task.difficulty_cefr}",
            "",
            "Задание:",
            prompt,
            "",
            "Skills to assess (ONLY these):",
            ", ".join(sorted(expected_skills)) if expected_skills else "None specified",
            "",
            "Ответ студента:",
            student_text.strip()
        ]

        return "\n".join(lines)

    def _build_prompt(self, task: Task, response: StudentTaskResponse) -> str:
        context_block = self._build_context_block(task, response)
        return f"""
    {context_block}

    """

    # LLM CALL
    def _call_llm(self, task: Task, prompt: str) -> AssessmentResult:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            self.llm_factory.generate_json_response(
                system_prompt=SYSTEM_BLOCK,
                user_message=prompt,
                conversation_history=[],
                media_context=self._get_media_context(task),
            )
        )
        print(f" _call_llm: result=", result)
        return self._parse_llm_response(result)

    # RESPONSE PARSING

    def _parse_llm_response(self, result) -> AssessmentResult:
        """
        Конвертация ответа LLM в валидный AssessmentResult
        """

        # result.response — это dict
        llm_payload = result.response
        print("_parse_llm_response llm_payload =", llm_payload)

        raw = llm_payload.get("response")
        print("_parse_llm_response raw =", raw)

        if not raw or not isinstance(raw, str) or not raw.strip():
            raise ValueError("Empty LLM response")

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("LLM returned non-JSON:\n%s", raw)
            raise RuntimeError("LLM returned invalid JSON") from e

        print("_parse_llm_response parsed payload =", payload)

        # Проверка наличия ключевых полей
        if "skill_evaluation" not in payload or "summary" not in payload:
            logger.warning(
                "Invalid LLM response format for task_id %s: missing 'skill_evaluation' or 'summary'",
                payload.get("task_id")
            )
            # Возвращаем нейтральный AssessmentResult
            return AssessmentResult(
                task_id=payload.get("task_id", -1),
                cefr_target=payload.get("cefr_target", ""),
                skill_evaluation={
                    skill: {"score": 0.5, "confidence": 0.5, "evidence": []}
                    for skill in ["grammar", "vocabulary", "reading", "listening", "writing", "speaking"]
                },
                summary={"text": "No valid assessment could be generated.", "advice": []},
                metadata={"error": "invalid_llm_response", "raw_llm": payload}
            )

        # Валидация и создание AssessmentResult
        return AssessmentResult(
            task_id=payload.get("task_id"),
            cefr_target=payload.get("cefr_target", ""),
            skill_evaluation=payload["skill_evaluation"],
            summary=payload["summary"],
            metadata={"raw_llm": payload}  # сохраняем весь ответ для аудита
        )

    # MEDIA CONTEXT

    def _get_media_context(self, task: Task) -> list[dict]:
        if not hasattr(task, "media_files"):
            return []

        context = []
        for media in task.media_files.all():
            context.append(
                {
                    "type": media.media_type,
                    "url": getattr(media.file, "url", None),
                }
            )
        return context
