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


@register.filter
def initials(user, default="—"):
    """
    Возвращает инициалы пользователя:
      Иван Петров → I. P.
      Иван → I.
      — Петров → P.
      нет данных → default
    """
    if not user:
        return default

    first = (getattr(user, "first_name", "") or "").strip()
    last = (getattr(user, "last_name", "") or "").strip()

    # Собираем инициалы только из непустых значений
    parts = []
    if first:
        parts.append(first[0] + ".")
    if last:
        parts.append(last[0] + ".")

    if parts:
        return "".join(parts)

    # Вообще нет ни имени ни фамилии
    return default
