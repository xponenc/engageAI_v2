from django.db import models

from curriculum.models.content.task import Task
from curriculum.models.student.enrollment import Enrollment
from curriculum.models.student.student_response import StudentTaskResponse


class TaskAssessmentResult(models.Model):
    """
    Результат оценки конкретного задания студента в рамках урока.
    Хранит score, фидбек и метаданные для каждого задания отдельно.
    """
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name='task_assessments')
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='task_assessments')
    response = models.OneToOneField(StudentTaskResponse, on_delete=models.SET_NULL, null=True, related_name='assessment')

    score = models.FloatField(null=True, blank=True, help_text="0.0–1.0")
    is_correct = models.BooleanField(null=True, blank=True, help_text="Для closed-заданий")
    feedback = models.TextField(blank=True, help_text="Краткий комментарий LLM или правила")
    structured_feedback = models.JSONField(default=dict, blank=True, help_text="{'grammar_error': 'Past Simple', 'confidence': 0.92}")
    evaluated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['enrollment', 'task']  # Один результат на задание в enrollment
        indexes = [
            models.Index(fields=['enrollment', 'task']),
            models.Index(fields=['score']),
        ]

    def __str__(self):
        return f"Task {self.task.id} для enrollment {self.enrollment.id} — score {self.score}"

    @classmethod
    def calc_task_score(cls, result: 'AssessmentResult'):
        """Выставление общей оценки за задание по AssessmentResult"""
        skill_scores = []
        for skill, data in result.skill_evaluation.items():
            if not isinstance(data, dict):
                continue
            score = data.get("score")
            if score is None:
                continue
            if isinstance(score, str):
                score = float(score.replace(",", "."))
            skill_scores.append(score)

        if skill_scores:
            task_score = sum(skill_scores) / len(skill_scores)
        else:
            # fallback: бинарный score по is_correct, если есть
            task_score = float(result.is_correct) if result.is_correct is not None else 0
        return task_score
