import json
import os

import requests
from celery import shared_task, chain, group
from celery.exceptions import SoftTimeLimitExceeded
import logging

from django.utils import timezone

from ai.llm.llm_factory import llm_factory
from curriculum.models.assessment.lesson_assesment import LessonAssessmentResult
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

logger = logging.getLogger(__name__)


@shared_task
def transcribe_response(response_id: int) -> int:
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
    enrollment = Enrollment.objects.select_related('student', 'course').get(id=enrollment_id)

    lesson = Lesson.objects.get(id=assessed_lesson_id)
    try:

        print(f"{lesson=}")

        logger.info(f"Оценка урока {lesson.title} ({assessed_lesson_id}) для enrollment {enrollment_id}")

        # Все ответы по этому уроку
        responses = StudentTaskResponse.objects.filter(
            enrollment=enrollment,
            task__lesson=lesson
        ).select_related('task')
        print(f"{responses=}")

        if not responses:
            raise ValueError("Нет ответов для оценки")

        auto_adapter = AutoAssessorAdapter()
        llm_adapter = LLMAssessmentAdapter()

        total_score = 0.0
        task_count = responses.count()

        for resp in responses:
            task = resp.task

            if task.response_format in AutoAssessorAdapter.SUPPORTED_FORMATS:
                result = auto_adapter.assess_task(task, resp)
            else:
                result = llm_adapter.assess_task(task, resp)

            # Сохраняем результат оценки задания
            TaskAssessmentResult.objects.create(
                enrollment=enrollment,
                task=task,
                response=resp,
                score=result.skill_evaluation.get(task.task_type, {}).get("score"),
                feedback=result.summary.get("text", ""),
                structured_feedback=result.skill_evaluation,
                is_correct=result.skill_evaluation.get(task.task_type, {}).get("score", 0) >= 0.8
            )

            total_score += result.skill_evaluation.get(task.task_type, {}).get("score", 0.0) or 0.0

        # Итоговый результат урока
        overall_score = total_score / task_count if task_count > 0 else 0.0

        lesson_result = LessonAssessmentResult.objects.create(
            enrollment=enrollment,
            lesson=lesson,
            overall_score=overall_score,
            status='COMPLETED',
            completed_at=timezone.now()
        )

        # Итоговое резюме LLM по уроку
        summary_prompt = f"""
        Подведи итог урока для студента уровня {enrollment.student.english_level}.
        Общий score: {overall_score:.2f}
        """
        user_message = f"""Задания: {json.dumps({r.task.id: r.score for r in responses}, indent=2)}

        Дай краткое резюме (2–3 предложения) и 2–3 конкретные рекомендации по улучшению.
        """
        print(summary_prompt)
        print(user_message)

        summary_response = llm_factory.generate_json_response(
            system_prompt=summary_prompt,
            user_message=user_message,
        )
        lesson_result.llm_summary = summary_response.get("text", "")
        lesson_result.llm_recommendations = "\n".join(summary_response.get("advice", []))
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
                "overall_score": overall_score,
                "tasks_evaluated": task_count,
                "job_id": self.request.id
            }
        )

        # Обновляем узел пути
        path = enrollment.learning_path
        current_index = path.current_node_index
        path.nodes[current_index]["status"] = "completed"
        path.nodes[current_index]["completed_at"] = timezone.now().isoformat()

        # Запускаем адаптацию пути (remedial, skip и т.д.)
        DecisionService.evaluate_and_adapt_path(enrollment, lesson)

        # Переход к следующему узлу — только если нет новых recommended/remedial
        if path.next_node and not any(
            n["status"] in ["recommended", "remedial"] for n in path.nodes[current_index + 1:]
        ):
            path.current_node_index += 1

        path.save()

        logger.info(f"Оценка завершена для enrollment {enrollment_id}, score={overall_score:.2f}")
        return {"status": "success", "overall_score": overall_score}

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