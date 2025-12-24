# import logging
#
# from curriculum.application.ports.assessment_port import AssessmentPort
# from curriculum.models.assessment.assessment import Assessment
# from curriculum.models.assessment.student_response import StudentTaskResponse
# from curriculum.models.content.task import Task, ResponseFormat
#
# logger = logging.getLogger(__name__)
#
#
# class AutoAssessorAdapter(AssessmentPort):
#     """
#     Адаптер для автоматической оценки закрытых заданий.
#     """
#
#     def __init__(self,):
#         """
#         Инициализация адаптера
#
#         Args:
#             asr_service: Сервис для распознавания речи (опционально, создается по умолчанию)
#         """
#         # self.speech_to_text_service = SpeechToTextFactory().get_service()
#
#     def assess_task(self, task: Task, response: StudentTaskResponse) -> Assessment:
#         """Единая точка входа, выбор стратегии внутри"""
#         if task.response_format in [ResponseFormat.SINGLE_CHOICE, ResponseFormat.MULTIPLE_CHOICE]:
#             return self._assess_closed_task(task, response)
#         elif task.response_format == ResponseFormat.SHORT_TEXT:
#             return self._assess_short_text(task, response)
#         elif task.response_format == ResponseFormat.AUDIO:
#             return self._assess_audio(task, response)  # обработка аудио внутри
#         else:
#             return self._create_fallback_assessment(task, response)
#
#     def _assess_audio(self, task: Task, response: StudentTaskResponse) -> Assessment:
#         """
#         Обработка аудио ответов с использованием ASR и правил
#         (без LLM, так как это Auto-ассессор)
#         """
#         try:
#             # Шаг 1: Проверка наличия аудио файла
#             if not response.audio_file:
#                 return self._create_error_assessment(task, response, "No audio file provided")
#
#             # Шаг 2: Анализ аудио через ASR
#             asr_result = self._analyze_audio_with_asr(response.audio_file)
#
#             # Шаг 3: Базовая оценка на основе ASR-результата
#             score = self._calculate_audio_score(asr_result)
#
#             # Шаг 4: Создание Assessment
#             assessment = Assessment.objects.create(
#                 task_response=response,
#                 llm_version="auto-audio-v1",
#                 raw_output={
#                     "asr_transcript": asr_result.get("transcript"),
#                     "asr_confidence": asr_result.get("confidence"),
#                     "duration_sec": asr_result.get("duration")
#                 },
#                 structured_feedback={
#                     "score": score,
#                     "is_correct": None,  # Для аудио нет бинарной корректности
#                     "error_tags": self._detect_audio_errors(asr_result),
#                     "feedback": self._generate_audio_feedback(asr_result, score)
#                 },
#                 score=score  # Прямое сохранение оценки в диапазоне 0.0-1.0
#             )
#
#             return assessment
#
#         except Exception as e:
#             return self._create_error_assessment(task, response, f"Audio processing failed: {str(e)}")
#
#     def _assess_closed_task(self, task: Task, response: StudentTaskResponse) -> Assessment:
#         """
#         Оценка закрытых заданий (MCQ) - только mcq_v1
#         """
#         if task.content_schema_version == "mcq_v1":
#             try:
#                 student_choice = int(response.response_text.strip())
#                 correct_idx = task.content["correct_idx"]
#                 is_correct = (student_choice == correct_idx)
#                 score = 1.0 if is_correct else 0.0
#
#                 # Создаем Assessment
#                 assessment = Assessment.objects.create(
#                     task_response=response,
#                     llm_version="auto-mcq-v1",
#                     raw_output={
#                         "student_choice": student_choice,
#                         "correct_idx": correct_idx,
#                         "task_content": task.content
#                     },
#                     structured_feedback={
#                         "score": score,
#                         "is_correct": is_correct,
#                         "error_tags": [] if is_correct else ["concept_gap"],
#                         "feedback": {
#                             "hint": "Правильный ответ" if is_correct else task.content.get("explanation",
#                                                                                            "Попробуйте ещё раз")
#                         }
#                     },
#                     score=score  # Прямое сохранение оценки
#                 )
#                 return assessment
#             except (ValueError, TypeError, KeyError) as e:
#                 return self._create_error_assessment(task, response, str(e))
#
#         # Если версия схемы не поддерживается
#         return self._create_error_assessment(
#             task,
#             response,
#             f"Unsupported schema version: {task.content_schema_version}"
#         )
#
#     def _assess_short_text(self, task: Task, response: StudentTaskResponse) -> Assessment:
#         """
#         Оценка кратких текстовых ответов
#         """
#         student_answer = response.response_text.strip().lower()
#         correct_answers = [ans.lower() for ans in task.content.get("correct", [])]
#         case_sensitive = task.content.get("case_sensitive", False)
#
#         if case_sensitive:
#             student_answer = response.response_text.strip()
#             correct_answers = task.content.get("correct", [])
#
#         # Простая проверка на совпадение
#         is_correct = any(self._fuzzy_match(student_answer, correct) for correct in correct_answers)
#         score = 1.0 if is_correct else 0.0
#
#         assessment = Assessment.objects.create(
#             task_response=response,
#             llm_version="auto-short-text-v1",
#             raw_output={
#                 "student_answer": student_answer,
#                 "correct_answers": correct_answers,
#                 "case_sensitive": case_sensitive
#             },
#             structured_feedback={
#                 "score": score,
#                 "is_correct": is_correct,
#                 "error_tags": [] if is_correct else ["concept_mismatch"],
#                 "feedback": {
#                     "hint": "Верный ответ!" if is_correct else "Попробуйте ещё раз"
#                 }
#             },
#             score=score  # Прямое сохранение оценки
#         )
#
#         return assessment
#
#     def _fuzzy_match(self, answer: str, correct_answer: str, threshold: float = 0.8) -> bool:
#         """
#         Простая fuzzy-проверка для неточных совпадений.
#         """
#         return answer.strip() == correct_answer.strip()
#
#     def _create_error_assessment(self, task: Task, response: StudentTaskResponse, error: str) -> Assessment:
#         """
#         Создает Assessment с информацией об ошибке обработки.
#         """
#         return Assessment.objects.create(
#             task_response=response,
#             llm_version="auto-error",
#             raw_output={"error": error},
#             structured_feedback={
#                 "score": 0.0,
#                 "is_correct": False,
#                 "error_tags": ["processing_error"],
#                 "feedback": {"error": f"Ошибка обработки: {error}"}
#             },
#             score=0.0  # Ошибка - минимальная оценка
#         )
#
#     def _create_fallback_assessment(self, task: Task, response: StudentTaskResponse) -> Assessment:
#         """
#         Заглушка для открытых форматов ответов.
#         """
#         return Assessment.objects.create(
#             task_response=response,
#             llm_version="auto-fallback",
#             raw_output={"message": "Требуется ручная оценка или интеграция с LLM"},
#             structured_feedback={
#                 "score": 0.7,
#                 "is_correct": None,
#                 "error_tags": [],
#                 "feedback": {
#                     "message": "Отличная попытка! Этот ответ будет дополнительно проверен.",
#                     "note": "Для полноценной оценки требуется интеграция с LLM"
#                 }
#             },
#             score=0.7  # Нейтральная оценка для заглушки
#         )
#
#     def _analyze_audio_with_asr(self, audio_file):
#         """
#         Интеграция с ASR сервисом
#         """
#         try:
#             result = self.speech_to_text_service.transcribe(audio_file)
#             return {
#                 'transcript': result.get('text', ''),
#                 'confidence': result.get('confidence', 0.0),
#                 'duration': result.get('duration', 0.0),
#                 'word_timings': result.get('word_timings', []),
#                 'audio_quality': result.get('audio_quality', 'good')
#             }
#         except Exception as e:
#             logger.error(f"ASR transcription failed: {str(e)}")
#             return {
#                 'transcript': "",
#                 'confidence': 0.0,
#                 'duration': 0.0,
#                 'word_timings': [],
#                 'audio_quality': 'poor'
#             }
#
#     def _calculate_audio_score(self, asr_result):
#         """
#         Расчет оценки для аудио ответа на основе:
#         - уверенности ASR
#         - длины ответа
#         - качества аудио
#         """
#         confidence = asr_result.get('confidence', 0.0)
#         duration = asr_result.get('duration', 0.0)
#         audio_quality = asr_result.get('audio_quality', 'good')
#
#         # Базовая оценка на основе уверенности ASR
#         base_score = confidence
#
#         # Штраф за слишком короткие ответы (менее 3 секунд)
#         if duration < 3.0:
#             base_score *= 0.7
#
#         # Штраф за плохое качество аудио
#         if audio_quality == 'poor':
#             base_score *= 0.6
#         elif audio_quality == 'medium':
#             base_score *= 0.8
#
#         # Нормализация в диапазон 0-1
#         return max(0.0, min(1.0, base_score * 0.9 + 0.1))
#
#     def _detect_audio_errors(self, asr_result):
#         """
#         Определение типов ошибок в устной речи
#         """
#         errors = []
#         confidence = asr_result.get('confidence', 0.0)
#         audio_quality = asr_result.get('audio_quality', 'good')
#         duration = asr_result.get('duration', 0.0)
#
#         if confidence < 0.3:
#             errors.append("unclear_speech")
#         if audio_quality == 'poor':
#             errors.append("audio_quality_issues")
#         if duration < 2.0:
#             errors.append("too_short_response")
#
#         return errors
#
#     def _generate_audio_feedback(self, asr_result, score):
#         """
#         Генерация обратной связи для аудио ответа
#         """
#         confidence = asr_result.get('confidence', 0.0)
#         duration = asr_result.get('duration', 0.0)
#         transcript = asr_result.get('transcript', '')
#
#         if score >= 0.8:
#             return {
#                 "message": "Отличное произношение! Ответ был четким и понятным.",
#                 "transcript": transcript,
#                 "confidence": confidence
#             }
#         elif score >= 0.6:
#             return {
#                 "message": "Хорошая попытка! Постарайтесь говорить немного четче и громче.",
#                 "transcript": transcript,
#                 "confidence": confidence
#             }
#         else:
#             feedback = "Нужно улучшить произношение. "
#             if confidence < 0.4:
#                 feedback += "Система не смогла распознать вашу речь. Попробуйте говорить четче. "
#             if duration < 3.0:
#                 feedback += "Ваш ответ был слишком коротким. Попробуйте ответить более развернуто."
#
#             return {
#                 "message": feedback.strip(),
#                 "transcript": transcript,
#                 "confidence": confidence
#             }

