import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from curriculum.models.content.course import Course
from curriculum.models.content.lesson import Lesson
from curriculum.models.content.task import Task
from curriculum.models.systematization.learning_objective import LearningObjective
from curriculum.models.systematization.professional_tag import ProfessionalTag


class Command(BaseCommand):
    help = "Create course, lessons, objectives and tasks from JSON definition"

    def add_arguments(self, parser):
        parser.add_argument(
            "json_path",
            type=str,
            help="Path to course JSON file"
        )

    # -------------------------------------------------
    # Entry point
    # -------------------------------------------------

    def handle(self, *args, **options):
        json_path = Path(options["json_path"])

        if not json_path.exists():
            raise CommandError(f"File not found: {json_path}")

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except json.JSONDecodeError as e:
            raise CommandError(f"Invalid JSON: {e}")

        self._validate_payload(payload)

        with transaction.atomic():
            # 0️⃣ professional tags
            self._ensure_professional_tags(payload)

            # 1️⃣ course
            course = self._create_course(payload["course"])
            self.stdout.write(self.style.SUCCESS(f"Course created: {course}"))

            # 2️⃣ lessons
            for lesson_data in payload["lessons"]:
                self._create_lesson(course, lesson_data)

        self.stdout.write(self.style.SUCCESS("Import completed successfully."))

    # -------------------------------------------------
    # Validation
    # -------------------------------------------------

    def _validate_payload(self, payload: dict):
        if "course" not in payload:
            raise CommandError("Missing 'course' section")

        if "lessons" not in payload or not isinstance(payload["lessons"], list):
            raise CommandError("'lessons' must be a list")

        for lesson in payload["lessons"]:
            if "tasks" not in lesson:
                raise CommandError("Each lesson must contain 'tasks'")

    # -------------------------------------------------
    # Professional tags
    # -------------------------------------------------

    def _ensure_professional_tags(self, payload: dict):
        """
        Создает все ProfessionalTag, упомянутые в JSON,
        если они еще не существуют.
        """
        tag_names: set[str] = set()

        for lesson in payload["lessons"]:
            for task in lesson["tasks"]:
                for tag in task.get("professional_tags", []):
                    tag_names.add(tag)

        for name in sorted(tag_names):
            ProfessionalTag.objects.get_or_create(name=name)

        self.stdout.write(f"Professional tags ensured: {', '.join(sorted(tag_names))}")

    # -------------------------------------------------
    # Creation logic
    # -------------------------------------------------

    def _create_course(self, data: dict) -> Course:
        course, created = Course.objects.get_or_create(
            title=data["title"],
            defaults={
                "description": data["description"],
                "target_cefr_from": data["target_cefr_from"],
                "target_cefr_to": data["target_cefr_to"],
                "estimated_duration": data["estimated_duration"],
            }
        )

        if not created:
            self.stdout.write(
                self.style.WARNING(
                    f"Course '{course.title}' already exists, reusing it"
                )
            )

        return course

    def _create_lesson(self, course: Course, data: dict):
        lesson = Lesson.objects.create(
            course=course,
            order=data["order"],
            title=data["title"],
            description=data["description"],
            duration_minutes=data["duration_minutes"],
            required_cefr=data["required_cefr"],
            skill_focus=data["skill_focus"],
            content=data["content"],
        )

        self.stdout.write(f"  Lesson {lesson.order}: {lesson.title}")

        objectives = self._create_objectives(data.get("learning_objectives", []))
        lesson.learning_objectives.set(objectives)

        for task_data in data["tasks"]:
            self._create_task(lesson, task_data)

    def _create_objectives(self, objectives_data: list):
        identifiers = [obj["identifier"] for obj in objectives_data]

        # 1️⃣ массово создаем (если нет)
        LearningObjective.objects.bulk_create(
            [
                LearningObjective(
                    identifier=obj["identifier"],
                    name=obj["name"],
                    cefr_level=obj["cefr_level"],
                    skill_domain=obj["skill_domain"],
                )
                for obj in objectives_data
            ],
            ignore_conflicts=True
        )

        # 2️⃣ гарантированно читаем существующие
        objs = list(
            LearningObjective.objects.filter(identifier__in=identifiers)
        )

        return objs

    def _create_task(self, lesson: Lesson, data: dict):
        task = Task.objects.create(
            lesson=lesson,
            task_type=data["task_type"],
            response_format=data["response_format"],
            difficulty_cefr=data["difficulty_cefr"],
            is_diagnostic=data["is_diagnostic"],
            content_schema_version=data["content_schema_version"],
            content=data["content"],
        )

        tags = ProfessionalTag.objects.filter(
            name__in=data.get("professional_tags", [])
        )

        task.professional_tags.set(tags)
