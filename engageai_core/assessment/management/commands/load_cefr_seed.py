import json
import os
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from assessment.models import CEFRQuestion


class Command(BaseCommand):
    help = "Load CEFR question seed from fixtures/cefr_test_questions.json"

    def handle(self, *args, **options):
        # Путь к файлу внутри проекта
        fixture_path = os.path.join(
            settings.BASE_DIR,
            "fixtures",
            "cefr_test_questions.json",
        )

        if not os.path.exists(fixture_path):
            raise CommandError(f"Fixture not found: {fixture_path}")

        # Читаем JSON
        try:
            with open(fixture_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise CommandError(f"Failed to load JSON: {e}")

        if not isinstance(data, list):
            raise CommandError("JSON root must be a list of question objects")

        created = 0

        for item in data:
            # Валидация минимальных полей
            if "question_text" not in item:
                self.stderr.write(self.style.WARNING("Skipped item without question_text"))
                continue

            CEFRQuestion.objects.create(
                level=item.get("level", "A1"),
                type=item.get("type", "open"),
                question_text=item["question_text"],
                options=item.get("options"),
                correct_answer=item.get("correct_answer"),
                explanation=item.get("explanation")
            )

            created += 1

        self.stdout.write(
            self.style.SUCCESS(f"Loaded {created} CEFR questions from seed")
        )
