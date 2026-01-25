from django.db import models

from curriculum.models.content.lesson import Lesson
from curriculum.models.student.enrollment import Enrollment


class AssessmentStatus(models.TextChoices):
    PENDING = "PENDING", "Ожидание оценки"
    PROCESSING = "PROCESSING", "Оценка в процессе"
    COMPLETED = "COMPLETED", "Оценка завершена"
    ERROR = "ERROR", "Ошибка оценки"


class LessonAssessmentResult(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name='assessment_results')
    lesson = models.ForeignKey(Lesson, on_delete=models.SET_NULL, null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    overall_score = models.FloatField(null=True, blank=True)  # 0.0–1.0
    structured_feedback = models.JSONField(default=dict)  # {'grammar': 0.85, 'speaking': 0.62, ...}
    llm_summary = models.TextField(blank=True)  # Итоговое резюме LLM
    llm_recommendations = models.TextField(blank=True)  # "Рекомендуем больше практики speaking"
    status = models.CharField(max_length=20, default=AssessmentStatus.PENDING, choices=AssessmentStatus)
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ['enrollment', 'lesson']
