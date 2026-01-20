"""
Схемы валидации контента заданий.

ПРИНЦИПЫ:
1. Имена схем соответствуют реальному содержанию:
   - scq_v1 = Single Choice Question (одиночный выбор)
   - mcq_v1 = Multiple Choice Question (множественный выбор)
   - short_text_v1 = Short Text Response (краткий текст)
2. Каждая схема имеет четкие правила валидации
3. Поддерживается расширение без нарушения обратной совместимости
4. Схемы документированы для разработчиков

АРХИТЕКТУРНЫЕ РЕШЕНИЯ:
- Для SHORT_TEXT: поддержка множественных правильных ответов
- Для MCQ/SCQ: единообразная структура options, но разная логика выбора
- Валидация типов и диапазонов на уровне схемы
"""
from curriculum.models.content.response_format import ResponseFormat

TASK_CONTENT_SCHEMAS = {
    "scq_v1": {
        "name": "Single Choice Question v1",
        "supported_formats": [ResponseFormat.SINGLE_CHOICE],
        "required": {"prompt", "options", "correct_idx"},
        "optional": {"explanation", "hint", "difficulty"},
        "validation_rules": {
            "options": {
                "type": "list",
                "item_type": "str",
                "min_items": 2,    # Минимум 2 варианта ответа
                "max_items": 10    # Максимум 10 вариантов ответа
            },
            "correct_idx": {
                "type": "int",
                "min": 0,           # Индекс не может быть меньше 0
                "reference": "options.length - 1"  # Индекс не может превышать последний индекс в массиве
            },
            "prompt": {
                "type": "str",
                "min_length": 5     # Текст вопроса должен быть минимум 5 символов
            }
        },
        "description": "Задание с выбором одного правильного варианта из списка"
    },
    "mcq_v1": {
        "name": "Multiple Choice Question v1",
        "supported_formats": [ResponseFormat.MULTIPLE_CHOICE],
        "required": {"prompt", "options", "correct_indices"},  # ИСПРАВЛЕНО: correct_indices вместо correct_idx
        "optional": {"explanation", "hint", "min_selections", "max_selections", "difficulty"},
        "validation_rules": {
            "options": {
                "type": "list",
                "item_type": "str",
                "min_items": 3,    # Минимум 3 варианта для MCQ
                "max_items": 15    # Максимум 15 вариантов
            },
            "correct_indices": {   # ИСПРАВЛЕНО: correct_indices вместо correct_idx
                "type": "list",
                "item_type": "int",
                "min_items": 1,    # Должен быть хотя бы один правильный ответ
                "reference": "options.length"  # Все индексы должны быть в пределах длины массива
            },
            "min_selections": {
                "type": "int",
                "min": 1,          # Минимум 1 выбранный вариант
                "reference": "correct_indices.length"  # Не может превышать количество правильных ответов
            },
            "max_selections": {
                "type": "int",
                "min": 1,          # Минимум 1 выбранный вариант
                "reference": "options.length"  # Не может превышать общее количество вариантов
            },
            "prompt": {
                "type": "str",
                "min_length": 5
            }
        },
        "description": "Задание с выбором нескольких правильных вариантов из списка"
    },
    "short_text_v1": {
        "name": "Short Text Response v1",
        "supported_formats": [ResponseFormat.SHORT_TEXT],
        "required": {"prompt", "correct_answers"},
        "optional": {"correct_answers", "case_sensitive", "min_length", "max_length", "allowed_characters"},
        "validation_rules": {
            "prompt": {
                "type": "str",
                "min_length": 5
            },
            "correct_answers": {
                "type": "list",
                "item_type": "str",
                "min_items": 1     # Должен быть хотя бы один правильный ответ
            },
            "case_sensitive": {
                "type": "bool",
                "default": False   # По умолчанию нечувствительно к регистру
            },
            "min_length": {
                "type": "int",
                "min": 1,          # Минимальная длина ответа - 1 символ
                "default": 1
            },
            "max_length": {
                "type": "int",
                "min": 1,          # Максимальная длина ответа - 100 символов
                "default": 100
            }
        },
        "description": "Задание с кратким текстовым ответом (1-3 слова)"
    }
}