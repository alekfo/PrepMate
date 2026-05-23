# Деплой PrepStats

## Что нужно заранее

- Сервер с Ubuntu 22.04+ (минимум 1 GB RAM)
- Домен `prepstats.pro` — DNS A-запись уже смотрит на IP сервера
- Репозиторий на GitHub с кодом проекта

---

## Первый деплой (один раз)

### 1. Подключиться к серверу как root

Через веб-консоль хостинга или SSH:

```bash
ssh root@<IP_сервера>
```

> **Важно:** весь первый деплой выполняется от root. Это избавляет от проблем с правами на docker, apt и certbot.

### 2. Залогиниться в Docker Hub

Нужно чтобы избежать лимита анонимных pull-запросов (100 в 6 часов на IP). Бесплатный аккаунт на [hub.docker.com](https://hub.docker.com):

```bash
docker login -u <твой_dockerhub_username>
```

> Если Docker ещё не установлен — `docker login` будет недоступен. Пропустите этот шаг, скрипт установит Docker сам. Вернитесь к нему если `docker compose up` упадёт с ошибкой rate limit.

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
SECRET_KEY=           # длинная случайная строка: python3 -c "import secrets; print(secrets.token_hex(50))"
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

### 6. Установить Docker, получить SSL и запустить всё

```bash
./init-ssl.sh alekfo772@gmail.com
```

Скрипт делает всё по порядку:
- Удаляет конфликтующие пакеты (`docker.io`, `containerd`, `runc` и др.)
- Устанавливает Docker Engine из официального репозитория (`docker-ce`, `containerd.io`, `docker-compose-plugin`)
- Устанавливает certbot (если ещё нет)
- Получает сертификат Let's Encrypt через `--standalone`
- Поднимает все сервисы (db, web, nginx)

Занимает ~2 минуты. В конце выведет `Done! https://prepstats.pro`.

### 7. Настроить автообновление сертификата (один раз)

```bash
(crontab -l 2>/dev/null; echo "0 3 1 * * cd ~/PrepMate && docker compose stop nginx && certbot renew --quiet && docker compose start nginx") | crontab -
```

Проверить что добавилось:

```bash
crontab -l
```

### 8. Проверить

```bash
docker compose ps
```

Все 3 сервиса должны быть `running`: `db`, `web`, `nginx`.

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

Сертификат Let's Encrypt хранится на хосте в `/etc/letsencrypt/` и монтируется в nginx read-only.

Автообновление — crontab 1-го числа каждого месяца в 3:00:
- Останавливает nginx (~1 сек даунтайм)
- Обновляет сертификат
- Запускает nginx обратно

Вручную обновить:

```bash
docker compose stop nginx
certbot renew
docker compose start nginx
```

---

## Структура деплоя

```
Запрос → nginx:443 (HTTPS) → gunicorn:8000 → Django
                            ↘ /static/ → папка staticfiles
nginx:80 → редирект на 443
/etc/letsencrypt → монтируется в nginx read-only
crontab → обновление сертификата 1 раз в месяц
db → PostgreSQL (данные в docker volume)
```