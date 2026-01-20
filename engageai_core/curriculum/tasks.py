import os

import requests
from celery import shared_task, chain, group
from celery.exceptions import SoftTimeLimitExceeded
import logging

from curriculum.models.student.enrollment import Enrollment
from curriculum.models.student.student_response import StudentTaskResponse

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


@shared_task(bind=True, soft_time_limit=300, time_limit=360)
def assess_lesson_tasks(self, enrollment_id):
    """
    Фоновая задача для оценки всех заданий в уроке.

    Особенности:
    - Работает только в BATCH_MODE
    - Не зависит от LearningService
    - Полностью изолирована от веб-слоя
    - Обеспечивает отказоустойчивость

    Алгоритм:
    1. Получаем зачисление и ответы студента
    2. Создаем LessonAssessmentService
    3. Выполняем оценку урока
    4. Обрабатываем результат или ошибку
    """
    try:
        logger.info(f"Starting assessment task for enrollment {enrollment_id}")

        # Получаем зачисление
        enrollment = Enrollment.objects.select_related(
            'student', 'course', 'current_lesson'
        ).get(id=enrollment_id, is_active=True)

        # Получаем ответы студента
        responses = StudentTaskResponse.objects.filter(
            student=enrollment.student,
            task__lesson=enrollment.current_lesson,
            task__is_active=True
        ).select_related('task')

        logger.info(f"Found {responses.count()} responses to assess for enrollment {enrollment_id}")

        if not responses.exists():
            raise ValueError(f"No responses found for enrollment {enrollment_id}")

        # Создаем сервис для batch-обработки
        factory = CurriculumServiceFactory()
        lesson_assessment_service = factory.create_lesson_assessment_service()

        # Оцениваем урок
        result = lesson_assessment_service.assess_lesson(
            enrollment=enrollment,
            responses=list(responses)
        )

        logger.info(f"Successfully completed assessment for enrollment {enrollment_id}")
        return result

    except SoftTimeLimitExceeded:
        logger.error(f"Assessment task timed out for enrollment {enrollment_id}")
        _handle_assessment_error(enrollment_id, "Assessment timed out after 5 minutes")
        raise

    except Exception as e:
        logger.error(f"Critical error in assess_lesson_tasks: {str(e)}", exc_info=True)
        _handle_assessment_error(enrollment_id, str(e))
        raise


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