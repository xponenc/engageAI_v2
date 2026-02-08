from django import template

register = template.Library()


@register.filter(name='get_item')
def get_item(dictionary, key):
    """Получить значение из словаря по ключу"""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None


@register.filter(name='get_skill')
def get_skill(snapshot, skill_name):
    """Получить значение навыка из объекта или словаря"""
    if hasattr(snapshot, skill_name):
        return getattr(snapshot, skill_name)
    elif isinstance(snapshot, dict):
        return snapshot.get(skill_name)
    return None

