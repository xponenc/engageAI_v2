from curriculum.models import Assessment, StudentTaskResponse


class LLMAssessmentService:
    """
     Сервис LLM-оценки открытых ответов (writing / speaking).

    Назначение:
    - Преобразует ответ студента в структурированную оценку.
    - Используется ТОЛЬКО для заданий без автоматической проверки.
    - Является источником данных для SkillProfile, ErrorLog и LessonMetrics.

    Student submits response
    ↓
    StudentTaskResponse created
    ↓
    response_format in ["free_text", "audio"]
    ↓
    LLM Assessment Runner
    ↓
    Assessment saved
    ↓
    ↓
    ErrorLog updated
    SkillProfile updated
    LessonMetrics updated



    {
      "scores": {
        "grammar": 0.72,
        "vocabulary": 0.81,
        "fluency": 0.65,
        "pronunciation": null
      },
      "confidence": 0.78,
      "errors": [
        {
          "type": "tense",
          "severity": 0.6,
          "example": "I have fixed it yesterday",
          "correction": "I fixed it yesterday",
          "skill_domain": "grammar"
        }
      ],
      "strengths": [
        "clear structure",
        "relevant technical vocabulary"
      ],
      "suggestions": [
        "Review past simple vs present perfect in work contexts"
      ]
    }
    """

    def assess(self, task_response: StudentTaskResponse) -> Assessment:
        prompt = self.build_prompt(task_response)
        llm_output = self.call_llm(prompt)

        structured = self.normalize(llm_output)

        assessment = Assessment.objects.create(
            task_response=task_response,
            llm_version="gpt-4.1",
            raw_output=llm_output,
            structured_feedback=structured
        )

        return assessment

    def _build_prompt(self, task_response):
        return build_writing_prompt(task_response)

    def _call_llm(self, prompt: str) -> dict:
        """
        Вызов LLM (изолирован, чтобы легко заменить провайдера).
        """
        return call_llm_api(prompt)

    def _normalize(self, llm_output: dict) -> dict:
        """
        Приводит ответ LLM к каноническому формату assessment_v1.
        """
        return normalize_assessment_output(llm_output)