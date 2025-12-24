import json

from ai.llm.llm_factory import llm_factory
from curriculum.application.ports.assessment_port import AssessmentPort
from curriculum.domain.value_objects.assessment_result import AssessmentResult
from curriculum.models.assessment.student_response import StudentTaskResponse
from curriculum.models.content.task import Task, ResponseFormat


class LLMAssessmentAdapter(AssessmentPort):
    """
    Адаптер для оценки с использованием LLM через llm_factory
    """

    def __init__(self):
        # Используем глобальный экземпляр llm_factory
        self.llm_factory = llm_factory

    def assess_task(self, task: Task, response: StudentTaskResponse) -> AssessmentResult:
        """
        Единая точка входа для оценки через LLM
        """
        try:
            # Формируем системный промпт в зависимости от типа задания
            system_prompt = self._build_system_prompt(task)

            # Формируем пользовательское сообщение
            user_message = self._build_user_message(task, response)

            # Генерируем оценку через llm_factory
            return self._generate_llm_assessment(
                task=task,
                response=response,
                system_prompt=system_prompt,
                user_message=user_message
            )
        except Exception as e:
            return self._create_fallback_result(task, str(e))

    def _build_system_prompt(self, context: dict) -> str:
        """Формирование системного промпта для LLM на основе контекста"""
        task_type = context.get('task_type', 'writing')

        if task_type == "writing":
            return f"""
            TASK: Assess the student's written response for an IT professional learning English.

            Task Prompt: {context['task_prompt']}
            Student Response: {context['student_response']}
            Target CEFR Level: {context['cefr_level']}
            Professional Context: {', '.join(context['professional_context'])}

            ASSESSMENT CRITERIA:
            1. Grammar accuracy (subject-verb agreement, tenses, articles)
            2. Vocabulary appropriateness for IT context
            3. Relevance to the prompt
            4. Clarity and coherence

            OUTPUT FORMAT (JSON ONLY):
            {{
                "score": 0.0-1.0,
                "is_correct": null,
                "error_tags": ["grammar", "vocabulary", "coherence", ...],
                "feedback": {{
                    "strengths": ["list of strengths"],
                    "improvement_areas": ["list of areas to improve"],
                    "specific_examples": ["quote error", "suggestion"]
                }},
                "confidence": 0.0-1.0
            }}
            """
        elif task_type == "speaking":
            return f"""
            TASK: Assess the student's spoken response for an IT professional learning English.

            Task Prompt: {context['task_prompt']}
            Transcribed Response: {context['transcript']}
            ASR Confidence: {context.get('asr_confidence', 0.0):.2f}
            Duration: {context.get('duration', 0.0):.1f} seconds
            Target CEFR Level: {context['cefr_level']}
            Professional Context: {', '.join(context['professional_context'])}

            ASSESSMENT CRITERIA:
            1. Fluency (flow, pauses, rhythm)
            2. Pronunciation clarity
            3. Grammar accuracy in speech
            4. Vocabulary appropriateness
            5. Relevance to the prompt

            OUTPUT FORMAT (JSON ONLY):
            {{
                "score": 0.0-1.0,
                "is_correct": null,
                "error_tags": ["fluency", "pronunciation", "grammar", ...],
                "feedback": {{
                    "strengths": ["list of strengths"],
                    "improvement_areas": ["list of areas to improve"],
                    "pronunciation_tips": ["specific tips"]
                }},
                "fluency_score": 0.0-1.0,
                "pronunciation_score": 0.0-1.0,
                "confidence": 0.0-1.0
            }}
            """
        else:
            # Fallback для других типов заданий
            return """
            You are an expert English tutor for IT professionals.
            Assess the student's response according to the CEFR level and professional context.
            Provide structured feedback in JSON format with the following fields:
            - score: float (0.0-1.0) overall quality score
            - is_correct: null (for open-ended tasks)
            - error_tags: array of detected error types
            - feedback: detailed feedback object
            - confidence: float (0.0-1.0) assessment confidence
            """

    def _build_user_message(self, task: Task, response: StudentTaskResponse) -> str:
        """Формирование пользовательского сообщения"""
        prompt = task.content.get("prompt", "")
        student_response = response.response_text

        if task.response_format == ResponseFormat.AUDIO:
            # Для аудио используем транскрипцию (предполагаем, что она уже сделана)
            student_response = getattr(response, 'transcript', student_response)

        return f"""
        Task Prompt: {prompt}
        Student Response: {student_response}
        CEFR Level: {task.difficulty_cefr}
        Professional Context: {', '.join([tag.name for tag in task.professional_tags.all()])}
        """

    def _generate_llm_assessment(
            self,
            task: Task,
            response: StudentTaskResponse,
            system_prompt: str,
            user_message: str
    ) -> AssessmentResult:
        """
        Генерация оценки через llm_factory
        """
        import asyncio

        # Получаем результат от LLM
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            self.llm_factory.generate_json_response(
                system_prompt=system_prompt,
                user_message=user_message,
                conversation_history=[],
                media_context=self._get_media_context(task)
            )
        )

        # Конвертируем в AssessmentResult
        return self._parse_llm_response(result, task)

    def _parse_llm_response(self, result, task: Task) -> AssessmentResult:
        """Конвертация ответа LLM в AssessmentResult"""
        try:
            # result содержит GenerationResult
            llm_response = result.response  # LLMResponse

            # Извлекаем данные из LLMResponse
            response_data = json.loads(llm_response.message) if isinstance(llm_response.message,
                                                                           str) else llm_response.message

            return AssessmentResult(
                score=response_data.get("score", 0.5),
                is_correct=response_data.get("is_correct"),
                error_tags=response_data.get("error_tags", []),
                feedback=response_data.get("feedback", {}),
                confidence=response_data.get("confidence", 0.8)
            )
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            return self._create_fallback_result(
                task,
                f"Failed to parse LLM response: {str(e)}"
            )

    def _create_fallback_result(self, task: Task, error: str) -> AssessmentResult:
        """Создание результата для fallback-сценария"""
        fallback_score = 0.7 if task.task_type in ["writing", "speaking"] else 0.5

        return AssessmentResult(
            score=fallback_score,
            is_correct=None,
            error_tags=["llm_processing_error"],
            feedback={
                "message": "Ваш ответ получен и будет оценен дополнительно",
                "note": f"Произошла временная ошибка при автоматической оценке: {error}"
            },
            confidence=0.4
        )

    def _get_media_context(self, task: Task):
        """Получение контекста медиафайлов для задания"""
        media_files = task.media_files.all()
        context = []
        for media in media_files:
            context.append({
                "type": media.media_type,
                "url": media.file.url if hasattr(media.file, 'url') else None
            })
        return context
