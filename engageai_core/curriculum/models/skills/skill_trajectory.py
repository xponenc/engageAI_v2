from django.db import models
from curriculum.validators import SkillDomain
from users.models import Student


class SkillTrajectory(models.Model):
    """
    Агрегирует историю SkillSnapshot и Assessment
    и используется для стратегических решений.

    ЧИТАЕТСЯ:
    - ExplainabilityEngine
    - AdminExplainabilityService

    ПИШЕТСЯ:
    - SkillTrajectoryUpdater
    """
    objects = models.Manager()

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="skill_trajectories")
    skill = models.CharField(max_length=32, choices=SkillDomain.choices)
    trend = models.FloatField(default=0.0)
    stability = models.FloatField(default=0.0)
    plateau_detected = models.BooleanField(default=False)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("student", "skill")

    def __str__(self) -> str:
        return f"{self.student} → {self.skill}"
