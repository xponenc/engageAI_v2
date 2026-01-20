import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from curriculum.models.content.course import Course
from curriculum.models.content.lesson import Lesson
from curriculum.models.content.task import Task
from curriculum.models.systematization.learning_objective import LearningObjective
from curriculum.models.systematization.professional_tag import ProfessionalTag


class Command(BaseCommand):
    help = "Импорт курса, уроков, целей и заданий из JSON-файла"

    def add_arguments(self, parser):
        parser.add_argument(
            "json_path",
            type=str,
            help="Путь к JSON-файлу с определением курса"
        )

    def handle(self, *args, **options):
        json_path = Path(options["json_path"])

        if not json_path.exists():
            raise CommandError(f"Файл не найден: {json_path}")

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except json.JSONDecodeError as e:
            raise CommandError(f"Некорректный JSON: {e}")

        self._validate_payload(payload)

        with transaction.atomic():
            # 0. Профессиональные теги (все уникальные из JSON)
            self._ensure_professional_tags(payload)

            # 1. Курс
            course = self._create_course(payload["course"])
            self.stdout.write(self.style.SUCCESS(f"Курс: {course}"))

            # 2. Уроки
            for lesson_data in payload.get("lessons", []):
                self._create_lesson(course, lesson_data)

        self.stdout.write(self.style.SUCCESS("\nИмпорт завершён успешно!"))

    # ──────────────────────────────────────────────────────────────
    # Валидация
    # ──────────────────────────────────────────────────────────────

    def _validate_payload(self, payload: dict):
        required_top_keys = ["course", "lessons"]
        for key in required_top_keys:
            if key not in payload:
                raise CommandError(f"Отсутствует обязательный раздел: '{key}'")

        if not isinstance(payload["lessons"], list):
            raise CommandError("'lessons' должен быть списком")

        for i, lesson in enumerate(payload["lessons"], 1):
            required = ["order", "title", "description", "duration_minutes", "required_cefr", "skill_focus", "tasks"]
            for key in required:
                if key not in lesson:
                    raise CommandError(f"Урок #{i} ({lesson.get('title', '?')}): отсутствует '{key}'")

            if not isinstance(lesson["tasks"], list) or len(lesson["tasks"]) < 2:
                raise CommandError(f"Урок #{i}: должно быть минимум 2 задания")

    # ──────────────────────────────────────────────────────────────
    # Профессиональные теги
    # ──────────────────────────────────────────────────────────────

    def _ensure_professional_tags(self, payload: dict):
        all_tags = set()

        for lesson in payload["lessons"]:
            for task in lesson["tasks"]:
                all_tags.update(task.get("professional_tags", []))

        created = 0
        for name in sorted(all_tags):
            tag, was_created = ProfessionalTag.objects.get_or_create(name=name)
            if was_created:
                created += 1

        self.stdout.write(f"Профессиональные теги: {len(all_tags)} найдено, {created} создано")

    # ──────────────────────────────────────────────────────────────
    # Курс
    # ──────────────────────────────────────────────────────────────

    def _create_course(self, data: dict) -> Course:
        course, created = Course.objects.get_or_create(
            title=data["title"],
            defaults={
                "description": data.get("description", ""),
                # target_cefr_from/to убираем — курс не привязан к уровню
                "estimated_duration": data.get("estimated_duration", 0),
            }
        )

        if not created:
            self.stdout.write(self.style.WARNING(f"Курс '{course}' уже существует → используем существующий"))

        return course

    # ──────────────────────────────────────────────────────────────
    # Урок
    # ──────────────────────────────────────────────────────────────

    def _create_lesson(self, course: Course, data: dict):
        lesson, created = Lesson.objects.get_or_create(
            course=course,
            order=data["order"],
            defaults={
                "title": data["title"],
                "description": data.get("description", ""),
                "duration_minutes": data["duration_minutes"],
                "required_cefr": data["required_cefr"],
                "skill_focus": data["skill_focus"],
                "content": data.get("content", {}),
                "is_remedial": data.get("is_remedial", False),
                "is_active": True,
            }
        )

        if not created:
            self.stdout.write(self.style.WARNING(f"  Урок {lesson.order}: {lesson.title} уже существует → пропуск"))
            return

        self.stdout.write(self.style.SUCCESS(f"  Урок {lesson.order}: {lesson.title} ({'remedial' if lesson.is_remedial else 'основной'})"))

        # Привязка целей
        if "learning_objectives" in data:
            objs = self._get_or_create_objectives(data["learning_objectives"])
            lesson.learning_objectives.set(objs)

        # Задания
        for task_data in data["tasks"]:
            self._create_task(lesson, task_data)

    # ──────────────────────────────────────────────────────────────
    # Цели (LearningObjective)
    # ──────────────────────────────────────────────────────────────

    def _get_or_create_objectives(self, objectives_data: list):
        identifiers = [obj["identifier"] for obj in objectives_data]

        # Массовое создание (если не существуют)
        LearningObjective.objects.bulk_create(
            [
                LearningObjective(
                    identifier=obj["identifier"],
                    name=obj["name"],
                    cefr_level=obj["cefr_level"],
                    skill_domain=obj["skill_domain"],
                    description=obj.get("description", ""),
                )
                for obj in objectives_data
            ],
            ignore_conflicts=True
        )

        # Читаем существующие
        return list(LearningObjective.objects.filter(identifier__in=identifiers))

    # ──────────────────────────────────────────────────────────────
    # Задание (Task)
    # ──────────────────────────────────────────────────────────────

    def _create_task(self, lesson: Lesson, data: dict):
        task, created = Task.objects.get_or_create(
            lesson=lesson,
            order=data.get("order", 0),  # если order не указан — берём из списка
            defaults={
                "task_type": data["task_type"],
                "response_format": data["response_format"],
                "difficulty_cefr": data["difficulty_cefr"],
                "is_diagnostic": data.get("is_diagnostic", False),
                "content_schema_version": data.get("content_schema_version", "v1"),
                "content": data["content"],
                "is_active": True,
            }
        )

        if not created:
            self.stdout.write(f"    Задание уже существует → пропуск")
            return

        # Теги
        if "professional_tags" in data:
            tags = ProfessionalTag.objects.filter(name__in=data["professional_tags"])
            task.professional_tags.set(tags)

        # Информация о медиа (для будущей генерации)
        if "media_required" in data and data["media_required"]:
            self.stdout.write(
                self.style.NOTICE(
                    f"      Требуется медиа: {data.get('media_type', '?')} — {data.get('media_description', 'нет описания')}"
                )
            )

        self.stdout.write(f"    Задание: {task.get_task_type_display()} ({task.get_response_format_display()})")