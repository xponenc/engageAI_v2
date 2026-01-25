# curriculum/services/assessment/lesson_assessment_service.py

from celery.result import AsyncResult
from django.utils import timezone

from curriculum.models.content.lesson import Lesson
from curriculum.tasks import assess_lesson_tasks
from curriculum.models.student.enrollment import Enrollment
import logging

logger = logging.getLogger(__name__)


class LessonAssessmentService:
    """
    Фасад для запуска и мониторинга оценки урока.
    Делегирует всю работу Celery-задаче assess_lesson_tasks.
    """

    def start_assessment(self, enrollment: Enrollment, assessed_lesson: Lesson) -> str | None:
        """
        Запускает оценку текущего урока.
        Возвращает ID задачи или None при ошибке.
        """
        if enrollment.lesson_status != 'PENDING_ASSESSMENT':
            logger.warning(f"Повторный запуск оценки для {enrollment.pk} в статусе {enrollment.lesson_status}")
            return None

        try:
            job = assess_lesson_tasks.delay(enrollment.pk, assessed_lesson.pk)  # Только enrollment.id!
            logger.info(f"Оценка запущена: enrollment={enrollment.pk}, job={job.id}")

            enrollment.assessment_job_id = job.id
            enrollment.assessment_started_at = timezone.now()
            enrollment.save(update_fields=['assessment_job_id', 'assessment_started_at'])

            return job.id

        except Exception as e:
            logger.error(f"Ошибка запуска оценки {enrollment.id}: {str(e)}", exc_info=True)
            enrollment.lesson_status = 'ASSESSMENT_ERROR'
            enrollment.save(update_fields=['lesson_status'])
            return None

    def get_status(self, enrollment: Enrollment) -> dict:
        """
        Получает статус задачи оценки (для CheckLessonAssessmentView).
        """
        if not enrollment.assessment_job_id:
            return {
                'status': enrollment.lesson_status,
                'message': 'Задача не найдена',
                'can_proceed': enrollment.lesson_status == 'COMPLETED'
            }

        job = AsyncResult(enrollment.assessment_job_id)

        if job.ready():
            if job.successful():
                enrollment.lesson_status = 'COMPLETED'
                enrollment.save(update_fields=['lesson_status'])
                return {
                    'status': 'COMPLETED',
                    'message': 'Оценка завершена',
                    'can_proceed': True,
                    'redirect_url': f'/curriculum/session/{enrollment.id}/'
                }
            else:
                error = str(job.result) or "Неизвестная ошибка"
                enrollment.lesson_status = 'ASSESSMENT_ERROR'
                enrollment.save(update_fields=['lesson_status'])
                return {
                    'status': 'ERROR',
                    'error_message': error,
                    'can_proceed': False
                }

        # В процессе
        progress = job.info or {'current': 0, 'total': 1}
        current = progress.get('current', 0)
        total = progress.get('total', 1)

        elapsed_min = (timezone.now() - enrollment.assessment_started_at).total_seconds() / 60
        remaining = max(0, total - elapsed_min)  # пример: 1 мин на задание

        return {
            'status': 'PENDING_ASSESSMENT',
            'progress': min(99, int(current / total * 100)) if total > 0 else 0,
            'current': current,
            'total': total,
            'estimated_remaining': round(remaining, 1),
            'can_proceed': False,
            'message': f'Оценка идёт... Осталось ~{round(remaining, 1)} мин'
        }
