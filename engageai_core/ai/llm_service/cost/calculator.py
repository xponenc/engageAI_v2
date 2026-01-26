# engageai_core/ai/llm/cost/calculator.py
"""
Модуль расчёта стоимости использования LLM.

Основные принципы:
- Разные калькуляторы для разных провайдеров (OpenAI, Anthropic, локальные = 0)
- Цены хранятся в одном месте и легко обновляются
- Поддержка разных типов затрат: токены input/output, изображения, TTS (символы)
- Возможность расширения на другие провайдеры в будущем
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from ..interfaces import CostCalculator


logger = logging.getLogger(__name__)


class OpenAICostCalculator(CostCalculator):
    """
    Калькулятор стоимости для моделей OpenAI (2024–2026 цены).

    Источник: официальная страница OpenAI pricing (обновляется вручную)
    https://openai.com/api/pricing/

    Формат цен: (input $/1M tokens, output $/1M tokens)
    """

    # Актуальные цены на январь 2026 (пример — уточняйте на момент использования)
    # Цены указаны в долларах за 1 миллион токенов
    PRICING: Dict[str, tuple[float, float]] = {
        # o-series (reasoning models)
        "o1":                     (15.00, 60.00),
        "o1-mini":                (3.00,  12.00),
        "o1-pro":                 (150.00, 600.00),   # если появится
        "o3-mini":                (1.10,  4.40),
        "o3":                     (2.00,  8.00),

        # GPT-4o family
        "gpt-4o":                 (5.00,  15.00),     # 2024-08 версия
        "gpt-4o-2024-08-06":      (2.50,  10.00),
        "gpt-4o-mini":            (0.150, 0.600),
        "gpt-4o-mini-2024-07-18": (0.150, 0.600),

        # GPT-4.1 / GPT-4 Turbo (если всё ещё используются)
        "gpt-4-turbo":            (10.00, 30.00),
        "gpt-4":                  (30.00, 60.00),

        # Старые / дешёвые
        "gpt-3.5-turbo":          (0.50,  1.50),
        "gpt-3.5-turbo-0125":     (0.50,  1.50),

        # Vision / multimodal input
        # Для gpt-4o и gpt-4o-mini цены на изображения считаются отдельно
        # Здесь указаны только текстовые токены

        # TTS и Whisper (за 1M символов / 1M секунд)
        "tts-1":                  (15.00, 0.00),      # ~$15 за миллион символов
        "tts-1-hd":               (30.00, 0.00),

        # DALL·E (цена за изображение, не за токены)
        "dall-e-3":               (0.040, 0.00),      # standard 1024×1024
        "dall-e-3-hd":            (0.080, 0.00),
        "dall-e-2":               (0.020, 0.00),      # 1024×1024
    }

    # ─── FALLBACK ДЛЯ НЕИЗВЕСТНЫХ МОДЕЛЕЙ ───
    UNKNOWN_MODEL_PRICE = (150.00, 600.00)  # o1-pro — самая дорогая известная

    def __init__(self, default_model: str = "gpt-4o-mini"):
        self.default_model = default_model

    def calculate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int = 0,
        extra_chars: int = 0,          # для TTS — количество символов
        image_count: int = 0,
        image_quality: str = "standard",
    ) -> float:
        """
        Рассчитывает стоимость одного запроса в USD.

        Args:
            model: имя модели (gpt-4o, gpt-4o-mini, tts-1, dall-e-3, ...)
            input_tokens: количество входных токенов
            output_tokens: количество выходных токенов
            extra_chars: дополнительные символы (особенно для TTS)
            image_count: количество сгенерированных изображений
            image_quality: "standard" / "hd" для DALL·E 3

        Returns:
            Стоимость в долларах США (с точностью до 6 знаков)
        """
        model = model.lower()

        # 1. TTS — стоимость за символы
        if model.startswith("tts-"):
            price_per_m_chars = self.PRICING.get(model, (15.00, 0.00))[0]
            cost = (extra_chars / 1_000_000) * price_per_m_chars
            return round(cost, 6)

        # 2. Image generation — фиксированная цена за картинку
        if model.startswith("dall-e-"):
            if model == "dall-e-3":
                base_price = 0.040 if image_quality == "standard" else 0.080
            elif model == "dall-e-2":
                base_price = 0.020  # 1024×1024
            else:
                base_price = 0.040

            return round(image_count * base_price, 6)

        # 3. Обычные текстовые / chat модели
        if model in self.PRICING:
            input_price, output_price = self.PRICING[model]
        else:
            input_price, output_price = self.UNKNOWN_MODEL_PRICE
            logger.warning(
                "НЕИЗВЕСТНАЯ МОДЕЛЬ OpenAI: %r\n"
                "→ fallback на САМУЮ ДОРОГУЮ цену ($150/$600 за 1M токенов)\n"
                "→ ОБНОВИТЕ PRICING в OpenAICostCalculator!\n"
                "Текущий расчёт: input=%d → $%.4f, output=%d → $%.4f",
                model, input_tokens, (input_tokens / 1e6) * input_price,
                output_tokens, (output_tokens / 1e6) * output_price
            )

        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price

        total = input_cost + output_cost
        return round(total, 6)


class ZeroCostCalculator(CostCalculator):
    """
    Калькулятор для всех локальных моделей и тестовых сред.
    Стоимость всегда = 0.
    """

    def calculate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int = 0,
        extra_chars: int = 0,
        image_count: int = 0,
        image_quality: str = "standard",
    ) -> float:
        return 0.0


# Удобные экземпляры для быстрого использования
openai_cost_calculator = OpenAICostCalculator(default_model="gpt-4o-mini")
zero_cost_calculator   = ZeroCostCalculator()