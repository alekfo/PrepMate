from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Payment, Subscription


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'email_confirmed', 'interviews_used', 'interviews_limit_per_day', 'is_subscribed', 'is_premium', 'subscription_expires_at', 'date_joined')
    list_filter = ('email_confirmed', 'is_subscribed', 'is_premium', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (
        ('PrepStats', {'fields': ('email_confirmed', 'interviews_used', 'interviews_limit_per_day', 'is_subscribed', 'is_premium', 'subscription_expires_at')}),
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'amount', 'status', 'yookassa_payment_id', 'created_at')
    list_filter = ('status', 'plan')
    search_fields = ('user__username', 'user__email', 'yookassa_payment_id')
    readonly_fields = ('yookassa_payment_id', 'created_at')


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'started_at', 'expires_at', 'is_active')
    list_filter = ('is_active', 'plan')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('started_at',)
