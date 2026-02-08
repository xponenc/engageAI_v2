import json
import os
import time

from celery_progress.backend import ProgressRecorder

import requests
from asgiref.sync import async_to_sync
from celery import shared_task, chain, group
from celery.exceptions import SoftTimeLimitExceeded
import logging

from django.db import IntegrityError
from django.utils import timezone

from ai.llm_service.factory import llm_factory
from curriculum.models.assessment.lesson_assesment import LessonAssessmentResult, AssessmentStatus
from curriculum.models.assessment.task_assessment import TaskAssessmentResult
from curriculum.models.content.lesson import Lesson
from curriculum.models.learning_process.lesson_event_log import LessonEventType
from curriculum.models.student.enrollment import Enrollment
from curriculum.models.student.skill_snapshot import SkillSnapshot
from curriculum.models.student.student_response import StudentTaskResponse
from curriculum.services.auto_assessment_adapter import AutoAssessorAdapter
from curriculum.services.learning_objective_evaluation import LearningObjectiveEvaluationService
from curriculum.services.learning_path_adaptation import LearningPathAdaptationService, LessonOutcomeContext, \
    LearningPathAdjustmentType
from curriculum.services.lesson_event_service import LessonEventService
from curriculum.services.llm_assessment_adapter import LLMAssessmentAdapter
from curriculum.services.skill_update_service import SkillUpdateService
from llm_logger.models import LLMRequestType

logger = logging.getLogger(__name__)


@shared_task
def transcribe_response(self, response_id: int) -> int:
    """
    Транскрибирует один StudentTaskResponse с аудио.
    Возвращает ID ответа (для совместимости с group).
    """

    try:
        response = StudentTaskResponse.objects.get(id=response_id)

        if not response.audio_file or response.transcript:
            return response_id  # уже есть транскрипт или нет аудио

        # Открываем файл
        audio_content = response.audio_file.read()

        # Определяем MIME
        ext = os.path.splitext(response.audio_file.name)[1].lower()
        mime_map = {
            '.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4',
            '.ogg': 'audio/ogg', '.flac': 'audio/flac', '.webm': 'audio/webm'
        }
        content_type = mime_map.get(ext, 'audio/wav')

        files = {
            'file': (os.path.basename(response.audio_file.name), audio_content, content_type)
        }
        data = {
            'model': 'whisper-1',
            'language': 'en',  # или динамически определяйте, если нужно
            'response_format': 'text'
        }

        whisper_response = requests.post(
            "http://localhost:8000/v1/audio/transcriptions",  # или через env переменную
            files=files,
            data=data,
            timeout=120
        )

        if whisper_response.status_code == 200:
            response.transcript = whisper_response.text.strip()
        else:
            response.transcript = "[Ошибка транскрипции]"
            logger.error(f"Whisper error {whisper_response.status_code}: {whisper_response.text}")

        response.save(update_fields=['transcript'])
        logger.info(f"Transcribed response {response_id}")

        return response_id

    except Exception as e:
        logger.error(f"Error transcribing response {response_id}: {str(e)}", exc_info=True)
        # Даже при ошибке сохраняем метку, чтобы не блокировать оценку
        try:
            resp = StudentTaskResponse.objects.get(id=response_id)
            resp.transcript = "[Ошибка транскрипции]"
            resp.save(update_fields=['transcript'])
        except:
            pass
        return response_id


@shared_task
def launch_full_assessment(enrollment_id: int):
    """
    Оркестратор: запускает транскрипцию (если нужно) → затем основную оценку.
    """
    try:
        enrollment = Enrollment.objects.get(id=enrollment_id)

        # Находим ответы с аудио, у которых ещё нет транскрипта
        responses_needing_transcription = StudentTaskResponse.objects.filter(
            student=enrollment.student,
            task__lesson=enrollment.current_lesson,
            audio_file__isnull=False,
            transcript__in=['', None]
        ).values_list('id', flat=True)

        response_ids = list(responses_needing_transcription)

        if response_ids:
            logger.info(f"Need to transcribe {len(response_ids)} audio responses before assessment")

            # Параллельно транскрибируем все аудио
            transcription_job = group(transcribe_response.s(resp_id) for resp_id in response_ids)

            # После завершения всех — запускаем оценку
            workflow = chain(
                transcription_job,
                assess_lesson_tasks.s(enrollment_id)  # передаём enrollment_id дальше
            )
        else:
            logger.info("No audio to transcribe — starting assessment directly")
            workflow = assess_lesson_tasks.s(enrollment_id)

        result = workflow.apply_async()
        return result.id

    except Exception as e:
        logger.error(f"Error launching full assessment: {str(e)}", exc_info=True)
        return None


