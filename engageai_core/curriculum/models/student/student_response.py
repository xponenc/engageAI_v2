from django.db import models
from django.utils.translation import gettext_lazy as _

from curriculum.models.content.task import Task
from curriculum.models.student.enrollment import Enrollment
from users.models import Student


class StudentTaskResponse(models.Model):
    """
    Ответ студента на задание.

    Назначение:
    - Хранит как текст, так и аудио.
    - Используется для автоматической и LLM-оценки.

    Поля:
    - response_text: для writing, short_text
    - audio_file: для speaking
    - is_correct: True/False для закрытых, None для открытых
    """
    student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("Student"))
    task = models.ForeignKey(Task, on_delete=models.CASCADE, verbose_name=_("Task"), related_name="student_response")
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, null=True, blank=True)  # ← добавляем
    response_text = models.TextField(blank=True, verbose_name=_("Text Response"))
    audio_file = models.FileField(upload_to='responses/', blank=True, null=True, verbose_name=_("Audio Response"))
    transcript = models.TextField(blank=True, null=True, verbose_name=_("Audio Transcript"))
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Submitted At"))

    class Meta:
        verbose_name = _("Student Task Response")
        verbose_name_plural = _("Student Task Responses")
        indexes = [
            models.Index(fields=['student', 'task'],
                         name='response_student_task_idx'),
            models.Index(fields=['task']),
            models.Index(fields=['submitted_at']),
        ]
        unique_together = ['enrollment', 'task']  # Один ответ на задание в рамках enrollment

    def __str__(self):
        return f"Response by {self.student} to {self.task}"
