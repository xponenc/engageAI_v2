from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views import View
from .models import Word
import re


class WordDetailView(LoginRequiredMixin, View):
    def get(self, request, word):
        # Очистка от пунктуации
        clean_word = re.sub(r'[^\w]', '', word).lower()
        if not clean_word:
            return JsonResponse({"error": "Invalid word"}, status=400)

        try:
            word_obj = Word.objects.prefetch_related('senses', 'forms').get(word=clean_word)
        except Word.DoesNotExist:
            # Попробуем найти по canonical_form
            try:
                word_obj = Word.objects.prefetch_related('senses', 'forms').get(canonical_form=clean_word)
            except Word.DoesNotExist:
                return JsonResponse({"error": "Word not found"}, status=404)

        data = {
            "word": word_obj.word,
            "canonical_form": word_obj.canonical_form,
            "pos": word_obj.pos,
            "ipa": word_obj.ipa,
            "senses": [
                {
                    "gloss": s.gloss,
                    "categories": s.categories,
                    "raw_tags": s.raw_tags,
                }
                for s in word_obj.senses.all()
            ],
            "forms": [
                {"form": f.form, "tags": f.tags}
                for f in word_obj.forms.all()
            ],
            "pronunciations": [
                {
                    "voice_type": p.voice_type,
                    "audio_url": p.audio_file.url if p.audio_file else None,
                    "source": p.source,
                }
                for p in word_obj.pronunciations.all()
            ],
        }
        return JsonResponse(data)
