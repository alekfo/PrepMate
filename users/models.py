from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    interviews_used = models.PositiveIntegerField(default=0)
    interviews_limit_per_day = models.PositiveSmallIntegerField(default=3)
    is_subscribed = models.BooleanField(default=False)
    is_premium = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Пользователь'
        verbose_name_plural = 'Пользователи'
