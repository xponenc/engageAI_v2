import json
import logging

from curriculum.models.assessment.assessment_result import AssessmentResult
from curriculum.models.content.response_format import ResponseFormat
from curriculum.models.content.task import Task
from curriculum.models.student.student_response import StudentTaskResponse
from curriculum.services.base_assessment_adapter import AssessmentPort
from curriculum.validation.task_schemas import TASK_CONTENT_SCHEMAS
from curriculum.validators import SkillDomain

logger = logging.getLogger(__name__)


class SchemaValidationError(Exception):
    """Исключение для ошибок валидации схемы контента задания"""
    pass


class AutoAssessorAdapter(AssessmentPort):
    """
    Адаптер для автоматической оценки закрытых и полузакрытых заданий.
    Поддерживает схемы: scq_v1, mcq_v1, short_text_v1.
    """

    SUPPORTED_FORMATS = {
        ResponseFormat.SINGLE_CHOICE: ['scq_v1'],
        ResponseFormat.MULTIPLE_CHOICE: ['mcq_v1'],
        # ResponseFormat.SHORT_TEXT: ['short_text_v1'],
    }

    def assess_task(self, task: Task, response: StudentTaskResponse) -> AssessmentResult:
        try:
            # 1. Валидация совместимости формата и схемы
            self._validate_format_schema(task)

            # 2. Выбор метода оценки
            if task.response_format == ResponseFormat.SINGLE_CHOICE:
                return self._assess_single_choice(task, response)
            elif task.response_format == ResponseFormat.MULTIPLE_CHOICE:
                return self._assess_multiple_choice(task, response)
            elif task.response_format == ResponseFormat.SHORT_TEXT:
                return self._assess_short_text(task, response)
            else:
                return self._neutral_assessment(task)

        except SchemaValidationError as e:
            logger.error(f"Schema validation failed for task {task.id}: {str(e)}")
            return self._neutral_assessment(task, error_tags=["schema_error"])
        except Exception as e:
            logger.error(f"Auto assessment failed for task {task.id}: {str(e)}", exc_info=True)
            return self._neutral_assessment(task, error_tags=["assessment_error"])


    def _validate_format_schema(self, task: Task) -> None:
        """
        Проверяет, что формат ответа задания и версия схемы контента
        поддерживаются автооценщиком, а также что все обязательные поля
        присутствуют в content задания.

        Этапы валидации:
        1. Проверка, что формат ответа поддерживается автооценщиком.
        2. Проверка, что версия схемы разрешена для данного формата ответа.
        3. Загрузка определения схемы из TASK_CONTENT_SCHEMAS.
        4. Проверка наличия всех обязательных полей,
           определённых схемой, в task.content.

        Исключения:
            SchemaValidationError:
                - если формат ответа не поддерживается
                - если схема не совместима с форматом ответа
                - если определение схемы отсутствует
                - если в task.content отсутствуют обязательные поля
        """

        response_format = task.response_format
        schema_name = task.content_schema_version

        # 1. Validate response format
        if response_format not in self.SUPPORTED_FORMATS:
            raise SchemaValidationError(
                f"Response format '{response_format}' is not supported by the auto-grader"
            )

        # 2. Validate schema compatibility with response format
        if schema_name not in self.SUPPORTED_FORMATS[response_format]:
            raise SchemaValidationError(
                f"Schema '{schema_name}' is not supported for response format '{response_format}'"
            )

        # 3. Load schema definition
        schema_definition = TASK_CONTENT_SCHEMAS.get(schema_name)
        if not schema_definition:
            raise SchemaValidationError(
                f"Unknown task content schema: '{schema_name}'"
            )

        # 4. Validate required content fields
        required_fields = schema_definition.get("required", set())

        missing_fields = [
            field for field in required_fields
            if field not in task.content
        ]

        if missing_fields:
            raise SchemaValidationError(
                f"Missing required fields in task content: {missing_fields}"
            )

    def _neutral_assessment(self, task: Task, error_tags=None):
        error_tags = error_tags or []
        skill_eval = {}
        for skill in SkillDomain.values:
            if skill == task.task_type:
                skill_eval[skill] = {"score": 0.0, "confidence": 0.0, "evidence": []}
            else:
                skill_eval[skill] = {"score": None, "confidence": None, "evidence": []}

        return AssessmentResult(
            is_correct=False,
            task_id=task.pk,
            cefr_target="N/A",
            skill_evaluation=skill_eval,
            summary={"text": "Автоматическая оценка невозможна", "advice": []},
            error_tags=error_tags,
            metadata={}
        )

    def _assess_single_choice(self, task: Task, response: StudentTaskResponse) -> AssessmentResult:
        """Оценка одиночного выбора (SINGLE_CHOICE)"""
        content = task.content
        options = content["options"]
        correct_idx = content["correct_idx"]

        try:
            student_choice = self._parse_student_choice_scq(response.response_text, task)

            is_correct = (student_choice == correct_idx)
            score = 1.0 if is_correct else 0.0

            # skill_evaluation
            skill_eval = {}
            for skill in SkillDomain.values:
                if skill == task.task_type:
                    evidence = [] if is_correct else [
                        f"Выбран вариант: {options[student_choice]}, правильный: {options[correct_idx]}"]
                    skill_eval[skill] = {"score": score, "confidence": 1.0, "evidence": evidence}
                else:
                    skill_eval[skill] = {"score": None, "confidence": None, "evidence": []}

            # summary
            summary = {
                "text": "Правильно" if is_correct else f"Неверно. Правильный вариант: {options[correct_idx]}",
                "advice": [] if is_correct else [content.get("explanation", "Попробуйте ещё раз")]
            }

            return AssessmentResult(
                is_correct=is_correct,
                task_id=task.pk,
                cefr_target="N/A",
                skill_evaluation=skill_eval,
                summary=summary,
                error_tags=[],
                metadata={"student_choice": student_choice, "correct_idx": correct_idx, "options": options}
            )
        except Exception as e:
            logger.error(f"SINGLE_CHOICE assessment failed for task {task.pk}: {str(e)}")
            return self._neutral_assessment(task)

    def _parse_student_choice_scq(self, response_text: str, task: Task) -> int | None:
        """
        Парсинг ответа для одиночного выбора.
        Поддерживает:
        - Точный текст варианта
        """
        response_text = (response_text or "").strip()

        if not response_text:
            return None

        student_text = response_text.lower()
        options = task.content["options"]

        for idx, option in enumerate(options):
            if student_text == option.lower().strip():
                return idx

        raise ValueError(f"Invalid choice: '{response_text}' not found in options")

    def _assess_multiple_choice(
            self,
            task: Task,
            response: StudentTaskResponse
    ) -> AssessmentResult:
        """
        Оценка задания с множественным выбором (mcq_v1).

        Поддерживает ответы:
        - JSON список значений options: ["latency", "throughput"]
        - JSON список индексов: [0, 2]
        - строка индексов: "0,2"
        """
        content = task.content
        options: list[str] = content.get("options", [])
        correct_indices: list[int] = content.get("correct_indices", [])
        min_sel: int = content.get("min_selections", 1)
        max_sel: int = content.get("max_selections", len(options))

        raw = response.response_text
        # пустой ответ → сразу 0 баллов
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            # Студент ничего не выбрал → score = 0
            score = 0.0

            evidence: list[str] = ["Нет выбранных вариантов"]

            skill_eval = {}
            for skill in SkillDomain.values:
                if skill == task.task_type:
                    skill_eval[skill] = {
                        "score": score,
                        "confidence": 1.0,
                        "evidence": evidence,
                    }
                else:
                    skill_eval[skill] = {
                        "score": None,
                        "confidence": None,
                        "evidence": [],
                    }

            summary = {
                "text": "0 правильных вариантов выбрано (ответ пустой)",
                "advice": ["Необходимо выбрать хотя бы один вариант ответа."],
            }

            return AssessmentResult(
                is_correct=False,
                task_id=task.pk,
                cefr_target="N/A",
                skill_evaluation=skill_eval,
                summary=summary,
                error_tags=["empty_response"],
                metadata={
                    "student_indices": [],
                    "correct_indices": correct_indices,
                    "min_selections": min_sel,
                    "max_selections": max_sel,
                },
            )

        try:

            student_indices: list[int] = []

            # ===== 1. JSON parsing =====
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                parsed = None

            # ===== 2. Parsed as list =====
            if isinstance(parsed, list):
                # список строк → маппинг в индексы
                if all(isinstance(v, str) for v in parsed):
                    option_to_index = {opt: i for i, opt in enumerate(options)}
                    for value in parsed:
                        if value not in option_to_index:
                            logger.warning(
                                "Unknown option value in MULTIPLE_CHOICE",
                                extra={
                                    "task_id": task.pk,
                                    "value": value,
                                    "options": options,
                                }
                            )
                            return self._neutral_assessment(task)
                        student_indices.append(option_to_index[value])

                # список чисел → используем напрямую
                elif all(isinstance(v, int) for v in parsed):
                    student_indices = parsed.copy()

                else:
                    return self._neutral_assessment(task)

            # ===== 3. Fallback: "0,2,3" =====
            elif isinstance(raw, str):
                try:
                    student_indices = [
                        int(i.strip())
                        for i in raw.split(",")
                        if i.strip()
                    ]
                except Exception:
                    return self._neutral_assessment(task)

            else:
                return self._neutral_assessment(task)

            # ===== 4. Out-of-range =====
            if any(i < 0 or i >= len(options) for i in student_indices):
                logger.warning(
                    "Out-of-range option index in MULTIPLE_CHOICE",
                    extra={
                        "task_id": task.pk,
                        "student_indices": student_indices,
                        "options_len": len(options),
                    }
                )
                return self._neutral_assessment(task)

            # ===== 5. Min / Max selections =====
            if not (min_sel <= len(student_indices) <= max_sel):
                return self._neutral_assessment(task)

            # ===== 6. Score =====
            correct_set = set(correct_indices)
            chosen_set = set(student_indices)
            correct_chosen = correct_set & chosen_set

            score = (
                len(correct_chosen) / len(correct_indices)
                if correct_indices else 0.0
            )

            # ===== 7. Evidence =====
            evidence: list[str] = []
            for i in student_indices:
                opt_text = options[i]
                correctness = "✔" if i in correct_set else "✖"
                evidence.append(f"{correctness} {opt_text}")

            # ===== 8. Skill evaluation =====
            skill_eval = {}
            for skill in SkillDomain.values:
                if skill == task.task_type:
                    skill_eval[skill] = {
                        "score": score,
                        "confidence": 1.0,
                        "evidence": evidence,
                    }
                else:
                    skill_eval[skill] = {
                        "score": None,
                        "confidence": None,
                        "evidence": [],
                    }

            summary = {
                "text": f"Выбрано {len(correct_chosen)}/{len(correct_indices)} правильных вариантов",
                "advice": [],
            }

            return AssessmentResult(
                is_correct=True if set(student_indices)==set(correct_indices) else False,
                task_id=task.pk,
                cefr_target="N/A",
                skill_evaluation=skill_eval,
                summary=summary,
                error_tags=[],
                metadata={
                    "student_indices": student_indices,
                    "correct_indices": correct_indices,
                    "min_selections": min_sel,
                    "max_selections": max_sel,
                },
            )

        except Exception as e:
            logger.error(
                f"MULTIPLE_CHOICE assessment failed for task {task.pk}: {e}",
                exc_info=True,
            )
            return self._neutral_assessment(task)

    def _assess_short_text(self, task: Task, response: StudentTaskResponse) -> AssessmentResult:
        """
        Оценка задания с кратким текстовым ответом (short_text_v1) в доменном формате AssessmentResult.

        Алгоритм:
        1. Проверка типа ответа студента
        2. Приведение к строке и проверка длины
        3. Сравнение с correct_answers (с учётом case_sensitive)
        4. Формирование score и evidence
        5. Формирование skill_evaluation с использованием SkillDomain
        """
        content = task.content
        student_answer = response.response_text

        try:
            # Пытаемся привести к строке
            if not isinstance(student_answer, str):
                student_answer = str(student_answer) if student_answer is not None else ""

            student_answer_stripped = student_answer.strip()

            # пустой ответ → сразу 0 баллов
            if student_answer_stripped == "":
                score = 0.0
                evidence = ["Ответ пустой или состоит только из пробелов"]

                skill_eval = {}
                for skill in SkillDomain.values:
                    if skill == task.task_type:
                        skill_eval[skill] = {
                            "score": score,
                            "confidence": 1.0,
                            "evidence": evidence,
                        }
                    else:
                        skill_eval[skill] = {
                            "score": None,
                            "confidence": None,
                            "evidence": [],
                        }

                summary = {
                    "text": "Ответ не предоставлен",
                    "advice": ["Необходимо ввести ответ в поле."]
                }

                return AssessmentResult(
                    is_correct=False,
                    task_id=task.pk,
                    cefr_target="N/A",
                    skill_evaluation=skill_eval,
                    summary=summary,
                    error_tags=["empty_response"],
                    metadata={
                        "student_answer": student_answer,
                        "correct_answers": content.get("correct_answers", []),
                        "case_sensitive": content.get("case_sensitive", False),
                        "min_length": content.get("min_length", 1),
                        "max_length": content.get("max_length", 100),
                    },
                )

            # Параметры схемы
            correct_answers = content.get("correct_answers", [])
            case_sensitive = content.get("case_sensitive", False)
            min_length = content.get("min_length", 1)
            max_length = content.get("max_length", 100)

            # Проверка длины ответа
            answer_length = len(student_answer_stripped)
            if not (min_length <= answer_length <= max_length):
                return self._neutral_assessment(task)

            # Проверка совпадения с correct_answers
            if correct_answers:
                if not case_sensitive:
                    student_answer_norm = student_answer_stripped.lower()
                    correct_norm = [a.lower() for a in correct_answers]
                else:
                    student_answer_norm = student_answer_stripped
                    correct_norm = [a.strip() for a in correct_answers]

                is_correct = student_answer_norm in correct_norm
                score = 1.0 if is_correct else 0.0
                evidence = [f"Ответ: {student_answer} — {'✔' if is_correct else '✖'}"]
            else:
                # Нет эталонного ответа → нейтральная оценка
                return self._neutral_assessment(task)

            # skill_evaluation
            skill_eval = {}
            for skill in SkillDomain.values:
                if skill == task.task_type:
                    skill_eval[skill] = {"score": score, "confidence": 1.0, "evidence": evidence}
                else:
                    skill_eval[skill] = {"score": None, "confidence": None, "evidence": []}

            advice = []
            if not case_sensitive:
                advice.append("Проверьте регистр и формат ответа.")

            summary = {
                "text": "Ответ проверен автоматически",
                "advice": advice
            }

            return AssessmentResult(
                is_correct=is_correct,
                task_id=task.pk,
                cefr_target="N/A",
                skill_evaluation=skill_eval,
                summary=summary,
                error_tags=[],
                metadata={
                    "student_answer": student_answer,
                    "correct_answers": correct_answers,
                    "case_sensitive": case_sensitive,
                    "min_length": min_length,
                    "max_length": max_length
                }
            )
        except Exception as e:
            logger.error(f"SHORT_TEXT assessment failed for task {task.pk}: {str(e)}")
            return self._neutral_assessment(task)
