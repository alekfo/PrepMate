import logging

from django.shortcuts import render, redirect
from django.contrib.auth import login, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core import signing
from django.core.mail import send_mail
from django.conf import settings
from .forms import RegisterForm, ContactForm

logger = logging.getLogger(__name__)


def _send_confirmation_email(user, request):
    token = signing.dumps({'uid': user.pk}, salt='email-confirm')
    confirm_url = request.build_absolute_uri(f'/users/confirm-email/?token={token}')
    send_mail(
        subject='Подтверждение email — PrepStats',
        message=(
            f'Здравствуйте, {user.username}!\n\n'
            f'Для подтверждения адреса электронной почты перейдите по ссылке:\n'
            f'{confirm_url}\n\n'
            f'Ссылка действительна 24 часа.\n'
            f'Если вы не регистрировались в PrepStats — проигнорируйте письмо.'
        ),
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[user.email],
        fail_silently=False,
    )


def _notify_admin_new_user(user):
    try:
        send_mail(
            subject=f"Новый пользователь в PrepStats: {user.username}",
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
            logger.info("New user registered: %s <%s>", user.username, user.email)
            _notify_admin_new_user(user)
            try:
                _send_confirmation_email(user, request)
                messages.info(
                    request,
                    f'Письмо с подтверждением email отправлено на {user.email}. Проверьте почту.',
                )
            except Exception as e:
                logger.warning("Confirmation email failed for user=%s: %s", user.username, e)
            return redirect('interviews:index')
    else:
        form = RegisterForm()
    return render(request, 'users/register.html', {'form': form})


@login_required
def settings_page(request):
    return render(request, 'users/settings.html')


@login_required
def send_confirmation(request):
    if request.method != 'POST':
        return redirect('users:settings')
    user = request.user
    if not user.email:
        messages.error(request, 'Укажите email в профиле перед подтверждением.')
        return redirect('users:settings')
    if user.email_confirmed:
        return redirect('users:settings')
    try:
        _send_confirmation_email(user, request)
        messages.success(request, f'Письмо с подтверждением отправлено на {user.email}.')
        logger.info("Confirmation email sent to user=%s <%s>", user.username, user.email)
    except Exception as e:
        logger.error("Confirmation email failed for user=%s: %s", user.username, e)
        messages.error(request, 'Не удалось отправить письмо. Проверьте настройки email.')
    return redirect('users:settings')


def confirm_email(request):
    token = request.GET.get('token', '')
    try:
        data = signing.loads(token, salt='email-confirm', max_age=86400)
        User = get_user_model()
        user = User.objects.get(pk=data['uid'])
        user.email_confirmed = True
        user.save(update_fields=['email_confirmed'])
        logger.info("Email confirmed for user=%s", user.username)
        messages.success(request, 'Email успешно подтверждён!')
    except signing.SignatureExpired:
        logger.warning("Expired email confirmation token for token=%.20s…", token)
        messages.error(request, 'Ссылка истекла. Запросите новое письмо.')
    except (signing.BadSignature, Exception) as e:
        logger.warning("Invalid email confirmation token: %s", e)
        messages.error(request, 'Недействительная ссылка подтверждения.')
    return redirect('users:settings')


def privacy_policy(request):
    return render(request, 'users/privacy_policy.html')


def public_offer(request):
    return render(request, 'users/public_offer.html')


def about(request):
    return render(request, 'users/about.html')


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
                    subject=f"Обращение от {username} в сервисе PrepStats",
                    message=body,
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[settings.SUPPORT_EMAIL],
                    fail_silently=False,
                )
                logger.info("Contact form submitted by %s <%s>", username, email)
            except Exception as e:
                logger.error("Contact email failed for %s <%s>: %s", username, email, e)
            return render(request, 'users/contact.html', {'form': ContactForm(initial=initial), 'success': True})
    else:
        form = ContactForm(initial=initial)

    return render(request, 'users/contact.html', {'form': form})