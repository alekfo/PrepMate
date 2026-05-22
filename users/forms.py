from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User


class ContactForm(forms.Form):
    name = forms.CharField(label='Имя', max_length=150)
    email = forms.EmailField(label='Email')
    message = forms.CharField(
        label='Описание проблемы',
        widget=forms.Textarea(attrs={'rows': 5}),
    )


class RegisterForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'placeholder': 'example@mail.com'}),
        label='Email',
    )
    privacy_policy = forms.BooleanField(
        required=True,
        error_messages={'required': 'Необходимо принять политику конфиденциальности для регистрации.'},
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('Пользователь с таким email уже зарегистрирован.')
        return email

