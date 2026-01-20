# from django.contrib.auth import get_user_model
# from django.db import models
# from django.utils.translation import gettext_lazy as _
#
#
# User = get_user_model()
#
#
# class Teacher(models.Model):
#     """
#     Профиль учителя — расширение User.
#
#
#     """
#     user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name=_("User"))
#
#     created_at = models.DateTimeField(auto_now_add=True)
#
#     class Meta:
#         verbose_name = _("Учитель")
#         verbose_name_plural = _("Учителя")
