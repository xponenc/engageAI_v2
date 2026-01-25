import json
import os

from django.core.files import File
from django.core.management.base import BaseCommand

from word_helper.models import Word, Pronunciation


def is_single_word(word_str: str) -> bool:
    return ' ' not in word_str and '-' not in word_str


class Command(BaseCommand):
    help = "Link audio files from a jsonl index to Word pronunciations"

    def add_arguments(self, parser):
        parser.add_argument('audio_index_path', type=str)

    def handle(self, *args, **options):
        index_path = options['audio_index_path']

        if not os.path.exists(index_path):
            self.stderr.write(self.style.ERROR(f"File not found: {index_path}"))
            return

        base_dir = os.path.dirname(index_path)
        audio_dir = os.path.join(base_dir, 'download')

        if not os.path.isdir(audio_dir):
            self.stderr.write(self.style.ERROR(f"Audio dir not found: {audio_dir}"))
            return

        created_count = 0
        updated_count = 0
        skipped_count = 0

        with open(index_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    skipped_count += 1
                    continue

                word_str = data.get("word", "").strip().lower()
                if not is_single_word(word_str):
                    skipped_count += 1
                    continue

                filename = data.get("file")
                if not filename:
                    skipped_count += 1
                    continue

                audio_path = os.path.join(audio_dir, filename)
                if not os.path.exists(audio_path):
                    self.stderr.write(f"Audio file not found: {audio_path}")
                    skipped_count += 1
                    continue

                try:
                    word_obj = Word.objects.get(word=word_str)
                except Word.DoesNotExist:
                    self.stderr.write(f"Word not found in DB: {word_str}")
                    skipped_count += 1
                    continue

                pron, created = Pronunciation.objects.get_or_create(
                    word=word_obj,
                    voice_type="random",
                    defaults={"source": "wiktionary_import"},
                )

                with open(audio_path, 'rb') as audio_fp:
                    pron.audio_file.save(filename, File(audio_fp), save=True)

                if created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created: {created_count}, Updated: {updated_count}, Skipped: {skipped_count}"
            )
        )
