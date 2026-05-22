# Деплой PrepStats

## Что нужно заранее

- Сервер с Ubuntu 22.04+ (минимум 1 GB RAM)
- Домен `prepstats.pro` — DNS A-запись уже смотрит на IP сервера
- Репозиторий на GitHub с кодом проекта

---

## Первый деплой (один раз)

### 1. Подключиться к серверу

Через веб-консоль DigitalOcean (Access → Launch Droplet Console) или SSH если работает.

### 2. Установить Docker

```bash
apt update && apt install -y docker.io docker-compose-plugin
```

Проверить:

```bash
docker --version
docker compose version
```

### 3. Склонировать репозиторий

```bash
git clone https://github.com/<твой-username>/<репо>.git
cd PrepMate
```

### 4. Создать `.env`

```bash
nano .env
```

Вставить и заполнить:

```env
SECRET_KEY=           # длинная случайная строка, например: python3 -c "import secrets; print(secrets.token_hex(50))"
DEBUG=False
ALLOWED_HOSTS=prepstats.pro

DATABASE_URL=postgres
DB_NAME=prepstats
DB_USER=prepstats
DB_PASSWORD=          # придумай надёжный пароль
DB_HOST=db
DB_PORT=5432

CLAUDE_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-6

EMAIL_HOST=smtp.yandex.ru
EMAIL_PORT=465
EMAIL_USE_SSL=True
EMAIL_HOST_USER=      # твой яндекс-адрес
EMAIL_HOST_PASSWORD=  # пароль приложения (не пароль аккаунта)
SUPPORT_EMAIL=        # куда приходят уведомления
```

Сохранить: `Ctrl+O`, `Enter`, `Ctrl+X`.

### 5. Выдать права на скрипты

```bash
chmod +x init-ssl.sh entrypoint.sh
```

### 6. Получить SSL и запустить всё

```bash
./init-ssl.sh alekfo772@gmail.com
```

Скрипт сделает всё автоматически:
- Создаст временный сертификат → nginx стартует
- Let's Encrypt выдаст реальный сертификат
- Nginx перезагрузится с реальным сертификатом
- Поднимутся все сервисы (db, web, nginx, certbot)

Занимает ~1–2 минуты. В конце выведет `Done! https://prepstats.pro`.

### 7. Проверить

```bash
docker compose ps
```

Все 4 сервиса должны быть `running`: `db`, `web`, `nginx`, `certbot`.

Открыть в браузере: `https://prepstats.pro`

---

## Обновление (каждый раз после изменений в коде)

```bash
cd PrepMate
git pull
docker compose up -d --build
```

Миграции и `collectstatic` применятся автоматически через `entrypoint.sh`.

---

## Полезные команды

```bash
# Посмотреть логи всех сервисов
docker compose logs -f

# Логи только Django
docker compose logs -f web

# Логи nginx
docker compose logs -f nginx

# Зайти в Django shell
docker compose exec web python manage.py shell

# Создать суперпользователя
docker compose exec web python manage.py createsuperuser

# Перезапустить один сервис
docker compose restart web

# Остановить всё
docker compose down

# Остановить и удалить данные БД (осторожно!)
docker compose down -v
```

---

## SSL-сертификат

Сертификат Let's Encrypt обновляется автоматически — контейнер `certbot` проверяет каждые 12 часов и обновляет за 30 дней до истечения.

Вручную обновить:

```bash
docker compose exec certbot certbot renew
docker compose exec nginx nginx -s reload
```

---

## Структура деплоя

```
Запрос → nginx:443 (HTTPS) → gunicorn:8000 → Django
                            ↘ /static/ → папка staticfiles
nginx:80 → редирект на 443
certbot → обновление сертификата каждые 12ч
db → PostgreSQL (данные в docker volume)
```
