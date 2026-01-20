from django import template

register = template.Library()


@register.filter
def field_for_task(form, task_id):
    field_name = f'task_{task_id}'
    return form.fields.get(field_name) and form[field_name]
