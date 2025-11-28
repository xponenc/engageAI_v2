from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.forms import model_to_dict, fields_for_model
from django.http import QueryDict

from .models import Profile


class UserRegistrationForm(UserCreationForm):
    """
    Форма регистрации
    username установится равным email
    """

    class Meta:
        model = User
        fields = ('email', )

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')

        if email:
            # Проверяем, существует ли пользователь с таким email (который станет username)
            if User.objects.filter(username=email).exists():
                raise ValidationError({
                    'email': "Пользователь с таким email уже зарегистрирован."
                })

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["email"]
        user.is_active = False
        if commit:
            user.save()
        return user


class UserProfileForm(forms.ModelForm):
    first_name = forms.CharField(label='Имя', max_length=50)
    last_name = forms.CharField(label='Фамилия', max_length=50)

    class Meta:
        model = Profile
        fields = ('last_name', 'first_name', 'birthdate', 'phone', 'location', 'avatar', 'bio',)



class UserProfileUpdateForm(forms.ModelForm):
    """Форма редактирования профиля Пользователя(User)"""
    first_name = forms.CharField(label='Имя', max_length=50)
    last_name = forms.CharField(label='Фамилия', max_length=50)

    class Meta:
        model = Profile
        fields = ('birthdate', 'phone', 'avatar', 'location')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            user = self.instance.user

            if user:
                self.fields['first_name'].initial = user.first_name
                self.fields['last_name'].initial = user.last_name


class FeedbackForm(forms.Form):
    """Форма отправки сообщения"""
    name = forms.CharField(label='Имя', max_length=50)
    email = forms.EmailField(label='электронная почта', )
    message = forms.CharField(label="сообщение", max_length=2000, widget=forms.Textarea)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ('name', 'email', ):
            self.fields[field].widget.attrs.update({
                'class': 'custom-field__input',
                'placeholder': ' '
            })
        self.fields['message'].widget.attrs.update({
            'class': 'custom-field__input custom-field__input_wide custom-field__input_textarea',
            'placeholder': ' ',
        })

    def save(self, commit=True):
        # Сначала сохраняем профиль (модель Profile)
        profile = super().save(commit=False)

        # Обновляем данные пользователя (модель User)
        profile.user.first_name = self.cleaned_data['first_name']
        profile.user.last_name = self.cleaned_data['last_name']

        if commit:
            profile.user.save()
            profile.save()

        return profile