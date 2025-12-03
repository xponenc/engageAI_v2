import json
from datetime import datetime

from django import template

register = template.Library()


@register.filter
def get(dictionary, key):
    return dictionary.get(key)


@register.filter
def getlist(qs, key):
    return qs.getlist(key)


@register.filter
def as_iso_date(value):
    try:
        # Пробуем DD.MM.YYYY
        if '.' in value:
            dt = datetime.strptime(value, "%d.%m.%Y")
        else:
            # Если уже ISO — пропускаем
            return value
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


@register.filter
def split(value, sep=","):
    return value.split(sep)


@register.filter
def json_prettify(value):
    try:
        return json.dumps(value, indent=4, ensure_ascii=False)
    except Exception:
        return str(value)