from django.db import models

from users.models import Student

from django.utils.translation import gettext_lazy as _


class SkillDelta(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="skill_deltas")
    enrollment = models.ForeignKey("Enrollment", on_delete=models.CASCADE, related_name="skill_deltas")
    lesson = models.ForeignKey("Lesson", on_delete=models.CASCADE, related_name="skill_deltas")

    pre_snapshot = models.ForeignKey(
        "SkillSnapshot", on_delete=models.SET_NULL, null=True, related_name="deltas_as_pre"
    )
    post_snapshot = models.ForeignKey(
        "SkillSnapshot", on_delete=models.SET_NULL, null=True, related_name="deltas_as_post"
    )

    deltas = models.JSONField(
        help_text=_("{'grammar': +0.10, 'speaking': -0.03, 'overall': +0.08}")
    )

    calculated_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ["student", "lesson"]

    def __str__(self):
        return f"{self.student} — Урок {self.lesson.order} — Δ {self.deltas.get('overall', 0):+.2f}"