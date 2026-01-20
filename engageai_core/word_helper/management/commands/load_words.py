# apps/word_helper/management/commands/load_words.py
import json
import os
from django.core.management.base import BaseCommand
from word_helper.models import Word, WordSense, WordForm


def is_single_word(word_str):
    return ' ' not in word_str and '-' not in word_str and len(word_str) > 0


class Command(BaseCommand):
    help = """
Command to load lexical data from a JSONL file in the following format:

Each line is a JSON object with these possible fields:
- "word": str — the surface form (e.g., "dismembered")
- "lang_code": str — language code (e.g., "en")
- "pos": str — part of speech (e.g., "verb", "noun")
- "forms": list of dicts — alternative forms with tags
    - "form": str
    - "tags": list[str] (e.g., ["past", "participle"])
    - "raw_tags": list[str] (optional)
- "senses": list of dicts
    - "glosses": list[str] — definitions or translations
    - "categories": list[str]
    - "raw_tags": list[str] (optional)
- "sounds": list of dicts (optional)
    - "ipa": str — phonetic transcription
    - "audio": str — filename (not used here; handled by load_audio)

Only single-word entries (no spaces or hyphens) are imported.
Multi-word expressions (e.g., "herring gull") are skipped.
"""

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str)

    def handle(self, *args, **options):
        file_path = options['file_path']
        if not os.path.exists(file_path):
            self.stderr.write(f"File not found: {file_path}")
            return

        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                word_str = data.get("word", "").strip().lower()
                if not is_single_word(word_str):
                    continue

                # Извлекаем canonical form
                canonical = None
                for form in data.get("forms", []):
                    if "canonical" in form.get("tags", []) or form.get("form") == word_str:
                        canonical = form["form"]
                        break
                if not canonical:
                    canonical = word_str

                # Создаём или получаем слово
                word_obj, created = Word.objects.get_or_create(
                    word=word_str,
                    defaults={
                        "canonical_form": canonical.lower(),
                        "pos": data.get("pos", ""),
                        "lang_code": data.get("lang_code", "en"),
                    }
                )

                # IPA и аудио пока не из этого файла — обновим позже
                # Но если есть sounds → сохраняем IPA
                for sound in data.get("sounds", []):
                    if "ipa" in sound and not word_obj.ipa:
                        word_obj.ipa = sound["ipa"]
                        word_obj.save()

                # Смыслы (senses)
                for sense in data.get("senses", []):
                    glosses = sense.get("glosses", [])
                    for gloss in glosses:
                        WordSense.objects.get_or_create(
                            word=word_obj,
                            gloss=gloss,
                            defaults={
                                "raw_tags": sense.get("raw_tags", []),
                                "categories": sense.get("categories", []),
                            }
                        )

                # Формы
                for form_data in data.get("forms", []):
                    form_text = form_data.get("form", "").lower()
                    if not is_single_word(form_text):
                        continue
                    WordForm.objects.get_or_create(
                        word=word_obj,
                        form=form_text,
                        defaults={
                            "tags": form_data.get("tags", []),
                            "raw_tags": form_data.get("raw_tags", []),
                        }
                    )
