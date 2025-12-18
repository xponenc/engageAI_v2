from django.core.exceptions import ValidationError

from curriculum.schemas import TASK_CONTENT_SCHEMAS


def validate_skill_focus(value: list[str]) -> None:

    from curriculum.models import SkillDomain

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