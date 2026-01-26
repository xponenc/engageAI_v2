# curriculum/decorators.py

from functools import wraps
import logging
import traceback

from django.utils import timezone

from llm_logger.models import LogLLMRequest

logger = logging.getLogger(__name__)

def log_llm_request(user=None, course=None, lesson=None):
    """
    Decorator для автоматического логгирования LLM-запросов.
    Ловит вызов LLM, считает токены/стоимость, сохраняет в модель.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = timezone.now()
            try:
                result = func(*args, **kwargs)
                duration = (timezone.now() - start).total_seconds()
                metadata = kwargs.get('metadata', {})
                metadata['duration_sec'] = duration

                # Получаем из llm_factory (предполагаем, что результат содержит токены/стоимость)
                tokens_in = result.get('tokens_in', 0)  # из твоего модуля подсчёта
                tokens_out = result.get('tokens_out', 0)
                cost_in = result.get('cost_in', 0)
                cost_out = result.get('cost_out', 0)
                cost_total = result.get('cost_total', 0)
                model_name = result.get('model', 'gpt-4o-mini')
                prompt = result.get('prompt', '')  # или args, если prompt в аргументах
                response = result.get('response', '')

                LogLLMRequest.objects.create(
                    model_name=model_name,
                    prompt=prompt,
                    response=response,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_in=cost_in,
                    cost_out=cost_out,
                    cost_total=cost_total,
                    metadata=metadata,
                    user=user or kwargs.get('user') or args[0].user if hasattr(args[0], 'user') else None,
                    course=course or kwargs.get('course'),
                    lesson=lesson or kwargs.get('lesson'),
                    status='SUCCESS'
                )
                return result
            except Exception as e:
                LogLLMRequest.objects.create(
                    # ... те же поля, но status='ERROR', metadata['error'] = str(e)
                )
                logger.error(f"LLM error: {str(e)}", exc_info=True)
                raise

        return wrapper
    return decorator