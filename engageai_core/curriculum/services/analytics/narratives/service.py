

from llm.client import call_llm  # твой существующий LLM wrapper

from curriculum.services.analytics.narratives.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from curriculum.services.analytics.narratives.schemas import ExplainabilityInput, NarrativeOutput


class ExplainabilityNarrativeService:
    """
    Преобразует explainability-структуру
    в человекочитаемое объяснение через LLM.

    SkillTrajectory
    ↓
    ExplainabilityEngine          (структура причин)
    ↓
    ExplainabilityNarrativeService
    ↓
    LLM (verbalize only)
    ↓
    Human-readable explanation
    ↓
    UI / Teacher / Student

    пример
    вход
    {
        "decision": "SIMPLIFY",
        "primary_reason": "Обнаружено снижение навыка grammar",
        "skill_insights": [
        {
            "skill": "grammar",
            "direction": "declining",
            "stability": 0.32
        }
        ],
        "confidence": 0.78
    }

    выход
    {
        "summary": "Система упростила следующий шаг, так как грамматика сейчас даётся нестабильно.",
        "details": "В последних уроках наблюдается снижение уверенности в грамматике. Это нормальная ситуация при усвоении сложных конструкций.",
        "recommendations": "Рекомендуется повторить базовые примеры и уделить внимание типичным ошибкам.",
        "confidence_note": "Решение принято с высокой уверенностью."
    }
    """

    def build_narrative(
        self,
        explainability: ExplainabilityInput
    ) -> NarrativeOutput:
        """
        Главная точка входа.

        explainability — результат ExplainabilityEngine
        """

        prompt = self._build_prompt(explainability)
        raw_output = call_llm(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt
        )

        return self._normalize(raw_output)

    # ---------- internal ----------

    def _build_prompt(self, data: ExplainabilityInput) -> str:
        """
        Строит user prompt из explainability данных.
        """

        return USER_PROMPT_TEMPLATE.format(
            decision=data["decision"],
            primary_reason=data["primary_reason"],
            supporting_factors=data["supporting_factors"],
            skill_insights=self._format_skills(data["skill_insights"]),
            confidence=data["confidence"],
        )

    def _format_skills(self, skills):
        """
        Упрощает список навыков для LLM.
        """

        lines = []
        for s in skills:
            lines.append(
                f"- {s['skill']}: {s['direction']} "
                f"(устойчивость {round(s['stability'], 2)})"
            )
        return "\n".join(lines)

    def _normalize(self, llm_output) -> NarrativeOutput:
        """
        Нормализация и защита от галлюцинаций.

        В реальной системе тут:
        - JSON schema validation
        - fallback тексты
        """

        return {
            "summary": llm_output.get("summary", ""),
            "details": llm_output.get("details", ""),
            "recommendations": llm_output.get("recommendations", ""),
            "confidence_note": llm_output.get("confidence_note", ""),
        }