import logging
import traceback
from typing import Dict

from django.conf import settings
from django.utils import timezone

from curriculum.application.ports.assessment_port import AssessmentPort
from curriculum.domain.value_objects.assessment_result import AssessmentResult
from curriculum.models.assessment.assessment import Assessment
from curriculum.models.assessment.student_response import StudentTaskResponse
from curriculum.models.content.task import Task, ResponseFormat
from curriculum.infrastructure.validation.task_schemas import TASK_CONTENT_SCHEMAS

logger = logging.getLogger(__name__)


class SchemaValidationError(Exception):
    """Исключение для ошибок валидации схемы контента задания"""
    pass


class AutoAssessorAdapter(AssessmentPort):
    """
    Адаптер для автоматической оценки закрытых заданий.
    КОРРЕКТНАЯ АРХИТЕКТУРА С ПОДДЕРЖКОЙ СХЕМ ВАЛИДАЦИИ.

    Основные принципы:
    1. Поддерживаемые форматы и схемы:
       - SINGLE_CHOICE + scq_v1
       - MULTIPLE_CHOICE + mcq_v1 (заглушка)
       - SHORT_TEXT + short_text_v1
    2. Централизованная валидация через TASK_CONTENT_SCHEMAS
    3. Четкое соответствие схемам и форматам ответов
    4. Расширяемая архитектура для новых схем

    АРХИТЕКТУРНЫЕ ИСПРАВЛЕНИЯ:
    - ИСПРАВЛЕНА номенклатура схем (scq_v1 для одиночного выбора)
    - УДАЛЕНА обработка AUDIO (требует LLMAssessor)
    - ДОБАВЛЕНА валидация типов и диапазонов
    - РЕАЛИЗОВАНА поддержка множественных правильных ответов для SHORT_TEXT
    """

    def __init__(self):
        """Инициализация без зависимостей"""
        pass

    def assess_task(self, task: Task, response: StudentTaskResponse) -> AssessmentResult:
        """
        Основной метод оценки с валидацией схемы.

        Алгоритм:
        1. Проверка соответствия формата задания и схемы
        2. Валидация контента по схеме
        3. Выбор стратегии оценки
        4. Обработка ошибок с информативными сообщениями

        Args:
            task: Задание для оценки
            response: Ответ студента

        Returns:
            Assessment: Результат оценки в правильном формате
        """
        try:
            print(f"ОБРАБОТКА ОТВЕТА 7. AutoAssessorAdapter # начало\n\n", )

            # 1. Валидация соответствия формата и схемы
            self._validate_format_schema_compatibility(task)
            print(f"ОБРАБОТКА ОТВЕТА 7. AutoAssessorAdapter # Валидация соответствия формата и схемы\n\n", )
            # 2. Валидация контента по схеме
            schema = self._get_schema_for_task(task)
            self._validate_task_content(task.content, schema)
            print(f"ОБРАБОТКА ОТВЕТА 7. AutoAssessorAdapter # Валидация контента по схеме:\n{schema}\n\n", )

            # 3. Выбор стратегии оценки
            if task.response_format == ResponseFormat.SINGLE_CHOICE:
                print(f"ОБРАБОТКА ОТВЕТА 7. AutoAssessorAdapter # Выбор стратегии оценки :\nSINGLE_CHOICE\n\n", )
                return self._assess_single_choice(task, response)
            elif task.response_format == ResponseFormat.MULTIPLE_CHOICE:
                print(f"ОБРАБОТКА ОТВЕТА 7. AutoAssessorAdapter # Выбор стратегии оценки :\nMULTIPLE_CHOICE\n\n", )
                return self._assess_multiple_choice(task, response)
            elif task.response_format == ResponseFormat.SHORT_TEXT:
                print(f"ОБРАБОТКА ОТВЕТА 7. AutoAssessorAdapter # Выбор стратегии оценки :\nSHORT_TEXT\n\n", )
                return self._assess_short_text(task, response)

        except SchemaValidationError as e:
            logger.error(f"Schema validation failed for task {task.pk}: {str(e)}")
            return self._create_schema_error_assessment(
                task, response,
                f"Schema validation error: {str(e)}",
                schema_name=task.content_schema_version
            )
        except Exception as e:
            logger.error(f"Critical error in assess_task: {str(e)}", exc_info=True)
            return self._create_critical_error_assessment(task, response, str(e))

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
                self._validate_int_field(field_value, rules, field_name)
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

    def _validate_int_field(self, value: int, rules: dict, field_name: str) -> None:
        """Валидация поля типа int"""
        # Проверка минимума
        min_value = rules.get("min")
        if min_value is not None and value < min_value:
            raise SchemaValidationError(f"Field '{field_name}' must be at least {min_value}")

        # Проверка максимума/ссылки
        reference = rules.get("reference")
        if reference:
            # Простая поддержка ссылок на длину списка
            if reference == "options.length - 1" and "options" in rules:
                max_value = len(rules["options"]) - 1
                if value > max_value:
                    raise SchemaValidationError(
                        f"Field '{field_name}' must be at most {max_value} (options length - 1)"
                    )
            elif reference == "options.length" and "options" in rules:
                max_value = len(rules["options"])
                if value > max_value:
                    raise SchemaValidationError(
                        f"Field '{field_name}' must be at most {max_value} (options length)"
                    )

    def _validate_str_field(self, value: str, rules: dict, field_name: str) -> None:
        """Валидация поля типа str"""
        min_length = rules.get("min_length")
        if min_length is not None and len(value) < min_length:
            raise SchemaValidationError(f"Field '{field_name}' must be at least {min_length} characters long")

    def _assess_single_choice(self, task: Task, response: StudentTaskResponse) -> AssessmentResult:
        """
        Оценка заданий с одиночным выбором (scq_v1).

        Логика:
        1. Парсинг числового индекса или поиск по тексту
        2. Сравнение с correct_idx
        3. Формирование структурированной обратной связи
        """
        try:
            student_choice = self._parse_student_choice_scq(response.response_text, task)
            correct_idx = task.content["correct_idx"]
            is_correct = (student_choice == correct_idx)
            score = 1.0 if is_correct else 0.0
            print(
                f"ОБРАБОТКА ОТВЕТА 7. AutoAssessorAdapter # _assess_single_choice :\n{student_choice=}\n{correct_idx=}\n{is_correct=}\n{score=}\n\n", )

            # СТРУКТУРИРОВАННАЯ ОБРАТНАЯ СВЯЗЬ
            options = task.content["options"]
            explanation = task.content.get("explanation", "Попробуйте ещё раз")  # TODO оно надо?

            structured_feedback = {
                "score_grammar": score if task.task_type == "grammar" else 0.5,
                "score_vocabulary": score if task.task_type == "vocabulary" else 0.5,
                "errors": [] if is_correct else [{
                    "type": "concept_gap",
                    "example": f"Выбран вариант: {options[student_choice]}",
                    "correction": f"Правильный вариант: {options[correct_idx]}"
                }],
                "strengths": ["Правильный выбор варианта"] if is_correct else [],
                "suggestions": [] if is_correct else [explanation],
                "metadata": {
                    "overall_score": score,
                    "is_correct": is_correct,
                    "student_choice": student_choice,
                    "correct_idx": correct_idx,
                    "schema_version": task.content_schema_version
                }
            }
            assessment_data = {
                "llm_version": "auto-scq-v1",
                "raw_output": {
                    "student_input": response.response_text,
                    "student_idx": student_choice,
                    "correct_idx": correct_idx,
                    "task_content": task.content
                },
                "structured_feedback": structured_feedback
            }

            assessment_result = AssessmentResult(
                score=score,
                is_correct=is_correct,
                metadata=assessment_data
            )

            print(
                f"ОБРАБОТКА ОТВЕТА 7. AutoAssessorAdapter # AssessmentResult:\n{assessment_result=}\n\n", )
            return assessment_result

        except (ValueError, TypeError, KeyError) as e:
            logger.error(f"Single choice Task processing error: {str(e)}")
            assessment_result = AssessmentResult(
                score=0.5,
            )
            return assessment_result

    def _parse_student_choice_scq(self, response_text: str, task: Task) -> int:
        """
        Парсинг ответа для одиночного выбора.
        Поддерживает:
        - Числовые индексы (0, 1, 2...)
        - Точный текст варианта
        """
        response_text = response_text.strip()

        # 1. Попытка преобразовать в число
        if response_text.isdigit():
            choice_idx = int(response_text)
            if 0 <= choice_idx < len(task.content["options"]):
                return choice_idx

        # 2. Поиск по тексту варианта (регистронезависимый)
        student_text = response_text.lower()
        options = task.content["options"]

        for idx, option in enumerate(options):
            if student_text == option.lower().strip():
                return idx

        # 3. Частичное совпадение (только для отладки)
        for idx, option in enumerate(options):
            if student_text in option.lower():
                logger.debug(f"Partial match found: '{student_text}' in '{option}'")
                return idx

        raise ValueError(f"Invalid choice: '{response_text}' not found in options")

    def _assess_multiple_choice(self, task: Task, response: StudentTaskResponse) -> Assessment:
        """
        Оценка заданий с множественным выбором (mcq_v1).
        ТЕКУЩАЯ РЕАЛИЗАЦИЯ - ЗАГЛУШКА.

        В будущем будет реализовано сравнение списков индексов.
        """
        logger.warning(f"MULTIPLE_CHOICE task {task.pk} processed with stub. Full support coming soon.")

        return Assessment.objects.create(
            task_response=response,
            llm_version="auto-mcq-v1-stub",
            raw_output={"warning": "MULTIPLE_CHOICE not fully implemented in AutoAssessor"},
            structured_feedback={
                "score_grammar": 0.5,
                "score_vocabulary": 0.5,
                "errors": [{
                    "type": "feature_limitation",
                    "example": "MULTIPLE_CHOICE format",
                    "correction": "Полная поддержка будет добавлена в будущих версиях"
                }],
                "strengths": [],
                "suggestions": [
                    "Система пока не поддерживает множественный выбор с автоматической оценкой. "
                    "Используйте одиночный выбор или запросите ручную оценку."
                ],
                "metadata": {
                    "overall_score": 0.5,
                    "is_correct": None,
                    "feature_status": "planned",
                    "recommendation": "use_single_choice_or_llm"
                }
            }
        )

    def _assess_short_text(self, task: Task, response: StudentTaskResponse) -> Assessment:
        """
        Оценка кратких текстовых ответов (short_text_v1).

        Поддерживает:
        - Регистрозависимую/независимую проверку
        - Множественные правильные ответы
        - Ограничения по длине
        """
        content = task.content
        student_answer = response.response_text.strip()

        # 1. Валидация длины ответа
        min_length = content.get("min_length", 1)
        max_length = content.get("max_length", 100)

        if len(student_answer) < min_length:
            return self._create_error_assessment(
                task, response,
                f"Answer too short. Minimum {min_length} characters required."
            )
        if len(student_answer) > max_length:
            return self._create_error_assessment(
                task, response,
                f"Answer too long. Maximum {max_length} characters allowed."
            )

        # 2. Проверка правильных ответов
        correct_answers = content.get("correct_answers", [])
        case_sensitive = content.get("case_sensitive", False)

        if not correct_answers:
            # Если нет правильных ответов - считаем все ответы верными
            logger.warning(f"Task {task.pk} has no correct_answers defined. All responses will be accepted.")
            is_correct = True
            score = 1.0
        else:
            if case_sensitive:
                is_correct = student_answer in correct_answers
            else:
                student_lower = student_answer.lower()
                correct_lower = [ans.lower() for ans in correct_answers]
                is_correct = student_lower in correct_lower

            score = 1.0 if is_correct else 0.0

        # 3. Формирование обратной связи
        structured_feedback = {
            "score_grammar": 0.5,  # SHORT_TEXT не оценивает grammar напрямую
            "score_vocabulary": score if task.task_type == "vocabulary" else 0.5,
            "errors": [] if is_correct else [{
                "type": "spelling" if case_sensitive else "concept_mismatch",
                "example": student_answer,
                "correction": correct_answers[0] if correct_answers else "правильный ответ"
            }],
            "strengths": ["Точный ответ"] if is_correct else [],
            "suggestions": ["Отлично!"] if is_correct else ["Проверьте правильность написания"],
            "metadata": {
                "overall_score": score,
                "is_correct": is_correct,
                "case_sensitive": case_sensitive,
                "answer_length": len(student_answer),
                "schema_version": task.content_schema_version
            }
        }

        return Assessment.objects.create(
            task_response=response,
            llm_version="auto-short-text-v1",
            raw_output={
                "student_input": student_answer,
                "correct_answers": correct_answers,
                "case_sensitive": case_sensitive,
                "answer_length": len(student_answer)
            },
            structured_feedback=structured_feedback
        )

    @staticmethod
    def _create_error_assessment(task: Task, response: StudentTaskResponse, error: str) -> Assessment:
        """Создает Assessment для обработки ошибок"""
        assessment, created = Assessment.objects.get_or_create(
            task_response=response,
            default={
                "llm_version": "auto-error",
                "raw_output": {"error": error, "task_id": task.pk},
                "structured_feedback": {
                    "score_grammar": 0.5,
                    "score_vocabulary": 0.5,
                    "errors": [{
                        "type": "processing_error",
                        "example": error,
                        "correction": "Ответ будет проверен преподавателем"
                    }],
                    "strengths": [],
                    "suggestions": ["Произошла техническая ошибка. Ваш ответ сохранен и будет проверен вручную."],
                    "metadata": {
                        "overall_score": 0.5,
                        "status": "requires_manual_review"
                    }
                }
            }

        )
        return assessment

    def _create_schema_error_assessment(
            self,
            task: Task,
            response: StudentTaskResponse,
            error: str,
            schema_name: str = None
    ) -> Assessment:
        """
        Создает Assessment для ошибок валидации схемы.

        Args:
            task: Задание с некорректной схемой
            response: Ответ студента
            error: Описание ошибки валидации
            schema_name: Имя схемы (опционально)

        Returns:
            Assessment: Результат с информацией об ошибке схемы
        """
        # Формируем детальное сообщение об ошибке
        error_details = {
            "validation_error": error,
            "task_id": task.pk,
            "schema_name": schema_name or task.content_schema_version,
            "submitted_schema_version": task.content_schema_version,
            "content_keys": list(task.content.keys()) if task.content else [],
            "timestamp": timezone.now().isoformat()
        }

        return Assessment.objects.create(
            task_response=response,
            llm_version="schema-error",
            raw_output=error_details,
            structured_feedback={
                "score_grammar": 0.5,
                "score_vocabulary": 0.5,
                "errors": [{
                    "type": "invalid_task_schema",
                    "example": f"Схема '{schema_name or task.content_schema_version}' не прошла валидацию",
                    "correction": "Задание содержит ошибку в конфигурации. Преподаватель будет уведомлен."
                }],
                "strengths": [],
                "suggestions": [
                    "Это задание содержит техническую ошибку и не может быть оценено автоматически.",
                    "Ваш ответ был сохранен и будет проверен преподавателем вручную.",
                    "Прогресс в обучении не будет потерян."
                ],
                "metadata": {
                    "overall_score": 0.5,
                    "schema_status": "invalid",
                    "schema_name": schema_name or task.content_schema_version,
                    "requires_manual_review": True,
                    "error_type": "schema_validation",
                    "admin_notification_sent": True
                }
            }
        )

    def _create_critical_error_assessment(
            self,
            task: Task,
            response: StudentTaskResponse,
            error: str
    ) -> Assessment:
        """
        Создает Assessment для критических ошибок системы.

        Используется для обработки непредвиденных исключений, которые
        могут нарушить учебный процесс. Обеспечивает graceful degradation.

        Args:
            task: Задание, при обработке которого произошла ошибка
            response: Ответ студента
            error: Описание критической ошибки

        Returns:
            Assessment: Результат с информацией о системном сбое
        """
        # Детальное логирование для администраторов
        admin_alert = {
            "critical_error": error,
            "task_id": task.pk,
            "student_id": response.student.id if response.student else None,
            "task_type": task.task_type,
            "response_format": task.response_format,
            "schema_version": task.content_schema_version,
            "timestamp": timezone.now().isoformat(),
            "traceback": traceback.format_exc() if settings.DEBUG else None
        }

        # Безопасное создание Assessment (обработка возможных ошибок)
        try:
            return Assessment.objects.create(
                task_response=response,
                llm_version="critical-error",
                raw_output=admin_alert,
                structured_feedback={
                    "score_grammar": 0.5,
                    "score_vocabulary": 0.5,
                    "errors": [{
                        "type": "system_failure",
                        "example": "Системная ошибка при обработке задания",
                        "correction": "Техническая поддержка уже работает над решением проблемы"
                    }],
                    "strengths": [],
                    "suggestions": [
                        "К сожалению, произошла временная техническая проблема.",
                        "Ваш ответ был сохранен и будет обработан автоматически позже.",
                        "Вы можете продолжить обучение с следующего задания.",
                        "Если проблема сохраняется, обратитесь в поддержку."
                    ],
                    "metadata": {
                        "overall_score": 0.0,
                        "status": "system_down",
                        "retry_after": "5 minutes",
                        "requires_manual_intervention": True,
                        "admin_notified": True,
                        "error_severity": "critical",
                        "fallback_applied": True
                    }
                }
            )
        except Exception as db_error:
            # Крайний случай: даже создание Assessment не удалось
            logger.critical(
                f"CRITICAL FAILURE: Could not create error assessment. Original error: {error}, DB error: {str(db_error)}")

            # Попытка минимального сохранения
            try:
                return Assessment.objects.create(
                    task_response=response,
                    llm_version="fallback-critical",
                    raw_output={"emergency_fallback": True, "original_error": str(error)},
                    structured_feedback={
                        "score_grammar": 0.5,
                        "score_vocabulary": 0.5,
                        "errors": [{"type": "emergency_fallback", "example": "System emergency",
                                    "correction": "Admin intervention required"}],
                        "strengths": [],
                        "suggestions": ["Система восстановлена в аварийном режиме. Обратитесь в поддержку."],
                        "metadata": {
                            "overall_score": 0.0,
                            "status": "emergency_fallback",
                            "admin_notified": False
                        }
                    }
                )
            except Exception as final_error:
                logger.critical(f"ABSOLUTE FAILURE: Could not create fallback assessment. Error: {str(final_error)}")
                raise RuntimeError("System in unrecoverable state") from final_error
