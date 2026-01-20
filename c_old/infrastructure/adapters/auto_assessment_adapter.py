import json
import logging

from curriculum.application.ports.assessment_port import AssessmentPort
from curriculum.domain.value_objects.assessment_result import AssessmentResult
from curriculum.models.assessment.student_response import StudentTaskResponse
from curriculum.models.content.task import Task, ResponseFormat
from curriculum.infrastructure.validation.task_schemas import TASK_CONTENT_SCHEMAS
from curriculum.validators import SkillDomain

logger = logging.getLogger(__name__)


class SchemaValidationError(Exception):
    """Исключение для ошибок валидации схемы контента задания"""
    pass


class AutoAssessorAdapter(AssessmentPort):
    """
    Адаптер для автоматической оценки закрытых заданий.

    Основные принципы:
    1. Поддерживаемые форматы и схемы:
       - SINGLE_CHOICE + scq_v1
       - MULTIPLE_CHOICE + mcq_v1
       - SHORT_TEXT + short_text_v1
    2. Централизованная валидация через TASK_CONTENT_SCHEMAS
    3. Четкое соответствие схемам и форматам ответов
    4. Расширяемая архитектура для новых схем
    """

    def assess_task(self, task: Task, response: StudentTaskResponse) -> AssessmentResult:
        """
        Основной метод оценки с валидацией схемы.
        Возвращает AssessmentResult.
        """
        # Валидация формата и схемы
        self._validate_format_schema_compatibility(task)
        schema = self._get_schema_for_task(task)
        self._validate_task_content(task.content, schema)

        # Выбор стратегии оценки
        if task.response_format == ResponseFormat.SINGLE_CHOICE:
            return self._assess_single_choice(task, response)
        elif task.response_format == ResponseFormat.MULTIPLE_CHOICE:
            return self._assess_multiple_choice(task, response)
        elif task.response_format == ResponseFormat.SHORT_TEXT:
            return self._assess_short_text(task, response)
        else:
            # Нейтральная оценка для неизвестного формата
            return self._neutral_assessment(task)

    def _neutral_assessment(self, task: Task) -> AssessmentResult:
        """Возвращает нейтральный AssessmentResult с None по неоцениваемым навыкам, 0.5 по task_type"""

        skill_eval = {}
        for skill in SkillDomain.values:
            if skill == task.task_type:
                skill_eval[skill] = {"score": 0.5, "confidence": 0.5, "evidence": []}
            else:
                skill_eval[skill] = {"score": None, "confidence": None, "evidence": []}

        summary = {"text": "Невозможно оценить задание автоматически", "advice": []}

        return AssessmentResult(
            task_id=task.pk,
            cefr_target="N/A",
            skill_evaluation=skill_eval,
            summary=summary,
            error_tags=["unsupported_format"],
            metadata={}
        )

    def _validate_format_schema_compatibility(self, task: Task) -> None:
        """
        Проверяет соответствие формата задания и схемы контента.

        Примеры корректных пар:
        - SINGLE_CHOICE + scq_v1
        - MULTIPLE_CHOICE + mcq_v1
        - SHORT_TEXT + short_text_v1

        Raises:
            SchemaValidationError: При несоответствии формата и схемы
        """
        schema_name = task.content_schema_version
        response_format = task.response_format

        if schema_name not in TASK_CONTENT_SCHEMAS:
            raise SchemaValidationError(f"Unknown schema: {schema_name}")

        schema = TASK_CONTENT_SCHEMAS[schema_name]
        supported_formats = schema.get("supported_formats", [])

        if response_format not in supported_formats:
            raise SchemaValidationError(
                f"Schema '{schema_name}' does not support response format '{response_format}'. "
                f"Supported formats: {supported_formats}"
            )

    def _get_schema_for_task(self, task: Task) -> dict:
        """
        Получает схему валидации для задания.

        Raises:
            SchemaValidationError: Если схема не найдена
        """
        schema_name = task.content_schema_version
        if schema_name not in TASK_CONTENT_SCHEMAS:
            raise SchemaValidationError(f"Schema not found: {schema_name}")
        return TASK_CONTENT_SCHEMAS[schema_name]

    def _validate_task_content(self, content: dict, schema: dict) -> None:
        """
        Валидация контента задания по схеме.

        Проверяет:
        1. Наличие обязательных полей
        2. Корректность типов данных
        3. Диапазоны значений
        4. Ссылочные ограничения (reference)

        Args:
            content: Контент задания
            schema: Схема валидации

        Raises:
            SchemaValidationError: При нарушении правил валидации
        """
        # 1. Проверка обязательных полей
        required_fields = schema.get("required", set())
        missing_fields = required_fields - set(content.keys())
        if missing_fields:
            raise SchemaValidationError(f"Missing required fields: {missing_fields}")

        # 2. Проверка правил валидации для каждого поля
        validation_rules = schema.get("validation_rules", {})
        for field_name, rules in validation_rules.items():
            if field_name not in content and field_name not in schema.get("optional", set()):
                continue

            field_value = content.get(field_name)
            if field_value is None:
                continue

            # Проверка типа
            expected_type = rules.get("type")
            if expected_type:
                if not self._validate_type(field_value, expected_type):
                    raise SchemaValidationError(
                        f"Field '{field_name}' must be {expected_type}, got {type(field_value).__name__}"
                    )

            # Специфические правила валидации
            if expected_type == "list":
                self._validate_list_field(field_value, rules, field_name)
            elif expected_type == "int":
                self._validate_int_field(field_value, rules, field_name, content)
            elif expected_type == "str":
                self._validate_str_field(field_value, rules, field_name)

    def _validate_type(self, value, expected_type: str) -> bool:
        """Проверка типа значения"""
        type_mapping = {
            "str": str,
            "int": int,
            "bool": bool,
            "list": list,
            "dict": dict
        }

        expected_python_type = type_mapping.get(expected_type)
        if not expected_python_type:
            return True  # Неизвестный тип - пропускаем проверку

        return isinstance(value, expected_python_type)

    def _validate_list_field(self, value: list, rules: dict, field_name: str) -> None:
        """Валидация поля типа list"""
        # Проверка длины списка
        min_items = rules.get("min_items")
        max_items = rules.get("max_items")

        if min_items is not None and len(value) < min_items:
            raise SchemaValidationError(f"Field '{field_name}' must have at least {min_items} items")
        if max_items is not None and len(value) > max_items:
            raise SchemaValidationError(f"Field '{field_name}' must have at most {max_items} items")

        # Проверка типа элементов
        item_type = rules.get("item_type")
        if item_type:
            for idx, item in enumerate(value):
                if not self._validate_type(item, item_type):
                    raise SchemaValidationError(
                        f"Item at index {idx} in field '{field_name}' must be {item_type}, "
                        f"got {type(item).__name__}"
                    )

    def _validate_int_field(
            self,
            value: int,
            rules: dict,
            field_name: str,
            content: dict
    ) -> None:
        """
        Валидация поля типа int с поддержкой reference на content.
        Поддерживает специальные правила для scq_v1 и mcq_v1 схем.
        """

        # Минимум
        min_value = rules.get("min")
        if min_value is not None and value < min_value:
            raise SchemaValidationError(
                f"Field '{field_name}' must be >= {min_value}"
            )

        # Reference (динамический максимум)
        reference = rules.get("reference")
        if reference:
            try:
                if reference == "options.length - 1":
                    # Проверка для SCQ: correct_idx должен быть в диапазоне [0, len(options)-1]
                    options = content.get("options", [])
                    if not isinstance(options, list):
                        raise SchemaValidationError(
                            f"Field 'options' must be a list for reference '{reference}'"
                        )
                    if len(options) == 0:
                        raise SchemaValidationError(
                            f"Field 'options' cannot be empty for reference '{reference}'"
                        )
                    max_value = len(options) - 1
                    if value < 0:
                        raise SchemaValidationError(
                            f"Field '{field_name}' must be >= 0"
                        )
                    if value > max_value:
                        raise SchemaValidationError(
                            f"Field '{field_name}' value {value} exceeds maximum allowed index {max_value} "
                            f"(based on options length: {len(options)})"
                        )

                elif reference == "options.length":
                    # Проверка для MCQ: значения должны быть <= длины массива options
                    options = content.get("options", [])
                    if not isinstance(options, list):
                        raise SchemaValidationError(
                            f"Field 'options' must be a list for reference '{reference}'"
                        )
                    max_value = len(options)
                    if value > max_value:
                        raise SchemaValidationError(
                            f"Field '{field_name}' value {value} exceeds maximum allowed value {max_value} "
                            f"(based on options length: {len(options)})"
                        )

                elif reference == "correct_indices.length":
                    # Проверка для MCQ: min_selections/max_selections не могут превышать количество правильных ответов
                    correct_indices = content.get("correct_indices", [])
                    if not isinstance(correct_indices, list):
                        raise SchemaValidationError(
                            f"Field 'correct_indices' must be a list for reference '{reference}'"
                        )
                    max_value = len(correct_indices)
                    if value > max_value:
                        raise SchemaValidationError(
                            f"Field '{field_name}' value {value} exceeds maximum allowed value {max_value} "
                            f"(based on correct_indices length: {len(correct_indices)})"
                        )

                else:
                    # Неизвестная ссылка → критическая ошибка валидации
                    raise SchemaValidationError(
                        f"Unsupported reference '{reference}' in field '{field_name}'. "
                        f"Supported references: 'options.length - 1', 'options.length', 'correct_indices.length'"
                    )

            except SchemaValidationError:
                # Пробрасываем наши исключения вверх
                raise
            except Exception as e:
                # Обработка других ошибок
                raise SchemaValidationError(
                    f"Failed to resolve reference '{reference}' for field '{field_name}': {str(e)}"
                )

    def _validate_str_field(self, value: str, rules: dict, field_name: str) -> None:
        """Валидация поля типа str"""
        min_length = rules.get("min_length")
        if min_length is not None and len(value) < min_length:
            raise SchemaValidationError(f"Field '{field_name}' must be at least {min_length} characters long")

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
                    evidence = [] if is_correct else [f"Выбран вариант: {options[student_choice]}, правильный: {options[correct_idx]}"]
                    skill_eval[skill] = {"score": score, "confidence": 1.0, "evidence": evidence}
                else:
                    skill_eval[skill] = {"score": None, "confidence": None, "evidence": []}

            # summary
            summary = {
                "text": "Правильно" if is_correct else f"Неверно. Правильный вариант: {options[correct_idx]}",
                "advice": [] if is_correct else [content.get("explanation", "Попробуйте ещё раз")]
            }

            return AssessmentResult(
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
