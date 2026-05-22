from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.core.mail import send_mail
from django.conf import settings
from .forms import RegisterForm, ContactForm


def _notify_admin_new_user(user):
    try:
        send_mail(
            subject=f"Новый пользователь в PrepMate: {user.username}",
            message=(
                f"Зарегистрировался новый пользователь.\n\n"
                f"Логин: {user.username}\n"
                f"Email: {user.email or '—'}\n"
                f"Дата: {user.date_joined.strftime('%d.%m.%Y %H:%M UTC')}"
            ),
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[settings.SUPPORT_EMAIL],
            fail_silently=True,
        )
    except Exception:
        pass


def register(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            _notify_admin_new_user(user)
            return redirect('interviews:index')
    else:
        form = RegisterForm()
    return render(request, 'users/register.html', {'form': form})


def privacy_policy(request):
    return render(request, 'users/privacy_policy.html')


def contact(request):
    initial = {}
    if request.user.is_authenticated:
        initial = {
            'name': request.user.get_full_name() or request.user.username,
            'email': request.user.email,
        }

    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data['name']
            email = form.cleaned_data['email']
            message = form.cleaned_data['message']
            username = request.user.username if request.user.is_authenticated else 'Аноним'
            body = (
                f"Имя: {name}\n"
                f"Email: {email}\n"
                f"Пользователь: {username}\n"
                f"\n{message}"
            )
            try:
                send_mail(
                    subject=f"Обращение от {username} в сервисе PrepMate",
                    message=body,
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[settings.SUPPORT_EMAIL],
                    fail_silently=False,
                )
            except Exception:
                pass
            return render(request, 'users/contact.html', {'form': ContactForm(initial=initial), 'success': True})
    else:
        form = ContactForm(initial=initial)

    return render(request, 'users/contact.html', {'form': form})
