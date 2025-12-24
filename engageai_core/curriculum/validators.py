from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from curriculum.infrastructure.validation.task_schemas import TASK_CONTENT_SCHEMAS


class SkillDomain(models.TextChoices):
    """Области языковых навыков (Skill Domains)."""

    GRAMMAR = ("grammar", _("Грамматика"))
    VOCABULARY = ("vocabulary", _("Лексика"))
    READING = ("reading", _("Чтение"))
    LISTENING = ("listening", _("Аудирование"))
    WRITING = ("writing", _("Письмо"))
    SPEAKING = ("speaking", _("Говорение"))
    # PRONUNCIATION = ("pronunciation", _("Произношение"))
    # USE_OF_ENGLISH = ("use_of_english", _("Использование языка"))
    # DISCOURSE = ("discourse", _("Связность и логика речи"))
    # INTERACTION = ("interaction", _("Коммуникативное взаимодействие"))
    # FLUENCY = ("fluency", _("Беглость речи"))


def validate_skill_focus(value: list[str]) -> None:

    if not isinstance(value, list):
        raise ValidationError("skill_focus must be a list")

    allowed = {choice.value for choice in SkillDomain}

    invalid = set(value) - allowed
    if invalid:
        raise ValidationError(f"Invalid skill(s): {', '.join(invalid)}")


def validate_task_content_schema(content: dict, schema_version: str):
    schema = TASK_CONTENT_SCHEMAS.get(schema_version)
    if not schema:
        raise ValidationError(f"Unknown schema version: {schema_version}")

    missing = schema["required"] - content.keys()
    if missing:
        raise ValidationError(f"Missing fields: {missing}")
