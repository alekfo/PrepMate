from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'interviews_used', 'interviews_limit_per_day', 'is_subscribed', 'is_premium', 'date_joined')
    list_filter = ('is_subscribed', 'is_premium', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (
        ('PrepStats', {'fields': ('interviews_used', 'interviews_limit_per_day', 'is_subscribed', 'is_premium')}),
    )
