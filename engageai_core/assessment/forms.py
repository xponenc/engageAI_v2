from django import forms

from curriculum.forms import StyledRadioSelect, StyledCheckboxSelectMultiple
from .models import QuestionInstance


class QuestionAnswerForm(forms.Form):
    """
    Форма ответа на вопрос теста.
    Включает скрытые session_id и question_instance_id.
    Django сам защитит через валидацию и clean().
    """

    session_id = forms.UUIDField(widget=forms.HiddenInput())
    question_instance_id = forms.UUIDField(widget=forms.HiddenInput())
    answer = forms.CharField(required=True)

    def __init__(self, *args, **kwargs):
        self.task = kwargs.pop("task", None)
        super().__init__(*args, **kwargs)

        if self.task:
            self._configure_answer_field(self.task)


    def _configure_answer_field(self, task):
        field_name = 'answer'
        print(task)
        print(task.response_format)
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
            self.fields[field_name] = forms.FileField(
                required=True,
                label=f"Задание № {task.order} (аудио)",
                widget=forms.ClearableFileInput(attrs={
                    'class': 'task-file',
                    'accept': 'audio/*',
                    'data-task-audio-input': task.id
                })
            )

    def clean(self):
        cleaned = super().clean()
        session_id = cleaned.get("session_id")
        qinst_id = cleaned.get("question_instance_id")

        if not session_id or not qinst_id:
            raise forms.ValidationError("Неверные данные формы.")

        # Проверяем существование
        try:
            qinst = QuestionInstance.objects.select_related("session").get(id=qinst_id)
        except QuestionInstance.DoesNotExist:
            raise forms.ValidationError("Вопрос не найден.")

        # Проверяем соответствие сессии
        if qinst.session_id != session_id:
            raise forms.ValidationError("Несоответствие вопроса тестовой сессии.")

        cleaned["qinst"] = qinst  # кладём в кэш формы
        return cleaned


