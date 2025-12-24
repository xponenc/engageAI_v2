# curriculum/infrastructure/validation/task_schemas.py
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
                "min_items": 2,
                "max_items": 10
            },
            "correct_idx": {
                "type": "int",
                "min": 0,
                "reference": "options.length - 1"
            },
            "prompt": {
                "type": "str",
                "min_length": 5
            }
        },
        "description": "Задание с выбором одного правильного варианта из списка"
    },
    "mcq_v1": {
        "name": "Multiple Choice Question v1",
        "supported_formats": [ResponseFormat.MULTIPLE_CHOICE],
        "required": {"prompt", "options", "correct_indices"},
        "optional": {"explanation", "hint", "min_selections", "max_selections", "difficulty"},
        "validation_rules": {
            "options": {
                "type": "list",
                "item_type": "str",
                "min_items": 3,
                "max_items": 15
            },
            "correct_indices": {
                "type": "list",
                "item_type": "int",
                "min_items": 1,
                "reference": "options.length"
            },
            "min_selections": {
                "type": "int",
                "min": 1,
                "reference": "correct_indices.length"
            },
            "max_selections": {
                "type": "int",
                "min": 1,
                "reference": "options.length"
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
        "required": {"prompt"},
        "optional": {"correct_answers", "case_sensitive", "min_length", "max_length", "allowed_characters"},
        "validation_rules": {
            "prompt": {
                "type": "str",
                "min_length": 5
            },
            "correct_answers": {
                "type": "list",
                "item_type": "str",
                "min_items": 1
            },
            "case_sensitive": {
                "type": "bool",
                "default": False
            },
            "min_length": {
                "type": "int",
                "min": 1,
                "default": 1
            },
            "max_length": {
                "type": "int",
                "min": 1,
                "default": 100
            }
        },
        "description": "Задание с кратким текстовым ответом (1-3 слова)"
    }
}