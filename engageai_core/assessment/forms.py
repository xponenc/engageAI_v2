from django import forms

from .models import QuestionInstance


class QuestionAnswerForm(forms.Form):
    """
    Форма ответа на вопрос теста.
    Включает скрытые session_id и question_instance_id.
    Django сам защитит через валидацию и clean().
    """

    session_id = forms.UUIDField(widget=forms.HiddenInput())
    question_instance_id = forms.UUIDField(widget=forms.HiddenInput())
    answer_text = forms.CharField(required=True)

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
