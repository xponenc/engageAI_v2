import json
import os
from django.core.management.base import BaseCommand
from word_helper.models import Word, Pronunciation


def is_single_word(word_str):
    return ' ' not in word_str and '-' not in word_str


class Command(BaseCommand):
    help = """
Command to link audio files from an index.jsonl file.

Expected format per line:
{
  "word": "teal",
  "file": "teal.mp3"
}

Requirements:
- Only single-word keys are processed (entries with spaces/hyphens are ignored).
- The corresponding Word entry must already exist in the database.
- Audio files must be placed in MEDIA_ROOT/word_audio/ manually or via script.

This command creates Pronunciation objects with voice_type="random".
"""

    def add_arguments(self, parser):
        parser.add_argument('audio_index_path', type=str)

    def handle(self, *args, **options):
        path = options['audio_index_path']
        if not os.path.exists(path):
            self.stderr.write(f"File not found: {path}")
            return

        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except:
                    continue

                word_str = data.get("word", "").strip().lower()
                if not is_single_word(word_str):
                    continue

                audio_file = data.get("file")
                if not audio_file:
                    continue

                try:
                    word_obj = Word.objects.get(word=clean_word)
                except Word.DoesNotExist:
                    self.stderr.write(f"Word not found in DB: {clean_word}")
                    continue

                # Создаём или обновляем произношение
                pron, created = Pronunciation.objects.update_or_create(
                    word=word_obj,
                    voice_type="random",
                    defaults={
                        "audio_file": f"word_audio/{audio_file}",
                        "source": "wiktionary_import"
                    }
                )
