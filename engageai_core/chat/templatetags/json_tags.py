import re
from django import template

register = template.Library()


@register.filter
def is_dict(value):
    return isinstance(value, dict)


@register.filter
def is_list(value):
    return isinstance(value, list)


@register.filter
def is_url(value):
    # Проверяем, является ли строка валидным URL
    url_pattern = re.compile(
        r'^(?:http|ftp)s?://'  # http:// или https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # домен
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP
        r'(?::\d+)?'  # порт (опционально)
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return bool(url_pattern.match(str(value)))
