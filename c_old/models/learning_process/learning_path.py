from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class LearningPath(models.Model):
    """
    Персонализированный учебный путь студента в рамках зачисления.

    Заменяет жёсткую линейную последовательность (current_lesson).
    Позволяет:
    - Линейные пути (по умолчанию для MVP)
    - Адаптивные пути с ветвлениями и remedial уроками
    - AI-генерацию пути (GPT-4o-mini на основе профиля + SkillDelta)
    """

    enrollment = models.OneToOneField(
        "Enrollment",
        on_delete=models.CASCADE,
        related_name="learning_path",
        verbose_name=_("Зачисление"),
        help_text=_("Один путь на одно зачисление")
    )

    path_type = models.CharField(
        max_length=20,
        choices=[
            ("LINEAR", _("Линейный (по порядку уроков курса)")),
            ("ADAPTIVE", _("Адаптивный (с ветвлениями по SkillDelta)")),
            ("PERSONALIZED", _("Персонализированный (AI-генерированный под цели/профессию)")),
        ],
        default="LINEAR",
        verbose_name=_("Тип пути")
    )

    # JSON-структура пути: список узлов с условиями
    nodes = models.JSONField(
        verbose_name=_("Узлы пути"),
        default=list,
        help_text=_("""
        Пример структуры:
        [
            {
                "node_id": 1,
                "lesson_id": 5,
                "title": "Grammar: Present Simple",
                "prerequisites": [], 
                "triggers": [
                    {"condition": "skill_delta.speaking < 0", "action": "add_remedial", "remedial_lesson_id": 12}
                ],
                "status": "completed",  // in_progress, locked, recommended
                "completed_at": "2025-12-28T15:30:00Z"
            },
            ...
        ]
        """)
    )

    current_node_index = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Индекс текущего узла"),
        help_text=_("Позиция в массиве nodes")
    )

    generated_at = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("Время генерации пути")
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Время последнего обновления")
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Метаданные"),
        help_text=_(
            "e.g., {'generated_by': 'gpt-4o-mini', 'based_on_profile': {'level': 'B1', 'goal': 'IT_interview'}}")
    )

    class Meta:
        verbose_name = _("Учебный путь")
        verbose_name_plural = _("Учебные пути")

    def __str__(self):
        return f"{self.enrollment.student} — {self.get_path_type_display()} путь в курсе {self.enrollment.course.title}"

    @property
    def current_node(self):
        """Текущий узел для удобства в сервисах и views"""
        if self.nodes and self.current_node_index < len(self.nodes):
            return self.nodes[self.current_node_index]
        return None

    @property
    def next_node(self):
        """Следующий узел (для preview в боте и дашборде)"""
        next_index = self.current_node_index + 1
        if next_index < len(self.nodes):
            return self.nodes[next_index]
        return None

    def advance_to_next_node(self):
        """Переход к следующему узлу после завершения урока"""
        if self.current_node_index + 1 < len(self.nodes):
            self.current_node_index += 1
            self.save(update_fields=["current_node_index", "updated_at"])