@shared_task(bind=True, soft_time_limit=600, time_limit=720)
def assess_lesson_tasks(self, enrollment_id, assessed_lesson_id):
    """
    Полная асинхронная оценка урока.
    1. Находит текущий урок по LearningPath
    2. Оценивает каждое задание (auto или LLM)
    3. Сохраняет результаты в TaskAssessmentResult
    4. Считает общий score и итоговое резюме LLM
    5. Сохраняет в LessonAssessmentResult
    6. Создаёт событие ASSESSMENT_COMPLETE
    7. Запускает DecisionService для адаптации
    8. Переходит к следующему узлу (если нет remedial)
    """
    progress_recorder = ProgressRecorder(self)
    current_assessment = 0

    enrollment = Enrollment.objects.select_related('student', 'course', 'learning_path').get(id=enrollment_id)

    # Обновление статуса узла в LearningPath
    current_node = enrollment.learning_path.current_node

    learning_path = enrollment.learning_path
    current_index = learning_path.current_node_index
    learning_path.nodes[current_index]["submitted_at"] = timezone.now().isoformat()
    learning_path.save(update_fields=["nodes"])

    lesson = Lesson.objects.get(id=assessed_lesson_id)

    try:
        logger.debug(f"Оценка урока {lesson.title} ({assessed_lesson_id}) для enrollment {enrollment_id}")

        # Все ответы по этому уроку
        responses = StudentTaskResponse.objects.filter(
            enrollment=enrollment,
            task__lesson=lesson
        ).select_related(
            'task', 'task__lesson__course', 'student__user',
        ).prefetch_related(
            'assessment'
        )

        if not responses:
            raise ValueError("Нет ответов для оценки")

        total_tasks = len(responses)

        auto_adapter = AutoAssessorAdapter()
        llm_adapter = LLMAssessmentAdapter()

        task_count = responses.count()
        task_assessments = []

        for i, resp in enumerate(responses, start=1):
            task = resp.task
            if not hasattr(resp, "assessment"):
                # Пропуск уже оцененных задач уже отвеченных задач
                # для варианта одна задача - один ответ

                if task.response_format in AutoAssessorAdapter.SUPPORTED_FORMATS:
                    result = auto_adapter.assess_task(task, resp)
                else:
                    result = llm_adapter.assess_task(task, resp)

                score = TaskAssessmentResult.calc_task_score(result=result)
                task_assessment = TaskAssessmentResult.objects.create(
                    enrollment=enrollment,
                    task=task,
                    response=resp,
                    is_correct=result.is_correct,
                    score=score,
                    feedback=result.summary.get("text", ""),
                    structured_feedback={
                        "skill_evaluation": result.skill_evaluation,
                        "summary": result.summary,
                        "error_tags": result.error_tags,
                        "metadata": result.metadata,
                    },
                )

                task_assessments.append(task_assessment)

                # Логируем оценку задания
                LessonEventService.create_event(
                    student=enrollment.student,
                    enrollment=enrollment,
                    lesson=lesson,
                    event_type=LessonEventType.TASK_ASSESSMENT_COMPLETE,
                    channel="WEB",
                    metadata={
                        "node_id": current_node["node_id"],
                        "path_type": enrollment.learning_path.path_type,
                        "task_id": task.id,
                        "task_assessment_id": task_assessment.id,
                        "reason": current_node.get("reason", ""),
                        "type": current_node.get("type", "core")
                    }
                )
            current_assessment += 1
            progress_recorder.set_progress(
                i,
                total_tasks,
                description=f"Оценено {i}/{total_tasks} заданий"
            )

        progress_recorder.set_progress(
            1,
            2,
            description=f"Оценивается урок"
        )
        # перезагрузка с оценками
        responses = StudentTaskResponse.objects.filter(
            enrollment=enrollment,
            task__lesson=lesson
        ).select_related(
            'task', 'task__lesson__course', 'student__user',
        ).prefetch_related(
            'assessment'
        )

        try:
            lesson_result = LessonAssessmentResult.objects.create(
                enrollment=enrollment,
                lesson=lesson,
                status=AssessmentStatus.PROCESSING,
            )
        except IntegrityError as e:
            LessonEventService.create_event(
                student=enrollment.student,
                enrollment=enrollment,
                lesson=lesson,
                event_type=LessonEventType.ASSESSMENT_ERROR,
                channel="WEB",
                metadata={
                    "error": str(e),
                    "node_id": current_node["node_id"],
                }
            )
            return "Урок уже проходил оценку"

        user_message = f"Дайте экспертную оценку по уроку.\nУровень CEFR ученика {enrollment.student.english_level}\n"
        for response in responses:
            task = response.task
            assessment = getattr(response, "assessment")
            skill_evaluation = assessment.structured_feedback.get("skill_evaluation", {})

            filtered_skills = {
                skill: data
                for skill, data in skill_evaluation.items()
                if data.get("score") is not None
            }

            assessment_skills = json.dumps(
                filtered_skills,
                indent=2,
                ensure_ascii=False
            )
            user_message += f"""
Задание:
 - № {task.order}
 - Контекст: 
{json.dumps(task.content, indent=2, ensure_ascii=False)}

 - Ответ ученика:
{response.response_text or responses.transcript}

 - Оценка ответа:
    is correct: {assessment.is_correct}
    Отзыв: {assessment.feedback} 
    Оценка skills: {assessment_skills}
    Оценка за урок(агрегированная): {assessment.score}
             """

        # Итоговое резюме LLM по уроку
        system_prompt = f"""
Вы — эксперт по оценке английского языка по шкале CEFR. Оцените ответ студента результат студента о прохождении урока
 и усвоении знаний по результатам тестовых заданий. В ответе укажите краткое мотивирующие резюме по результатам урока
  (2–3 предложения) и 2–3 конкретные рекомендации по улучшению.
 
 Ответ дайте в формате JSON:
 {{
 "resume": str,
 "recommendations": str,
 }}
        """

        context = {
            "course_id": enrollment.course.pk,
            "lesson_id": lesson.pk,
            "user_id": enrollment.student.user.id,
            "request_type": LLMRequestType.LESSON_REVIEW,
        }
        # TODO более изящный вызов фабрики
        result = async_to_sync(llm_factory.generate_json_response)(
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=0.1,
            context=context
        )

        if result.error:
            logger.error(f"LLM error: {result.error}", extra={"raw_response": result.raw_provider_response})
            raise ValueError(f"LLM generation failed: {result.error}")

        summary_response = result.response.message
        if not isinstance(summary_response, dict):
            raise ValueError(f"Invalid LLM response format: expected {dict}, got {type(summary_response).__name__}")

        # Агрегация skills по результатам урока
        lesson_skill_feedback = LessonAssessmentResult.aggregate_skill_feedback(task_assessments)

        # Агрегированная оценка урока
        overall_score = LessonAssessmentResult.calculate_overall_score(task_assessments, strategy="hybrid")

        lesson_result.overall_score = overall_score
        lesson_result.structured_feedback = {
            "llm_result": summary_response,
            "overall": overall_score,
            "skills": lesson_skill_feedback,
        }

        lesson_result.llm_summary = summary_response.get("resume", "")
        lesson_result.llm_recommendations = (summary_response.get("recommendations", ""))
        lesson_result.status = AssessmentStatus.COMPLETED
        lesson_result.completed_at = timezone.now()
        lesson_result.save()

        # Создаём событие завершения оценки
        LessonEventService.create_event(
            student=enrollment.student,
            enrollment=enrollment,
            lesson=lesson,
            event_type=LessonEventType.ASSESSMENT_COMPLETE,
            channel="SYSTEM",
            metadata={
                # "node_id": current_node["node_id"],
                "lesson_id": assessed_lesson_id,
                "tasks_evaluated": task_count,
                "job_id": self.request.id
            }
        )

        # ======================
        # 5. Создаем снимок навыков
        # ======================
        pre_snapshot = SkillSnapshot.objects.filter(
            enrollment=enrollment,
            snapshot_context__in=["POST_LESSON", "PLACEMENT"],
        ).order_by("-snapshot_at").first()

        # Рассчитываем новые значения навыков
        new_skill_values = SkillUpdateService.calculate_skill_deltas(
            pre_snapshot=pre_snapshot,
            lesson_feedback=lesson_skill_feedback
        )

        # Создаем новый снимок
        skill_snapshot = SkillSnapshot.objects.create(
            student=enrollment.student,
            enrollment=enrollment,
            associated_lesson=lesson,
            snapshot_context="POST_LESSON",
            grammar=new_skill_values["grammar"],
            vocabulary=new_skill_values["vocabulary"],
            listening=new_skill_values["listening"],
            reading=new_skill_values["reading"],
            writing=new_skill_values["writing"],
            speaking=new_skill_values["speaking"],
            skills=new_skill_values,  # Для удобства в JSON
            metadata={
                "source": "lesson_assessment",
                "lesson_id": lesson.id,
                "lesson_score": overall_score,
                "tasks_completed": len(task_assessments),
                "skill_feedback": lesson_skill_feedback
            }
        )

        # Логируем завершение оценки урока
        LessonEventService.create_event(
            student=enrollment.student,
            enrollment=enrollment,
            lesson=lesson,
            event_type=LessonEventType.ASSESSMENT_COMPLETE,
            channel="WEB",
            metadata={
                "node_id": current_node["node_id"],
                "path_type": enrollment.learning_path.path_type,
                "reason": current_node.get("reason", ""),
                "type": current_node.get("type", "core"),
                "lesson_score": lesson_result.overall_score,
            }
        )

        # ======================
        # 6. Создаем дельту навыков (опционально)
        # ======================
        # if pre_snapshot:
        #     deltas = {
        #         skill: new_skill_values[skill] - getattr(pre_snapshot, skill, 0.0)
        #         for skill in list(SkillDomain.values())
        #     }
        #     deltas["overall"] = sum(deltas.values()) / len(deltas)
        #
        #     SkillDelta.objects.create(
        #         student=enrollment.student,
        #         enrollment=enrollment,
        #         lesson=lesson,
        #         pre_snapshot=pre_snapshot,
        #         post_snapshot=skill_snapshot,
        #         deltas=deltas,
        #         metadata={"source": "auto"}
        #     )

        # Адаптация учебного плана
        #
        # task_assessments = TaskAssessmentResult.objects.filter(  # TODO Не лишний ли запрос?
        #     enrollment=enrollment,
        #     task__lesson=lesson
        # ).select_related("task")
        #
        # task_evaluation_payload = []
        #
        # for ta in task_assessments:
        #     task_evaluation_payload.append({
        #         "learning_objectives": ta.task.learning_objectives.all(),
        #         # ← список identifier'ов LO
        #         "skill_evaluation": ta.structured_feedback,
        #     })
        #
        # lo_evaluations = LearningObjectiveEvaluationService.evaluate(
        #     task_evaluation_payload
        # )
        #
        # outcome = LessonOutcomeContext(
        #     lesson_id=lesson.id,
        #     objective_scores={
        #         lo_id: eval.avg_score
        #         for lo_id, eval in lo_evaluations.items()
        #     },
        #     objective_attempts={
        #         lo_id: eval.attempts
        #         for lo_id, eval in lo_evaluations.items()
        #     },
        #     completed_at=lesson_result.completed_at,
        # )
        # print("OUTCOME")
        # print(outcome.__dict__)
        #
        # adjustment = LearningPathAdaptationService().adapt_after_lesson(
        #     learning_path=enrollment.learning_path,
        #     outcome=outcome
        # )

        # task_assessments = TaskAssessmentResult.objects.filter(
        #     enrollment=enrollment,
        #     task__lesson=lesson
        # ).select_related("task").prefetch_related("task__learning_objectives")

        task_evaluation_payload = []

        for response in responses:
            task = response.task
            task_assessment = getattr(response, "assessment")
            print("Task", task)
            # Правильно: получаем СПИСОК идентификаторов
            lo_identifiers = list(
                task.learning_objectives.all().values_list('identifier', flat=True)
            )
            print("lo_identifiers", lo_identifiers)

            # Отладка: логируем данные для диагностики
            logger.debug(
                f"Task {task.id} LOs: {lo_identifiers}, "
                f"skill_eval: {list(task_assessment.structured_feedback.get("skill_evaluation", {}).keys())}"
            )

            task_evaluation_payload.append({
                "learning_objectives": lo_identifiers,  # ← Список строк!
                "skill_evaluation": task_assessment.structured_feedback.get("skill_evaluation"),
            })

        # Проверка: есть ли данные для оценки?
        if not task_evaluation_payload:
            logger.warning(
                f"No task evaluation payload for lesson {lesson.id}. "
                f"Check if tasks have learning objectives assigned."
            )
            # Можно пропустить адаптацию или использовать fallback-логику
            lo_evaluations = {}
        else:
            lo_evaluations = LearningObjectiveEvaluationService.evaluate(
                task_evaluation_payload
            )
            logger.info(f"LO evaluations: {lo_evaluations}")

        # ======================
        # 6. Создание контекста результата урока
        # ======================
        outcome = LessonOutcomeContext(
            lesson_id=lesson.id,
            objective_scores={
                lo_id: eval.avg_score
                for lo_id, eval in lo_evaluations.items()
                if eval.avg_score is not None  # Защита от None
            },
            objective_attempts={
                lo_id: eval.attempts
                for lo_id, eval in lo_evaluations.items()
                if eval.attempts is not None
            },
            completed_at=lesson_result.completed_at,
        )

        logger.info(f"Outcome created: {outcome.__dict__}")

        # ======================
        # 7. Адаптация учебного пути
        # ======================
        adjustment = LearningPathAdaptationService().adapt_after_lesson(
            learning_path=enrollment.learning_path,
            outcome=outcome
        )
        # Результат
        # LearningPathAdjustmentType.ADVANCE
        # LearningPathAdjustmentType.INSERT_REMEDIAL
        # LearningPathAdjustmentType.REWIND_LEVEL
        # LearningPathAdjustmentType.HOLD

        LessonEventService.create_event(
            student=enrollment.student,
            enrollment=enrollment,
            lesson=lesson,
            event_type=LessonEventType.LEARNING_PATH_ADJUSTED,
            channel="SYSTEM",
            metadata={
                "adjustment": adjustment.value,
                "lesson_id": lesson.id,
            }
        )

        if adjustment == LearningPathAdjustmentType.ADVANCE:  # TODO логирование остальных вариантов
            # Логирование события завершения
            LessonEventService.create_event(
                student=enrollment.student,
                enrollment=enrollment,
                lesson=lesson,
                event_type=LessonEventType.COMPLETE,
                channel="WEB",
                metadata={
                    "node_id": current_node["node_id"],
                    "tasks_completed": len(responses),
                    "pending_assessment": True,
                    "submitted_at": timezone.now().isoformat(),
                    "lesson_score": lesson_result.overall_score,
                    "learning_path_adjustment": adjustment.value,
                }
            )

        enrollment.lesson_status = 'ACTIVE'
        enrollment.save(update_fields=['lesson_status'])

        progress_recorder.set_progress(
            2,
            2,
            description=f"Оценивается урок"
        )

        logger.info(f"Оценка завершена для enrollment {enrollment_id}")
        return "Оценка завершена"

    except Exception as e:
        logger.error(f"Ошибка оценки {enrollment_id}: {str(e)}", exc_info=True)
        enrollment.lesson_status = 'ASSESSMENT_ERROR'
        enrollment.save(update_fields=['lesson_status'])

        # Логируем ошибку оценки
        LessonEventService.create_event(
            student=enrollment.student,
            enrollment=enrollment,
            lesson=lesson,
            event_type=LessonEventType.ASSESSMENT_ERROR,
            channel="SYSTEM",
            metadata={
                "error": str(e),
                "node_id": current_node["node_id"],
                "path_type": enrollment.learning_path.path_type,
                "reason": current_node.get("reason", ""),
                "type": current_node.get("type", "core"),
            }
        )
        # raise self.retry(exc=e, countdown=60)  # retry 1 раз через минуту
        return None


def _handle_assessment_error(enrollment_id, error_message):
    """Обрабатывает ошибки в задаче оценки"""
    try:
        from curriculum.models.student.enrollment import Enrollment
        from django.utils import timezone

        enrollment = Enrollment.objects.get(id=enrollment_id)
        enrollment.lesson_status = 'ASSESSMENT_ERROR'
        enrollment.save(update_fields=['lesson_status'])

        # Логируем ошибку (без использования несуществующей модели ErrorLog)
        logger.error(
            f"Assessment error for enrollment {enrollment_id}: {error_message}",
            extra={
                'enrollment_id': enrollment_id,
                'student_id': enrollment.student.id,
                'lesson_id': enrollment.current_lesson.id if enrollment.current_lesson else None,
                'error_type': 'ASSESSMENT_ERROR',
                'timestamp': timezone.now().isoformat()
            }
        )

    except Exception as recovery_error:
        logger.critical(f"Failed to handle assessment error: {str(recovery_error)}", exc_info=True)
