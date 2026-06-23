import ipaddress
import json
import logging

from django.shortcuts import render, redirect
from django.contrib.auth import login, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import RegisterForm, ContactForm
from .models import Payment

_YOOKASSA_NETWORKS = [
    ipaddress.ip_network('185.71.76.0/27'),
    ipaddress.ip_network('185.71.77.0/27'),
    ipaddress.ip_network('77.75.153.0/25'),
    ipaddress.ip_network('77.75.154.128/25'),
    ipaddress.ip_network('2a02:5180::/32'),
]
_YOOKASSA_SINGLE_IPS = {
    ipaddress.ip_address('77.75.156.11'),
    ipaddress.ip_address('77.75.156.35'),
}


def _is_yookassa_ip(request):
    ip_str = request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', '')
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip in _YOOKASSA_SINGLE_IPS or any(ip in net for net in _YOOKASSA_NETWORKS)

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


_REGISTER_RATE_LIMIT = 5  # попыток регистрации с одного IP за час


def register(request):
    if request.method == 'POST':
        ip = request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', '')
        rate_key = f'register_attempts_{ip}'
        attempts = cache.get(rate_key, 0)
        if attempts >= _REGISTER_RATE_LIMIT:
            logger.warning("Registration rate limit hit for ip=%s", ip)
            messages.error(request, 'Слишком много попыток регистрации с вашего адреса. Попробуйте позже.')
            return render(request, 'users/register.html', {'form': RegisterForm()})
        cache.set(rate_key, attempts + 1, timeout=3600)

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


@login_required
def subscription(request):
    u = request.user
    if u.is_premium:
        current_plan = 'premium'
    elif u.is_subscribed:
        current_plan = 'subscribed'
    else:
        current_plan = 'free'
    return render(request, 'users/subscription.html', {
        'current_plan': current_plan,
        'subscription_expires_at': u.subscription_expires_at,
    })


@login_required
@require_POST
def create_payment(request):
    from .services import create_yookassa_payment

    plan = request.POST.get('plan')
    if plan not in ('subscribed', 'premium'):
        return HttpResponseBadRequest('Неверный план.')

    # Не даём купить более низкий план
    u = request.user
    if u.is_premium:
        messages.error(request, 'У вас уже активен Премиум план.')
        return redirect('users:subscription')
    if u.is_subscribed and plan == 'subscribed':
        messages.error(request, 'У вас уже активна базовая подписка.')
        return redirect('users:subscription')

    return_url = request.build_absolute_uri('/users/payment/return/')

    try:
        _payment_db, confirmation_url = create_yookassa_payment(u, plan, return_url)
    except Exception as e:
        logger.error("YooKassa payment creation failed: user=%s plan=%s error=%s", u.username, plan, e)
        messages.error(request, 'Не удалось создать платёж. Попробуйте позже.')
        return redirect('users:subscription')

    return redirect(confirmation_url)


@csrf_exempt
@require_POST
def payment_webhook(request):
    from .services import activate_subscription

    if not _is_yookassa_ip(request):
        logger.warning("Webhook from unknown IP: %s", request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR'))
        return HttpResponse('ok')  # возвращаем 200 чтобы не раскрывать информацию

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return HttpResponseBadRequest('Invalid JSON')

    event = data.get('event')
    obj = data.get('object', {})
    yk_payment_id = obj.get('id')
    status = obj.get('status')

    logger.info("YooKassa webhook: event=%s yk_id=%s status=%s", event, yk_payment_id, status)

    if event != 'payment.succeeded' or status != 'succeeded':
        return HttpResponse('ok')

    try:
        payment = Payment.objects.select_related('user').get(yookassa_payment_id=yk_payment_id)
    except Payment.DoesNotExist:
        logger.warning("Webhook: payment not found yk_id=%s", yk_payment_id)
        return HttpResponse('ok')

    if payment.status == Payment.STATUS_SUCCEEDED:
        # Уже обработан (идемпотентность)
        return HttpResponse('ok')

    payment.status = Payment.STATUS_SUCCEEDED
    payment.save(update_fields=['status'])

    activate_subscription(payment.user, payment)

    return HttpResponse('ok')


@login_required
def payment_return(request):
    """Страница, на которую YooKassa редиректит после оплаты."""
    u = request.user
    # Проверяем, есть ли у пользователя активная подписка (webhook мог уже сработать)
    if u.is_subscribed or u.is_premium:
        return render(request, 'users/payment_success.html')
    return render(request, 'users/payment_pending.html')


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