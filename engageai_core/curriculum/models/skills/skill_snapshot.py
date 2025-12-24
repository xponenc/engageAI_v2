from django.db import models

from users.models import Student


class SkillSnapshot(models.Model):
    """
    Снимок навыков студента после оценки.
    Используется как вход для SkillTrajectoryUpdater.
    """
    objects = models.Manager()

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="skill_snapshots")
    grammar = models.FloatField(default=0.0)
    vocabulary = models.FloatField(default=0.0)
    listening = models.FloatField(default=0.0)
    reading = models.FloatField(default=0.0)
    writing = models.FloatField(default=0.0)
    speaking = models.FloatField(default=0.0)
    snapshot_at = models.DateTimeField(auto_now_add=True)

    def to_dict(self):
        return {
            'grammar': self.grammar,
            'vocabulary': self.vocabulary,
            'listening': self.listening,
            'reading': self.reading,
            'writing': self.writing,
            'speaking': self.speaking,
        }

    def __str__(self) -> str:
        return f"SkillSnapshot({self.student}, {self.snapshot_at})"
