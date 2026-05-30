from django.core.management.base import BaseCommand
from django.utils import timezone

from users.models import Subscription
from users.services import deactivate_user_subscription, send_subscription_expired_email


class Command(BaseCommand):
    help = 'Деактивирует истёкшие подписки и уведомляет пользователей по email'

    def handle(self, *args, **options):
        now = timezone.now()
        expired = (
            Subscription.objects
            .filter(is_active=True, expires_at__lte=now)
            .select_related('user')
        )

        count = 0
        for sub in expired:
            user = sub.user
            sub.is_active = False
            sub.save(update_fields=['is_active'])

            # Проверяем, нет ли у пользователя другой активной подписки
            has_active = user.subscriptions.filter(is_active=True).exists()
            if not has_active:
                deactivate_user_subscription(user)
                send_subscription_expired_email(user)

            count += 1
            self.stdout.write(f'  Деактивирована подписка: {sub}')

        self.stdout.write(self.style.SUCCESS(f'Готово. Деактивировано подписок: {count}'))