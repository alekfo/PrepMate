from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    email = models.EmailField(unique=True)
    interviews_used = models.PositiveIntegerField(default=0)
    interviews_limit_per_day = models.PositiveSmallIntegerField(default=1)
    is_subscribed = models.BooleanField(default=False)
    is_premium = models.BooleanField(default=False)
    email_confirmed = models.BooleanField(default=False)
    subscription_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'


class Payment(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SUCCEEDED = 'succeeded'
    STATUS_CANCELED = 'canceled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Ожидает'),
        (STATUS_SUCCEEDED, 'Успешно'),
        (STATUS_CANCELED, 'Отменён'),
    ]

    PLAN_SUBSCRIBED = 'subscribed'
    PLAN_PREMIUM = 'premium'
    PLAN_CHOICES = [
        (PLAN_SUBSCRIBED, 'Базовый'),
        (PLAN_PREMIUM, 'Премиум'),
    ]

    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='payments')
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    yookassa_payment_id = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Платёж'
        verbose_name_plural = 'Платежи'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} — {self.get_plan_display()} {self.amount}₽ ({self.get_status_display()})'


class Subscription(models.Model):
    PLAN_CHOICES = Payment.PLAN_CHOICES

    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='subscriptions')
    payment = models.OneToOneField(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='subscription')
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES)
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Подписка'
        verbose_name_plural = 'Подписки'
        ordering = ['-started_at']

    def __str__(self):
        status = 'активна' if self.is_active else 'истекла'
        return f'{self.user.username} — {self.get_plan_display()} до {self.expires_at:%d.%m.%Y} ({status})'
