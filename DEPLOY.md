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
ALLOWED_HOSTS=prepstats.pro,www.prepstats.pro

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

YOOKASSA_SHOP_ID=     # shopId из ЛК ЮKassa
YOOKASSA_SECRET_KEY=  # Секретный ключ из ЛК ЮKassa → Настройки → Ключи API
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

### 7. Настроить ежедневную деактивацию истёкших подписок (один раз)

Crontab — это планировщик задач Linux. Он хранит список команд с расписанием и запускает их автоматически, без участия пользователя. Каждая строка — одно задание в формате: `минуты часы день месяц день_недели команда`.

```bash
crontab -e
```

Если спросит редактор — выбери `1` (nano). Добавь строку в конец файла:

```
0 3 * * * cd /home/alek_fo/PrepMate && docker compose exec -T prepmate-web-1 python manage.py deactivate_expired_subscriptions >> /home/alek_fo/logs/subscriptions_cron.log 2>&1
```

Сохрани: `Ctrl+O` → Enter → `Ctrl+X`.

Что делает эта строка: `0 3 * * *` — каждый день в 3:00 ночи. Заходит в Docker-контейнер `prepmate-web-1` и запускает команду, которая ищет подписки с истёкшей датой, деактивирует их и отправляет пользователям письмо. Результат пишется в лог `/home/alek_fo/logs/subscriptions_cron.log`.

Проверить что добавилось:

```bash
crontab -l
```

Проверить вручную (без ожидания 3:00):

```bash
docker compose exec prepmate-web-1 python manage.py deactivate_expired_subscriptions
```

### 8. Настроить автообновление сертификата (один раз)

```bash
(crontab -l 2>/dev/null; echo "0 3 1 * * cd ~/PrepMate && docker compose stop nginx && certbot renew --quiet && docker compose start nginx") | crontab -
```

Проверить что добавилось:

```bash
crontab -l
```

### 9. Проверить

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
crontab 03:00 ежедневно → deactivate_expired_subscriptions (письмо + сброс доступа)
crontab 03:00 1-го числа → обновление SSL-сертификата
db → PostgreSQL (данные в docker volume)
```