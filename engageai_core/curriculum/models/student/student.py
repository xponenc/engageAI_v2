# from django.contrib.auth import get_user_model
# from django.db import models
# from django.utils.translation import gettext_lazy as _
#
# from users.models import CEFRLevel
#
#
# User = get_user_model()
#
#
# class Student(models.Model):
#     """
#     Профиль студента — расширение User.
#
#     Назначение:
#     - Хранит профессиональный контекст (из мини-анкеты, блок 2),
#     - Текущий CEFR-уровень,
#     - Используется для персонализации.
#
#     Поля:
#     - systematization: свободное текстовое поле или JSON с ролью/целями
#     - cefr_level: текущий уровень (обновляется после диагностики)
#     """
#     user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name=_("User"))
#     cefr_level = models.CharField(
#         max_length=2, choices=CEFRLevel, null=True, blank=True,
#         verbose_name=_("Current CEFR Level")
#     )
#     professional_context = models.TextField(
#         blank=True,
#         verbose_name=_("Professional Context"),
#         help_text=_("e.g., 'Backend developer in fintech. Need English for stand-ups and documentation.'")
#     )
#     created_at = models.DateTimeField(auto_now_add=True)
#
#     class Meta:
#         verbose_name = _("Student")
#         verbose_name_plural = _("Students")
#         indexes = [models.Index(fields=['cefr_level'])]
#
#     def __str__(self):
#         return f"{self.user.get_full_name() or self.user.username} ({self.cefr_level or '–'})"