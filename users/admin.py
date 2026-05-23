from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'email_confirmed', 'interviews_used', 'interviews_limit_per_day', 'is_subscribed', 'is_premium', 'date_joined')
    list_filter = ('email_confirmed', 'is_subscribed', 'is_premium', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (
        ('PrepStats', {'fields': ('email_confirmed', 'interviews_used', 'interviews_limit_per_day', 'is_subscribed', 'is_premium')}),
    )
