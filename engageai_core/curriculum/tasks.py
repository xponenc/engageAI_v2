import json
import os
import time

from celery_progress.backend import ProgressRecorder

import requests
from asgiref.sync import async_to_sync
from celery import shared_task, chain, group
from celery.exceptions import SoftTimeLimitExceeded
import logging

from django.utils import timezone

from ai.llm_service.factory import llm_factory
from curriculum.models.assessment.lesson_assesment import LessonAssessmentResult, AssessmentStatus
from curriculum.models.assessment.task_assessment import TaskAssessmentResult
from curriculum.models.content.lesson import Lesson
from curriculum.models.content.task import Task
from curriculum.models.learning_process.lesson_event_log import LessonEventType
from curriculum.models.student.enrollment import Enrollment
from curriculum.models.student.student_response import StudentTaskResponse
from curriculum.services.auto_assessment_adapter import AutoAssessorAdapter
from curriculum.services.decision_service import DecisionService
from curriculum.services.lesson_event_service import LessonEventService
from curriculum.services.llm_assessment_adapter import LLMAssessmentAdapter
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


    enrollment = Enrollment.objects.select_related('student', 'course').get(id=enrollment_id)

    lesson = Lesson.objects.get(id=assessed_lesson_id)
    try:
        logger.info(f"Оценка урока {lesson.title} ({assessed_lesson_id}) для enrollment {enrollment_id}")

        # Все ответы по этому уроку
        responses = StudentTaskResponse.objects.filter(
            enrollment=enrollment,
            task__lesson=lesson
        ).select_related(
            'task', 'task__lesson__course', 'student__user',
        ).prefetch_related(
            'assessment'
        )
        print(f"{responses=}")

        if not responses:
            raise ValueError("Нет ответов для оценки")

        total_assessment_counter = len(responses) + 1
        progress_recorder.set_progress(
            current_assessment,
            total_assessment_counter,
            description=f"Обработано {current_assessment}/{total_assessment_counter} оценок"
        )

        auto_adapter = AutoAssessorAdapter()
        llm_adapter = LLMAssessmentAdapter()

        task_count = responses.count()
        task_assessments = []

        for resp in responses:
            task = resp.task
            # TODO проверка уже отвеченных задач
            if task.response_format in AutoAssessorAdapter.SUPPORTED_FORMATS:
                result = auto_adapter.assess_task(task, resp)
            else:
                result = llm_adapter.assess_task(task, resp)
            print(task)
            print(resp)
            print(result)
            # Сохраняем результат оценки задания
            task_assessment = TaskAssessmentResult.objects.create(
                enrollment=enrollment,
                task=task,
                response=resp,
                score=result.skill_evaluation.get(task.task_type, {}).get("score"),
                feedback=result.summary.get("text", ""),
                structured_feedback=result.skill_evaluation,
                # is_correct=result.skill_evaluation.get(task.task_type, {}).get("score", 0) >= 0.8
                is_correct=result.is_correct
            )
            task_assessments.append(task_assessment)
            current_assessment += 1
            progress_recorder.set_progress(
                current_assessment,
                total_assessment_counter,
                description=f"Обработано {current_assessment - 1}/{total_assessment_counter} задач"
            )
            time.sleep(60)

        current_assessment += 1
        progress_recorder.set_progress(
            current_assessment,
            total_assessment_counter,
            description=f"Оценивается урок"
        )
        time.sleep(60)

        lesson_result = LessonAssessmentResult.objects.create(
            enrollment=enrollment,
            lesson=lesson,
            status=AssessmentStatus.PROCESSING,
        )
        user_message = f"Дайте экспертную оценку по уроку.\nУровень CEFR ученика {enrollment.student.english_level}\n"
        for response in responses:
            task = response.task
            assessment = response.assessment
            user_message += f"""
Задание:
 - № {task.order}
 - Контекст: 
{json.dumps(task.content, indent=2, ensure_ascii=False)}

 - Ответ ученика:
{response.response_text or responses.transcript}

 - Оценка:
    Правильность: {assessment.is_correct}
    Отзыв {assessment.feedback} 
    Оценка skills: {json.dumps(assessment.structured_feedback, indent=2, ensure_ascii=False)}
             """

        # Итоговое резюме LLM по уроку
        system_prompt = f"""
Вы — эксперт по оценке английского языка по шкале CEFR. Оцените ответ студента результат студента о прохождении урока
 и усвоении знаний по результатам тестовых заданий. В ответе укажите краткое резюме по результатам урока (2–3 предложения), 
 2–3 конкретные рекомендации по улучшению и рекомендацию по учебному плану: повторить урок/следующий урок.
 
 Ответ дайте в формате JSON:
 {{
 "resume": "краткое резюме по результатам урока",
 "recommendations": "рекомендации по улучшению",
 "learning_plan": "рекомендация по учебному плану",
 }}
        """
        print(system_prompt)
        print(user_message)

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

        lesson_result.llm_summary = summary_response.get("resume", "")
        lesson_result.llm_recommendations = (summary_response.get("recommendations", ""))
        lesson_result.status = AssessmentStatus.COMPLETED.value,
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

        # Обновляем узел пути
        path = enrollment.learning_path
        current_index = path.current_node_index
        print(f"{current_index=}")
        print(f"{path.nodes[current_index]=}")
        path.nodes[current_index]["status"] = "completed"
        path.nodes[current_index]["completed_at"] = timezone.now().isoformat()
        path.save()

        # Запускаем адаптацию пути (remedial, skip и т.д.)
        DecisionService.evaluate_and_adapt_path(enrollment, lesson)

        # Переход к следующему узлу — только если нет новых recommended/remedial
        if path.next_node and not any(
                n["status"] in ["recommended", "remedial"] for n in path.nodes[current_index + 1:]
        ):
            path.current_node_index += 1

        path.save()

        logger.info(f"Оценка завершена для enrollment {enrollment_id}")
        return {"status": "success"}

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
            metadata={"error": str(e)}
        )
        raise self.retry(exc=e, countdown=60)  # retry 1 раз через минуту


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
