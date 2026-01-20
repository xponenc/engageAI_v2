from django import forms
from django.utils.safestring import mark_safe


class StyledRadioSelect(forms.RadioSelect):
    def render(self, name, value, attrs=None, renderer=None):
        if attrs is None:
            attrs = {}

        choice_index = 0
        output = []
        for option_value, option_label in self.choices:
            option_value_str = str(option_value)
            checked = option_value_str == str(value or '')
            option_id = f"{attrs.get('id', 'id')}_{choice_index}"

            html = f'''
            <label class="task-option task-option--radio">
                <input type="radio"
                       name="{name}"
                       value="{option_value_str}"
                       id="{option_id}"
                       {'checked' if checked else ''}
                       {'disabled' if attrs.get("disabled", False) else ''}
                       {'required' if self.is_required else ''}>
                <span class="task-option__text">{option_label}</span>
            </label>
            '''
            output.append(html.strip())
            choice_index += 1

        return mark_safe('\n'.join(output))


class StyledCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    def render(self, name, value, attrs=None, renderer=None):
        if attrs is None:
            attrs = {}

        value = value or []
        value = [str(v) for v in value]  # приводим к строкам для сравнения

        choice_index = 0
        options = []
        for option_value, option_label in self.choices:
            checked = str(option_value) in value
            option_id = f"{attrs.get('id', 'id')}_{choice_index}"

            html = f'''
            <label class="task-option task-option--checkbox">
                <input type="checkbox"
                       name="{name}"
                       value="{option_value}"
                       {'checked' if checked else ''}
                       {'disabled' if attrs.get('disabled') else ''}
                       id="{option_id}">
                <span class="task-option__text">{option_label}</span>
            </label>
            '''
            options.append(html)
            choice_index += 1

        return mark_safe('\n'.join(options))


class LessonTasksForm(forms.Form):
    """
    Простая динамическая форма для валидации ответов на задания урока.

    Особенности:
    - Создает поля только для активных, невыполненных заданий
    - Минимальная валидация (только required)
    - Не содержит сложной бизнес-логики
    - Используется только для проверки form.is_valid()
    """

    def __init__(self, *args, **kwargs):
        self.lesson = kwargs.pop('lesson', None)
        self.completed_task_ids = kwargs.pop('completed_task_ids', set())
        super().__init__(*args, **kwargs)

        if self.lesson:
            self._add_task_fields()

    def _add_task_fields(self):
        tasks = self.lesson.tasks.filter(is_active=True).order_by('order')

        for task in tasks:
            if task.id in self.completed_task_ids:
                continue

            field_name = f'task_{task.id}'

            if task.response_format == 'single_choice':
                options = task.content.get('options', [])
                choices = [(o, o) for o in options]

                self.fields[field_name] = forms.ChoiceField(
                    choices=choices,
                    widget=StyledRadioSelect(),
                    required=True,
                    label=f"Задание № {task.order}",
                )
                self.fields[field_name].widget.attrs.update({'class': 'task-radio-group'})

            elif task.response_format == 'multiple_choice':
                options = task.content.get('options', [])
                choices = [(o, o) for o in options]
                self.fields[field_name] = forms.MultipleChoiceField(
                    choices=choices,
                    widget=StyledCheckboxSelectMultiple(attrs={'class': 'task-checkbox-group'}),
                    required=True,
                    label=f"Задание № {task.order}"
                )

            elif task.response_format == 'short_text':
                self.fields[field_name] = forms.CharField(
                    required=True,
                    label=f"Задание № {task.order}",
                    widget=forms.TextInput(attrs={
                        'class': 'task-input',
                        'placeholder': 'Введите ответ...'
                    })

                )

            elif task.response_format == 'free_text':
                self.fields[field_name] = forms.CharField(
                    required=True,
                    label=f"Задание № {task.order}",
                    widget=forms.Textarea(attrs={
                        'class': 'task-textarea',
                        'rows': 4,
                        'placeholder': 'Напишите ваш ответ здесь...'
                    })
                )

            elif task.response_format == 'audio':
                # Важно: имя поля — task_{id}_audio, чтобы совпадало с шаблоном
                audio_field_name = f'task_{task.id}_audio'
                self.fields[audio_field_name] = forms.FileField(
                    required=True,
                    label=f"Задание № {task.order} (аудио)",
                    widget=forms.ClearableFileInput(attrs={
                        'class': 'task-file',
                        'accept': 'audio/*',
                        'data-task-audio-input': task.id
                    })
                )
