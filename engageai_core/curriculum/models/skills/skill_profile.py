from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from users.models import Student


#
# class SkillProfile(models.Model):
#     """
#     Профиль навыков — результат диагностики или промежуточной оценки.
#
#     Назначение:
#     - Соответствует цели №2 из плана: «Сформировать первичный профиль навыков».
#     - Используется для Goal Setting и подбора курсов.
#
#     Поля:
#     - grammar, vocabulary, listening, reading, writing, speaking: float от 0.0 до 1.0
#     - snapshot_at: момент оценки (можно хранить историю прогресса)
#     """
#     student = models.ForeignKey(Student, on_delete=models.CASCADE, verbose_name=_("Student"))
#     grammar = models.FloatField(default=0.0, verbose_name=_("Grammar Score"))
#     vocabulary = models.FloatField(default=0.0, verbose_name=_("Vocabulary Score"))
#     listening = models.FloatField(default=0.0, verbose_name=_("Listening Score"))
#     reading = models.FloatField(default=0.0, verbose_name=_("Reading Score"))
#     writing = models.FloatField(default=0.0, verbose_name=_("Writing Score"))
#     speaking = models.FloatField(default=0.0, verbose_name=_("Speaking Score"))
#     snapshot_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Snapshot Timestamp"))
#
#     class Meta:
#         verbose_name = _("Skill Profile")
#         verbose_name_plural = _("Skill Profiles")
#         indexes = [
#             models.Index(fields=['student']),
#             models.Index(fields=['snapshot_at']),
#         ]
#
#     def __str__(self):
#         return f"Skill Profile for {self.student} at {self.snapshot_at.date()}"


class CurrentSkillProfile(models.Model):
    """
    Текущее состояние навыков студента.
    Заменяет CurrentSkill и SkillProfile.
    """
    objects = models.Manager()

    student = models.OneToOneField(
        Student,
        on_delete=models.CASCADE,
        related_name="skill_profile"
    )
    grammar = models.FloatField(default=0.0, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    vocabulary = models.FloatField(default=0.0, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    listening = models.FloatField(default=0.0, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    reading = models.FloatField(default=0.0, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    writing = models.FloatField(default=0.0, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    speaking = models.FloatField(default=0.0, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    last_updated = models.DateTimeField(auto_now=True)

    def to_dict(self):
        """Вспомогательный метод для работы со всеми навыками как со словарем"""
        return {
            'grammar': self.grammar,
            'vocabulary': self.vocabulary,
            'listening': self.listening,
            'reading': self.reading,
            'writing': self.writing,
            'speaking': self.speaking,
        }

    def update_from_dict(self, skills_dict):
        """Обновление навыков из словаря"""
        for skill, value in skills_dict.items():
            if hasattr(self, skill):
                setattr(self, skill, max(0.0, min(1.0, float(value))))