from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


class LearningPath(models.Model):
    """
    Персонализированный учебный путь студента в рамках зачисления.

    структура узла в nodes
        {
            "node_id": "remedial-grammar-B1-02-9f3a2c",
            "lesson_id": null,
            "learning_objective": "grammar-B1-02",
            "title": "Повтор: Past Simple vs Present Perfect",
            "type": "remedial",
            "status": "locked",
            "prerequisites": ["lesson-42"],
            "created_at": "2026-02-04T10:12:00Z",
            "completed_at": null,
            "metadata": {
                "source": "auto",
                "trigger": "multiple_failures"
            }
        }

    node_id : string Уникальный идентификатор узла внутри LearningPath. {node_type}-{lesson_or_objective}-{uuid4}
        Примеры:
            lesson-42
            remedial-grammar-B1-02-9f3a2c
            diagnostic-speaking-B2-7b12f9

    lesson_id : int | null ID урока, если узел привязан к Lesson.
        int → обычный урок курса
        null → виртуальный узел (remedial, diagnostic, practice)

    title : string Отображаемое название узла:
        берётся из Lesson
        либо генерируется (remedial)

    type : string Тип узла.
        Допустимые значения v1:
        type	Назначение
        core	Основной урок курса
        remedial	Повтор / восстановление
        diagnostic	Проверка уровня
        practice	Практика без теории

    status : string Текущее состояние узла.
        Допустимые значения
        status	Значение
        locked	Недоступен, нельзя начинать
        in_progress	Текущий активный узел
        completed	Успешно завершён
        skipped	Пропущен осознанно
        recommended	Рекомендован (не блокирует путь)

    prerequisites : list[str]
        Список node_id, которые должны быть:
        completed или skipped
        Используется:
        для remedial
        для сложных ветвлений

    triggers : list[object]
        Будущая точка расширения.
        Примеры:
        {
          "condition": "objective.grammar-B1-02 < 0.6",
          "action": "insert_remedial"
        }

    created_at : ISO datetime Когда узел был добавлен в путь.

    metadata : object
        Свободное поле:
        explainability
        source ("auto", "teacher", "diagnostic")
        confidence, reason и т.д.
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
                "node_id": "remedial-grammar-B1-02-9f3a2c",
                "lesson_id": null,
                "learning_objective": "grammar-B1-02",
                "title": "Повтор: Past Simple vs Present Perfect",
                "type": "remedial",
                "status": "locked",
                "prerequisites": ["lesson-42"],
                "created_at": "2026-02-04T10:12:00Z",
                "completed_at": null,
                "metadata": {
                    "source": "auto",
                    "trigger": "multiple_failures"
                }
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

    def advance_to_next_node(self):
        """Переход к следующему узлу после завершения урока"""
        if self.current_node_index + 1 < len(self.nodes):
            self.current_node_index += 1
            self.save(update_fields=["current_node_index", "updated_at"])