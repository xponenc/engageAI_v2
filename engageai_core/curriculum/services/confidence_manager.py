# curriculum/services/confidence_manager.py
"""
Менеджер уровня уверенности студента с учётом реальной структуры оценки.
Обновление на основе:
- TaskAssessmentResult.score (микро-успехи)
- LessonAssessmentResult.overall_score (макро-успехи)
"""
from datetime import timedelta

from django.utils import timezone

from curriculum.models import TaskAssessmentResult, LessonAssessmentResult
from curriculum.models.assessment.lesson_assesment import AssessmentStatus
from users.models import Student


class ConfidenceManager:
    """Менеджер уровня уверенности студента"""

    @classmethod
    def update_confidence_from_task(
            cls,
            student_id: int,
            task_assessment_id: int
    ) -> int:
        """
        Обновление уверенности на основе оценки задания.

        Правила:
        - score ≥ 0.8 → +1 к уверенности (сильный успех)
        - 0.6 ≤ score < 0.8 → +0.5 к уверенности (умеренный успех)
        - 0.4 ≤ score < 0.6 → без изменений (нейтрально)
        - score < 0.4 → -0.5 к уверенности (неудача)

        Возвращает: новый уровень уверенности (1-10)
        """
        # Получаем оценку задания
        assessment = TaskAssessmentResult.objects.select_related('enrollment').get(
            id=task_assessment_id
        )

        # Получаем/создаём профиль студента
        student, _ = Student.objects.get_or_create(id=student_id)

        # Обновляем уверенность на основе скор
        if assessment.score is not None:
            if assessment.score >= 0.8:
                student.confidence_level = min(10, student.confidence_level + 1)
            elif assessment.score >= 0.6:
                student.confidence_level = min(10, student.confidence_level + 0.5)
            elif assessment.score < 0.4:
                student.confidence_level = max(1, student.confidence_level - 0.5)

        student.save(update_fields=['confidence_level'])
        return int(student.confidence_level)

    @classmethod
    def update_confidence_from_lesson(
            cls,
            student_id: int,
            lesson_assessment_id: int
    ) -> int:
        """
        Обновление уверенности на основе оценки урока (макро-успех).

        Правила:
        - Урок завершён успешно (overall_score ≥ 0.7) → +2 к уверенности
        - Урок завершён с ремедиацией (overall_score < 0.6) → -1.5 к уверенности
        - Урок в процессе оценки → без изменений

        Возвращает: новый уровень уверенности (1-10)
        """
        # Получаем оценку урока
        assessment = LessonAssessmentResult.objects.select_related('enrollment').get(
            id=lesson_assessment_id
        )

        # Получаем/создаём профиль студента
        student, _ = Student.objects.get_or_create(id=student_id)

        # Обновляем уверенность на основе статуса и скор урока
        if assessment.status == AssessmentStatus.COMPLETED:
            if assessment.overall_score is not None:
                if assessment.overall_score >= 0.7:
                    # Успешное завершение урока = большой прирост уверенности
                    student.confidence_level = min(10, student.confidence_level + 2)
                elif assessment.overall_score < 0.6:
                    # Ремедиация = падение уверенности
                    student.confidence_level = max(1, student.confidence_level - 1.5)

        student.save(update_fields=['confidence_level'])
        return int(student.confidence_level)

    @classmethod
    def can_advance_to_difficult_content(cls, student_id: int) -> bool:
        """
        Можно ли переходить к сложному контенту?
        Условие: уверенность ≥ 7
        """
        try:
            student = Student.objects.get(id=student_id)
            return student.confidence_level >= 7
        except Student.DoesNotExist:
            return False

    @classmethod
    def get_confidence_trend(cls, student_id: int, days: int = 7) -> dict:
        """
        Получает тренд уверенности за последние N дней.

        Возвращает: {
            'current': 6,
            'previous': 5,
            'trend': '+1',
            'assessments_count': 15
        }
        """
        from django.db.models import Avg, Count

        # Получаем все оценки заданий студента за период
        assessments = TaskAssessmentResult.objects.filter(
            enrollment__student_id=student_id,
            evaluated_at__gte=timezone.now() - timedelta(days=days)
        )

        # Считаем средний скор и количество оценок
        stats = assessments.aggregate(
            avg_score=Avg('score'),
            count=Count('id')
        )

        # Получаем текущий уровень уверенности
        try:
            student = Student.objects.get(id=student_id)
            current_confidence = student.confidence_level
        except Student.DoesNotExist:
            current_confidence = 5

        # Простая эвристика тренда (можно улучшить)
        avg_score = stats['avg_score'] or 0.5
        trend = "+1" if avg_score > 0.6 else "-1" if avg_score < 0.4 else "0"

        return {
            'current': current_confidence,
            'previous': max(1, current_confidence - 1),  # Упрощённо
            'trend': trend,
            'assessments_count': stats['count']
        }