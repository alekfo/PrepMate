import logging

from django.core.cache import cache
from django.http import HttpResponse

logger = logging.getLogger('users')

_ADMIN_LOGIN_PATH = '/admin/login/'
_ADMIN_LOGIN_RATE_LIMIT = 5  # неудачных попыток входа в админку с одного IP за час


def _client_ip(request):
    """IP клиента: X-Real-IP (выставляется nginx), fallback — REMOTE_ADDR."""
    return request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', '')


class AdminLoginRateLimitMiddleware:
    """Защита /admin/login/ от перебора пароля: не более _ADMIN_LOGIN_RATE_LIMIT
    неудачных попыток входа с одного IP в час. Успешный вход (редирект после
    логина) счётчик не увеличивает.

    Админка — самая ценная цель на сайте (полный доступ ко всем данным), а
    её форма входа — стандартный Django admin login без какой-либо защиты
    от брутфорса из коробки.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != _ADMIN_LOGIN_PATH or request.method != 'POST':
            return self.get_response(request)

        ip = _client_ip(request)
        rate_key = f'admin_login_attempts_{ip}'
        if cache.get(rate_key, 0) >= _ADMIN_LOGIN_RATE_LIMIT:
            logger.warning("Admin login rate limit hit for ip=%s", ip)
            return HttpResponse('Слишком много попыток входа. Попробуйте позже.', status=429)

        response = self.get_response(request)
        # Django admin login при неверных данных повторно рендерит форму (200);
        # при успехе — редиректит (302). Считаем только неудачи.
        if response.status_code == 200:
            cache.set(rate_key, cache.get(rate_key, 0) + 1, timeout=3600)
        return response