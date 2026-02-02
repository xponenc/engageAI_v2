import json
from typing import Dict, Any

from curriculum.models import Lesson, Task, Course
from curriculum.models.student.enrollment import Enrollment


class PageContextService:
    """Сервис обработки поступившей вместе с сообщением чата контекстной
     информации о странице с которой было отправлено сообщение"""

    MODEL_MAP = {
        "Lesson": Lesson,
        "Task": Task,
        "Course": Course,
    }

    @classmethod
    def validate_data(cls, raw_message_context: dict, user: "User") -> Dict[str, Any]:
        context: Dict[str, Any] = {}

        if not user.is_authenticated or not raw_message_context:
            return context
        action_context = raw_message_context.get("action_context")
        environment_context = raw_message_context.get("environment_context")

        action_payload = {}
        try:
            action_payload = json.loads(action_context)
            context["action_context"] = {}
        except json.JSONDecodeError:
            pass
        # --- context objects ---
        obj_type = action_payload.get("type")
        obj_id = action_payload.get("id")
        if obj_type or not obj_id:
            model = cls.MODEL_MAP.get(obj_type)
            # Базовая проверка существования
            if model and model.objects.filter(id=obj_id).exists():
                context["action_context"][f"{obj_type.lower()}_id"] = obj_id

        print(environment_context)
        environment_payload = {}
        try:
            environment_payload = json.loads(environment_context)
            context["environment_context"] = {}
        except json.JSONDecodeError:
            pass

        # --- page type ---
        page_type = environment_payload.get("pageType")
        if page_type:
            context["environment_context"]["page"] = page_type

        # --- enrollment ---
        enrollment_id = environment_payload.get("enrollmentId")
        if enrollment_id and Enrollment.objects.filter(
                id=enrollment_id,
                student__user_id=user.id
        ).exists():
            context["environment_context"]["enrollment_id"] = enrollment_id
        else:
            enrollment_id = None  # дальше используем как якорь

        # --- context objects ---
        context_objects = environment_payload.get("contextObjects", [])

        if isinstance(context_objects, str):
            try:
                context_objects = json.loads(context_objects)
            except json.JSONDecodeError:
                context_objects = []
        if not isinstance(context_objects, list):
            return context

        for obj in context_objects:
            obj_type = obj.get("type")
            obj_id = obj.get("id")
            if not obj_type or not obj_id:
                continue

            model = cls.MODEL_MAP.get(obj_type)
            if not model:
                continue
            # Базовая проверка существования
            if model.objects.filter(id=obj_id).exists():
                context["environment_context"][f"{obj_type.lower()}_id"] = obj_id

        return context
