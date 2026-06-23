from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User

# Домены одноразовой почты, через которые часто фармят бесплатные аккаунты.
_DISPOSABLE_EMAIL_DOMAINS = frozenset({
    'mailinator.com', 'guerrillamail.com', '10minutemail.com', 'tempmail.com',
    'temp-mail.org', 'yopmail.com', 'trashmail.com', '1secmail.com',
    'sharklasers.com', 'getnada.com', 'maildrop.cc', 'discard.email',
})


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
    # Honeypot: невидимое для людей поле. Простые боты заполняют все input'ы
    # формы автоматически, человек его не видит и не трогает.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'autocomplete': 'off',
        'tabindex': '-1',
    }))

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('Ошибка валидации формы.')
        return ''

    def clean_email(self):
        email = self.cleaned_data.get('email')
        domain = email.rsplit('@', 1)[-1].lower() if email and '@' in email else ''
        if domain in _DISPOSABLE_EMAIL_DOMAINS:
            raise forms.ValidationError('Временные почтовые адреса не поддерживаются.')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('Пользователь с таким email уже зарегистрирован.')
        return email

