from dataclasses import dataclass

from django.utils import timezone

from curriculum.models import TaskAssessmentResult, LessonAssessmentResult
from curriculum.models.assessment.lesson_assesment import AssessmentStatus
from users.models import Student


@dataclass
class FrustrationState:
    score: int          # 0–10
    is_critical: bool   # да/нет

class FrustrationAnalyzer:
    """Анализатор фрустрации на уровне студента (агрегация по всем курсам)"""

    @classmethod
    def _calculate_frustration_signals(cls, student_id: int) -> int:
        """
        Рассчитывает фрустрацию на уровне студента (НЕ курса).

        Почему на уровне студента:
        - Фрустрация в одном курсе влияет на мотивацию во всех курсах
        - Студент воспринимает обучение как единый процесс (Задача 2.1 ТЗ: единая модель данных)
        - Адаптация ответов чата должна учитывать общее состояние, а не контекст конкретного курса

        Алгоритм:
        1. Берём последние 15 оценок заданий по ВСЕМ активным курсам студента
        2. Сортируем по времени (самые свежие первыми)
        3. Считаем серию ошибок ПОДРЯД с конца списка (последние попытки)
        4. Добавляем +2 если последний завершённый урок по ЛЮБОМУ курсу — с ремедиацией (score < 0.6)
        5. Итог: сумма по всем факторам, ограничена 0-10

        Возвращает: целое число 0-10
        """
        # Шаг 1: Последние 15 оценок по ВСЕМ курсам студента
        recent_assessments = TaskAssessmentResult.objects.filter(
            enrollment__student_id=student_id  # ← Фильтрация по студенту, а не по enrollment
        ).order_by('-evaluated_at')[:15]  # Последние 15 оценок по всем курсам

        if not recent_assessments:
            return 0

        # Шаг 2: Считаем серию ошибок ПОДРЯД с конца списка
        consecutive_errors = 0
        for assessment in reversed(recent_assessments):  # От самых свежих к старым
            is_error = (
                    assessment.is_correct is False or
                    (assessment.score is not None and assessment.score < 0.5)
            )
            if is_error:
                consecutive_errors += 1
            else:
                break  # Прерываем при первой правильной оценке

        # Шаг 3: Анализ последнего завершённого урока по ЛЮБОМУ курсу
        lesson_frustration = 0

        # Находим последний завершённый урок среди всех курсов студента
        last_completed_lesson = LessonAssessmentResult.objects.filter(
            enrollment__student_id=student_id,
            status=AssessmentStatus.COMPLETED
        ).select_related('enrollment__course').order_by('-completed_at').first()

        if last_completed_lesson and last_completed_lesson.overall_score is not None:
            if last_completed_lesson.overall_score < 0.6:
                lesson_frustration = 2  # Ремедиация = признак фрустрации
            elif last_completed_lesson.overall_score >= 0.8:
                lesson_frustration = -1  # Успех = снижение фрустрации

        # Шаг 4: Итоговый расчёт
        frustration_score = consecutive_errors + lesson_frustration
        return min(10, max(0, frustration_score))

    @classmethod
    def _detect_critical_frustration(cls, student_id: int, frustration_score: int, chat_message: str = "", ) -> bool:
        """
        Детектирует критическую фрустрацию студента (агрегация по всем курсам).

        Критерии:
        1. Серия ошибок ≥5 подряд по любому курсу
        2. ИЛИ ремедиация в последнем уроке + негативный тон в чате
        3. ИЛИ студент вернулся после долгого перерыва с сообщением «бросаю/не могу»
        """

        # Критерий 1: Серия ошибок ≥5
        if frustration_score >= 5:
            return True

        # Критерий 2: Негативный тон в сообщении
        negative_triggers = ["бросаю", "не могу", "сложно", "надоело", "бесит", "злюсь", "устал"]
        if chat_message and any(trigger in chat_message.lower() for trigger in negative_triggers):
            return True

        # Критерий 3: Долгий перерыв + возвращение (проверяем через последнюю активность)
        try:
            student = Student.objects.get(id=student_id)
        except Student.DoesNotExist:
            return False
        # TODO писать последнюю активность
        # if student.last_activity_at:
        #     days_inactive = (timezone.now() - student.last_activity_at).days
        #     if days_inactive >= 7 and chat_message:
        #         return True

        return False

    @classmethod
    def analyze(cls, student_id: int, chat_message: str = "") -> FrustrationState:
        """
        Публичный фасад: один раз обращается к БД, возвращает и скор, и флаг критичности.
        """
        score = cls._calculate_frustration_signals(student_id)
        is_critical = cls._detect_critical_frustration(
            student_id=student_id,
            frustration_score=score,
            chat_message=chat_message,
        )
        return FrustrationState(score=score, is_critical=is_critical)