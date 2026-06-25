import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from yookassa import Configuration, Payment as YKPayment

logger = logging.getLogger(__name__)

PLAN_DESCRIPTIONS = {
    'subscribed': 'Базовая подписка PrepStats на 30 дней',
    'premium': 'Премиум-подписка PrepStats на 30 дней',
}


def _configure_yookassa():
    """Инициализирует SDK YooKassa учётными данными из settings."""
    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY


def create_yookassa_payment(user, plan, return_url):
    """Создаёт платёж в YooKassa и возвращает (yookassa_payment_id, confirmation_url)."""
    from .models import Payment

    _configure_yookassa()

    amount = settings.SUBSCRIPTION_PRICES[plan]
    description = PLAN_DESCRIPTIONS[plan]
    idempotency_key = str(uuid.uuid4())

    yk_payment = YKPayment.create({
        'amount': {
            'value': amount,
            'currency': 'RUB',
        },
        'confirmation': {
            'type': 'redirect',
            'return_url': return_url,
        },
        'capture': True,
        'description': description,
        'metadata': {
            'user_id': str(user.pk),
            'plan': plan,
        },
        # Чек через «Мой налог» настраивается в ЛК YooKassa (интеграция для самозанятых).
        # После успешного платежа YooKassa автоматически регистрирует доход и отправляет
        # чек покупателю, если интеграция с «Мой налог» активирована.
    }, idempotency_key)

    payment_db = Payment.objects.create(
        user=user,
        plan=plan,
        amount=amount,
        yookassa_payment_id=yk_payment.id,
        status=Payment.STATUS_PENDING,
    )

    logger.info(
        "Payment created: user=%s plan=%s yk_id=%s",
        user.username, plan, yk_payment.id,
    )
    return payment_db, yk_payment.confirmation.confirmation_url


def activate_subscription(user, payment):
    """Активирует подписку после успешной оплаты."""
    from .models import Subscription

    plan = payment.plan

    # Деактивируем все предыдущие активные подписки
    user.subscriptions.filter(is_active=True).update(is_active=False)

    now = timezone.now()
    sub = Subscription.objects.create(
        user=user,
        payment=payment,
        plan=plan,
        expires_at=now + timedelta(days=30),
        is_active=True,
    )

    user.is_subscribed = True
    user.is_premium = (plan == 'premium')
    user.subscription_expires_at = sub.expires_at
    user.interviews_limit_per_day = settings.SUBSCRIPTION_LIMITS[plan]
    user.save(update_fields=[
        'is_subscribed', 'is_premium',
        'subscription_expires_at', 'interviews_limit_per_day',
    ])

    logger.info(
        "Subscription activated: user=%s plan=%s expires=%s",
        user.username, plan, sub.expires_at,
    )
    _send_subscription_activated_email(user, sub)
    return sub


def _send_subscription_activated_email(user, sub):
    """Отправляет пользователю письмо об успешной активации подписки. fail_silently."""
    plan_name = dict(sub.PLAN_CHOICES).get(sub.plan, sub.plan)
    try:
        send_mail(
            subject='Подписка PrepStats активирована',
            message=(
                f'Здравствуйте, {user.username}!\n\n'
                f'Ваша подписка «{plan_name}» успешно оформлена.\n'
                f'Доступ открыт до {sub.expires_at.strftime("%d.%m.%Y")}.\n\n'
                f'Чек от «Мой налог» придёт отдельным письмом от ФНС.\n\n'
                f'Перейти в PrepStats:\n'
                f'https://prepstats.pro\n\n'
                f'С уважением,\nКоманда PrepStats'
            ),
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[user.email],
            fail_silently=True,
        )
        logger.info("Activation email sent to user=%s", user.username)
    except Exception as e:
        logger.error("Failed to send activation email to user=%s: %s", user.username, e)


def deactivate_user_subscription(user):
    """Сбрасывает подписку пользователя (вызывается management command'ом)."""
    user.is_subscribed = False
    user.is_premium = False
    user.subscription_expires_at = None
    user.interviews_limit_per_day = settings.SUBSCRIPTION_LIMITS['free']
    user.save(update_fields=[
        'is_subscribed', 'is_premium',
        'subscription_expires_at', 'interviews_limit_per_day',
    ])
    logger.info("Subscription deactivated: user=%s", user.username)


def send_subscription_expired_email(user):
    """Уведомляет пользователя об истечении подписки."""
    try:
        send_mail(
            subject='Подписка PrepStats истекла',
            message=(
                f'Здравствуйте, {user.username}!\n\n'
                f'Ваша подписка PrepStats истекла. Доступ к расширенным возможностям закрыт.\n\n'
                f'Чтобы продолжить пользоваться сервисом в полном объёме, '
                f'оформите подписку снова на странице:\n'
                f'https://prepstats.pro/users/subscription/\n\n'
                f'С уважением,\nКоманда PrepStats'
            ),
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[user.email],
            fail_silently=True,
        )
        logger.info("Expiry email sent to user=%s", user.username)
    except Exception as e:
        logger.error("Failed to send expiry email to user=%s: %s", user.username, e)