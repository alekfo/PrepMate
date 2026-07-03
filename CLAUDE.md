# PrepStats — CLAUDE.md

Инструмент подготовки к техническим собеседованиям. Пользователь вставляет текст вакансии, AI генерирует 8 вопросов, пользователь отвечает на каждый, AI оценивает каждый ответ. В конце — итоговый отчёт с баллами и фидбеком.

## Стек

- **Python 3.12**, **Django 6.0**
- **SQLite** (dev) / **PostgreSQL** (prod, через `DATABASE_URL=postgres`)
- **requests** — HTTP-клиент для вызова Claude API через внешний прокси-сервис
- **yookassa** — официальный Python SDK для приёма платежей через ЮKassa
- **gevent** — асинхронные воркеры для gunicorn
- **python-dotenv** — переменные окружения из `.env`
- Фронтенд: чистые Django-шаблоны + CSS (без JS-фреймворков)

## Структура проекта

```
prep_mate/        — настройки Django (settings.py, urls.py, wsgi/asgi)
interviews/       — основное приложение
  models.py       — InterviewSession, Question, UserAnswer, Feedback, VacancyProfile, VacancyAdvice
  views.py        — index, start, question, resume, history, report, statistics_overview,
                    statistics_vacancy, flashcards, flashcards_train
  services.py     — generate_questions(), evaluate_answer(), generate_vacancy_advice() (Claude API через прокси)
  urls.py         — маршруты приложения
  admin.py        — регистрация моделей
users/            — кастомная модель пользователя + auth-страницы + платежи
  models.py       — User (AbstractUser + доп. поля), Payment, Subscription
  views.py        — register, settings_page, privacy_policy, public_offer,
                    about, contact, send_confirmation, confirm_email,
                    create_payment, payment_webhook, payment_return
  services.py     — create_yookassa_payment(), activate_subscription(),
                    deactivate_user_subscription(), send_subscription_expired_email()
  forms.py        — RegisterForm, ContactForm
  urls.py         — маршруты users-приложения
  admin.py        — CustomUserAdmin, PaymentAdmin, SubscriptionAdmin
  management/commands/deactivate_expired_subscriptions.py — cron-команда
resumes/          — раздел резюме (только подписчики)
  models.py       — Resume, ResumeSection
  views.py        — resume_list, resume_new, resume_delete, resume_step, resume_generate, resume_retry_ai, resume_detail
  services.py     — polish_resume() (Claude API через прокси)
  urls.py         — маршруты /resume/
  admin.py        — ResumeAdmin, ResumeSectionAdmin
templates/
  base.html       — навбар, спиннер-оверлей, футер
  interviews/     — index, question, report, history, flashcards, flashcards_train
  resumes/        — list, step, detail
  users/          — login, register, settings, about, contact,
                    privacy_policy, public_offer,
                    password_change, password_change_done,
                    password_reset, password_reset_done,
                    password_reset_confirm, password_reset_complete,
                    password_reset_email.txt (email-шаблон),
                    subscription, payment_success, payment_pending
static/css/main.css — минималистичный стиль (Inter/Outfit, нейтральная палитра)
                      включает медиазапросы для мобильных (≤ 600px)
nginx/nginx.conf  — конфиг nginx: HTTPS, редирект www→apex, return 444 для чужих Host
```

## Модели

### users.User (AbstractUser +)
| Поле | Тип | По умолчанию | Назначение |
|---|---|---|---|
| `email` | EmailField | — | Уникальный (unique=True), обязательный при регистрации |
| `interviews_used` | PositiveIntegerField | 0 | Всего интервью запущено (инкремент при старте) |
| `interviews_limit_per_day` | PositiveSmallIntegerField | 1 | Дневной лимит; **управляется автоматически** через `activate_subscription` / `deactivate_user_subscription` — вручную не менять |
| `is_subscribed` | BooleanField | False | Базовая подписка активна |
| `is_premium` | BooleanField | False | Премиум подписка активна |
| `email_confirmed` | BooleanField | False | Подтверждён ли email |
| `subscription_expires_at` | DateTimeField | null | Дата истечения активной подписки |

Лимиты по плану (`settings.SUBSCRIPTION_LIMITS`): `free` → 1, `subscribed` → 2, `premium` → 5.

### users.Payment
Создаётся при каждом нажатии «Купить» — до перехода на страницу YooKassa.
| Поле | Тип | Назначение |
|---|---|---|
| `user` | FK → User | Плательщик |
| `plan` | CharField | `subscribed` / `premium` |
| `amount` | DecimalField | Сумма в рублях |
| `yookassa_payment_id` | CharField (unique) | ID платежа в YooKassa |
| `status` | CharField | `pending` / `succeeded` / `canceled` |
| `created_at` | DateTimeField | auto_now_add |

### users.Subscription
Создаётся в `activate_subscription()` после получения webhook `payment.succeeded`.
| Поле | Тип | Назначение |
|---|---|---|
| `user` | FK → User | Владелец |
| `payment` | OneToOne → Payment | Платёж, создавший подписку |
| `plan` | CharField | `subscribed` / `premium` |
| `started_at` | DateTimeField | auto_now_add |
| `expires_at` | DateTimeField | started_at + 30 дней |
| `is_active` | BooleanField | True пока не истекла |

Деактивация: management command `deactivate_expired_subscriptions` (запускается через cron ежедневно в 3:00 и при каждом деплое через `entrypoint.sh`).

### interviews.VacancyProfile
Группирует сессии одного пользователя по одному тексту вакансии.
| Поле | Тип | Назначение |
|---|---|---|
| `user` | FK → User | Владелец |
| `vacancy_text` | TextField | Полный текст вакансии (ключ дедупликации) |
| `job_title` | CharField | Название должности (обновляется из последней сессии) |
| `company_name` | CharField | Название компании |
| `created_at` | DateTimeField | auto_now_add |

Создаётся в `start` view через `get_or_create(user, vacancy_text)`. Каждая `InterviewSession` имеет FK `vacancy_profile` (nullable для старых сессий до миграции 0004).

### interviews.InterviewSession
Статусы: `pending` / `in_progress` / `completed`
Уровни: `common` (по умолчанию) / `junior` / `middle` / `pro`
Хранит: текст вакансии, job_title, company_name, overall_score, level, created_at, completed_at, `vacancy_profile` (FK)
Сортировка по умолчанию: `-created_at`

### interviews.Question
Типы: `technical` / `behavioral` / `situational`
8 вопросов на сессию, порядок через `order` (0–7)

### interviews.UserAnswer
OneToOne → Question. Хранит текст ответа.

### interviews.Feedback
OneToOne → UserAnswer. Хранит: score (1–10), strengths (JSON), improvements (JSON), ideal_answer_hint, `weakness_tags` (JSON, default=[]), `strength_tags` (JSON, default=[]).

Теги выбираются из фиксированного белого списка `_VALID_TAGS` в `services.py` (depth, examples, structure, communication, confidence, relevance, experience, proactivity). Теги не из списка отбрасываются после парсинга.

### interviews.VacancyAdvice
OneToOne → VacancyProfile. Агрегированный AI-анализ прогресса по всем сессиям вакансии.
| Поле | Тип |
|---|---|
| `overall_progress` | TextField |
| `chronic_issues` | JSONField (list) |
| `improvements` | JSONField (list) |
| `next_steps` | JSONField (list) |
| `focus_topics` | JSONField (list) |
| `verdict` | TextField |
| `generated_at` | DateTimeField (auto_now_add) |
| `session_count_at_generation` | PositiveIntegerField |

Инвалидация: при каждом визите сравнивается `session_count_at_generation` с текущим числом завершённых сессий. Если не совпадает — регенерируется.

**Важно:** `generated_at` имеет `auto_now_add=True` (устанавливается только при INSERT). При обновлении существующей записи `views.py` вручную присваивает `vacancy_advice.generated_at = timezone.now()` перед `save()` — иначе дата оставалась бы датой первого создания.

## URL-маршруты

```
/                                           → index (форма вакансии / лендинг)
/start/                                     → start (POST, создаёт сессию)
/history/                                   → history (список сессий пользователя)
/session/<id>/resume/                       → resume (редирект на первый неотвеченный вопрос)
/session/<id>/question/<order>/             → question (GET показ / POST сохранение ответа)
/session/<id>/report/                       → report (итоговый отчёт)
/statistics/                                → statistics_overview (список вакансий, только подписчики)
/statistics/vacancy/<id>/                   → statistics_vacancy (детальная страница вакансии)
/flashcards/                                → flashcards (выбор вакансии и фильтров, только подписчики)
/flashcards/train/                          → flashcards_train (GET с параметрами фильтрации)

/users/login/                               → login (rate-limit: 10 неудачных попыток/час с IP, см. «Безопасность»)
/users/logout/                              → logout (только POST)
/users/register/                            → register
/users/settings/                            → settings (требует login)
/users/subscription/                        → subscription (страница тарифов, paywall)
/users/about/                               → о проекте (публичная)
/users/privacy-policy/                      → политика конфиденциальности
/users/public-offer/                        → договор публичной оферты
/users/contact/                             → форма обратной связи
/users/send-confirmation/                   → POST, отправляет письмо подтверждения email
/users/confirm-email/?token=...             → подтверждение email по токену
/users/payment/create/                      → POST, создаёт платёж в YooKassa и редиректит на него
/users/payment/webhook/                     → POST @csrf_exempt, принимает уведомления от YooKassa
/users/payment/return/                      → страница возврата после оплаты (success / pending)
/users/password-change/                     → смена пароля (требует login)
/users/password-change/done/               → успешная смена пароля
/users/password-reset/                      → запрос сброса пароля (email)
/users/password-reset/done/                → "письмо отправлено"
/users/password-reset/<uidb64>/<token>/    → форма нового пароля
/users/password-reset/complete/            → сброс завершён

/admin/                                     → Django admin (rate-limit на /admin/login/, см. «Безопасность»)
```

## Email — подтверждение и уведомления

**Отправка письма подтверждения** — хелпер `_send_confirmation_email(user, request)` в `users/views.py`:
- Вызывается автоматически сразу при регистрации
- Вызывается повторно через кнопку «Подтвердить» в настройках (`/users/send-confirmation/`)
- Токен генерируется через `django.core.signing.dumps({'uid': pk}, salt='email-confirm')`, действителен 24 часа
- Подтверждение: `confirm_email` view верифицирует токен и выставляет `user.email_confirmed = True`
- Flash-сообщение после отправки содержит подсказку «Если не видите — проверьте папку «Спам»»

**Уведомление админу при регистрации** — `_notify_admin_new_user(user)` в `users/views.py`, `fail_silently=True`.

**Уведомление админу при оплате подписки** — `_notify_admin_new_payment(user, payment, sub)` в `users/services.py`, вызывается из `activate_subscription()` сразу после письма пользователю. Отправляет на `SUPPORT_EMAIL` план, сумму, `yookassa_payment_id` и дату окончания подписки. `fail_silently=True`, обёрнуто в `try/except: pass` — сбой уведомления не должен ронять активацию подписки.

**Сброс пароля** — стандартный Django `PasswordResetView` с кастомными шаблонами. Письмо отправляется только если email есть в базе, но пользователю всегда показывается «письмо отправлено» (защита от перебора).

**Email-конфиг** (`settings.py`):
```
EMAIL_BACKEND = smtp.EmailBackend
EMAIL_HOST = smtp.yandex.ru
EMAIL_PORT = 465
EMAIL_USE_SSL = True
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER   ← важно, иначе PasswordResetView шлёт с webmaster@localhost
```

## Блокировка начала интервью

В `start` view и в UI (шаблон `index.html`) проверки выполняются **в таком порядке**:
1. `not user.email_confirmed` → ошибка «Подтвердите email»
2. `used_today >= user.interviews_limit_per_day` → ошибка «Дневной лимит исчерпан»

Кнопка «Начать интервью» в UI: при блокировке заменяется на `.btn-blocked-wrap` с CSS hover-tooltip (tooltip всплывает при наведении, не всегда виден). Textarea тоже блокируется.

## Claude API — логика вызовов

В `interviews/services.py` три публичных метода. Claude вызывается **не напрямую через Anthropic SDK**, а через HTTP-прокси: `requests.post(settings.CLAUDE_API_SERVICE_URL, json={"prompt": ...}, headers={"X-API-Key": settings.CLAUDE_API_SERVICE_KEY}, timeout=60)`. Прокси возвращает `{"response": "..."}`.

Адрес прокси задаётся через `CLAUDE_API_SERVICE_URL`, ключ авторизации — через `CLAUDE_API_SERVICE_KEY` (env `SERVICE_API_KEY`).

**`_ask(prompt, _retries=2)`** — внутренний хелпер. Выполняет до 3 попыток (1 + 2 retry) с паузами 1s и 2s:
- Retry при `RequestException` (сетевые ошибки)
- Retry при пустом ответе (`response.json().get("response", "")` — пустая строка)
- Если все попытки исчерпаны — бросает `RuntimeError`

**`generate_questions(vacancy_text, level='common')`** — 1 запрос при старте сессии.
При `level` ≠ `'common'` добавляет в промпт инструкцию по уровню из `_LEVEL_INSTRUCTIONS`.
Возвращает `{"job_title": ..., "company_name": ..., "questions": [{text, type}, ...]}`.

**`evaluate_answer(question_text, answer_text, vacancy_context)`** — 1 запрос после каждого ответа.
Возвращает `{"score": 1-10, "strengths": [...], "improvements": [...], "ideal_answer_hint": ..., "weakness_tags": [...], "strength_tags": [...]}`.
Промпт задаёт роль «ментора» (не строгого экзаменатора) с явными ориентирами по баллам (8-10 / 5-7 / 3-4 / 1-2) — 5-7 считается нормальным ответом без деталей и примеров, а не провалом; цель — не занижать баллы за неидеальные, но по существу ответы, чтобы не ронять мотивацию кандидата. `strengths`/`improvements` при этом остаются такими же подробными, как раньше — смягчение касается только числового балла.

**`generate_vacancy_advice(vacancy_profile)`** — 1 запрос при генерации/обновлении `VacancyAdvice`. Берёт данные напрямую из `Question → Feedback` (не из промежуточных summary). Передаёт историю всех сессий (дата, балл, текст вопроса, первое замечание), хронические и исправленные теги, **уровни подготовки** (`Counter` по `session.get_level_display()`). Вердикт запрашивается в формате «что работает + что блокирует + реалистичный срок». Возвращает `{"overall_progress": ..., "chronic_issues": [...], "improvements": [...], "next_steps": [...], "focus_topics": [...], "verdict": ...}`.

Итого **9 запросов** на одну полную сессию (1 + 8). `VacancyAdvice` — отдельный запрос при первом визите на страницу вакансии или при появлении новой сессии, только для подписчиков. Ответ парсится через `_parse_json()`, которая снимает markdown-обёртку ` ```json ``` `.

## Переменные окружения (.env)

```
SECRET_KEY=...              # обязателен, без дефолта — без него приложение падает при старте (см. «Безопасность»)
DEBUG=False                 # дефолт в settings.py — False; для локальной разработки указать True явно
ALLOWED_HOSTS=localhost,127.0.0.1
CLAUDE_API_SERVICE_URL=https://api.fieldlog.online/ask   # прокси к Claude
SERVICE_API_KEY=...                                      # X-API-Key для прокси

YOOKASSA_SHOP_ID=...       # shopId из ЛК ЮKassa
YOOKASSA_SECRET_KEY=...    # Секретный ключ из ЛК ЮKassa → Настройки → Ключи API

EMAIL_HOST=smtp.yandex.ru
EMAIL_PORT=465
EMAIL_USE_SSL=True
EMAIL_HOST_USER=...        # адрес отправителя
EMAIL_HOST_PASSWORD=...    # пароль приложения (не пароль аккаунта)
SUPPORT_EMAIL=...          # адрес получателя уведомлений

# Для прода раскомментировать:
# DATABASE_URL=postgres
# DB_NAME=...
# DB_USER=...
# DB_PASSWORD=...
# DB_HOST=db
# DB_PORT=5432
```

## Инфраструктура (прод)

**Домен:** `prepstats.pro` (www редиректит на apex)

**Docker Compose** (`docker-compose.yml`):
- `db` — postgres:16-alpine, данные в volume `postgres_data`
- `web` — собственный образ, запускается через `entrypoint.sh`
- `nginx` — nginx:alpine, порты 80/443, static через volume `static_files`

**entrypoint.sh** при старте контейнера:
1. Ждёт готовности PostgreSQL (polling через psycopg2)
2. `python manage.py migrate --noinput`
3. `python manage.py backfill_vacancy_profiles` — привязывает старые сессии к `VacancyProfile` (идемпотентно, безопасно при каждом деплое)
4. `python manage.py deactivate_expired_subscriptions` — деактивирует истёкшие подписки (идемпотентно; основной запуск — cron ежедневно в 3:00)
5. `python manage.py collectstatic --noinput`
6. Запускает gunicorn: `gevent` воркеры, 2 workers, 20 connections, timeout 120s

**nginx** (`nginx/nginx.conf`):
- `default_server` на 80 и 443 → `return 444` (блокирует сканеры с чужим Host)
- `prepstats.pro` → proxy_pass на `web:8000`, таймауты 60s/120s
- `www.prepstats.pro` → редирект на apex
- `/static/` отдаётся напрямую из volume
- `/media/` **не** отдаётся напрямую — `location /protected-media/ { internal; alias /media/; }` доступен только по внутреннему редиректу от Django (см. «Безопасность»)
- `/favicon.ico` и `/robots.txt` — статика без access_log
- `client_max_body_size 6m;` — иначе nginx (дефолт 1m) отклонял загрузку фото резюме (лимит 5 МБ на уровне Django) до того, как запрос доходил до приложения

**Важно при деплое:** `nginx.conf` смонтирован как volume (`ro`), а не собирается в образ — `docker compose up -d` не видит изменений его содержимого и не пересоздаёт контейнер `nginx`. После любого изменения `nginx/nginx.conf` нужно вручную выполнить `docker compose restart nginx` на сервере, иначе новый конфиг не подхватится.

**CI/CD** (`.github/workflows/ci.yml`):
- `test` job: Python 3.12, pip cache, `SECRET_KEY`/`DEBUG`/`ALLOWED_HOSTS` заданы явно через `env:` (нужно из-за отсутствия дефолта у `SECRET_KEY`), migrate, `python manage.py test interviews users --verbosity=2`
- `deploy` job: только при `push` в `main`, SSH → dump БД → сохранить логи → `git pull` → `docker compose build --no-cache web` → `docker compose up -d`
- Деплой запускается только после успешного прохождения тестов (`needs: test`)
- Деплой пересоздаёт только `web` — если менялся `nginx.conf`, после деплоя нужен ручной `docker compose restart nginx` (CI это не делает)

## Безопасность

Хардненинг, сделанный перед запуском платной рекламы (03.07.2026):

- **`SECRET_KEY` без дефолта** (`prep_mate/settings.py`) — `os.environ['SECRET_KEY']`, приложение падает при старте, если переменная не задана. Раньше был дефолт `'django-insecure-change-me-in-production'`: при сбое загрузки `.env` на проде приложение тихо продолжало бы работать с публично известным ключом — а на нём построены не только сессии/CSRF, но и токен подтверждения email (`signing.dumps(..., salt='email-confirm')`) и токены сброса пароля Django. Компрометация ключа = подделка любого из этих токенов.
- **`DEBUG` по умолчанию `False`** (раньше был `True`) — то же соображение: отсутствие переменной в проде не должно включать вывод трейсбеков всем посетителям.
- **`SECURE_*` настройки, активные только когда `DEBUG=False`**: `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` (+ `INCLUDE_SUBDOMAINS`/`PRELOAD`), `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')`. Последнее безопасно доверять, т.к. `web` не публикует порт наружу (`docker-compose.yml` без `ports:` у сервиса `web`) — до Django запрос может дойти только через nginx, который сам выставляет этот заголовок.
- **Rate-limit на `/users/login/`** — `RateLimitedLoginView` (`users/views.py`, подключён в `users/urls.py` вместо голого `auth_views.LoginView`): не более 10 неудачных попыток входа с одного IP в час (`cache`, ключ `login_attempts_<ip>`). Считаются только неудачные попытки (`form_invalid`) — успешный вход счётчик не трогает, чтобы не блокировать общий IP (офис/NAT).
- **Rate-limit на `/admin/login/`** — `AdminLoginRateLimitMiddleware` (`prep_mate/middleware.py`, первым после `SecurityMiddleware` в `MIDDLEWARE`): не более 5 неудачных попыток с одного IP в час. Django admin login штатно не защищён от перебора, а это самая ценная цель на сайте. Различает успех/неудачу по коду ответа admin-login view (200 = форма перерендерена с ошибкой → неудача; 302 = редирект после входа → успех).
- **`/media/` закрыт от прямого доступа** — раньше nginx отдавал `location /media/ { alias /media/; }` всем без проверки, а там лежат фото резюме реальных людей (PII). Теперь:
  - `nginx.conf`: `location /protected-media/ { internal; alias /media/; }` — недоступен напрямую снаружи.
  - `resumes/views.py: resume_photo` (url `resumes:photo`, `/resume/<id>/photo/`) — проверяет `resume.user == request.user`, на проде отдаёт `X-Accel-Redirect: /protected-media/<path>` (файл гоняет nginx, не Python), в `DEBUG` (локальный `runserver` без nginx) отдаёт файл напрямую через `FileResponse`.
  - Все ссылки на фото (`templates/resumes/detail.html`, JSON-ответ `resume_upload_photo`) ведут на `resumes:photo`, а не на `resume.photo.url` напрямую.

## Логирование

В `settings.py` настроен structured logging (формат `{asctime} {levelname} {name}: {message}`):
- `interviews` и `users` логгеры: `DEBUG` в dev, `INFO` в prod
- `django.request`: только `WARNING` и выше
- `django.security.DisallowedHost`: подавлен через `NullHandler` (**важно**: `'handlers': []` не глушит логгер — при нуле обработавших запись хендлеров Python сбрасывает её в `logging.lastResort`, то есть всё равно печатает в stderr с traceback'ом; нужен явный `NullHandler`, который реально поглощает запись)

## Навигация

**Незалогиненный пользователь** (навбар): бренд → О проекте · Войти · Регистрация
**Залогиненный пользователь** (навбар): бренд → username · Выйти · бургер-меню `≡`
Бургер-меню dropdown: История · Менторство от AI · Флэш-карточки · Настройки · О проекте

`.nav-username` отображается на мобильных устройствах с `max-width: 80px; overflow: hidden; text-overflow: ellipsis` — длинные логины обрезаются с `…`.

При добавлении нового раздела — добавить `<a>` в `#navDropdown` в `base.html`.

## Страница index

- **Незалогиненный**: заголовок «Начни свой карьерный путь здесь», кнопки «Зарегистрироваться» + «Войти» (`.landing-cta`)
- **Залогиненный**: заголовок «Готов проверить себя?», форма с textarea
- `index` view передаёт `past_vacancies` — до 5 последних уникальных сессий (дедупликация по `vacancy_text`)
- Dropdown «Из истории» подставляет текст вакансии в textarea через JS
- Textarea: `rows=4`, авторастягивается (`autoGrow`), `resize: none`
- Выбор уровня сложности (`junior` / `middle` / `pro`) — доступен только подписчикам (`is_subscribed` или `is_premium`); для остальных select задизейблен с hover-tooltip. Сервер валидирует подписку повторно в `start` view (игнорирует level если нет подписки).

## Раздел Статистика

Доступен только подписчикам (`is_subscribed` или `is_premium`). Не-подписчик редиректится на `/users/subscription/`.

### Обзор вакансий (`/statistics/`)

View `statistics_overview`. Итерирует все `VacancyProfile` пользователя с завершёнными сессиями. По каждой вакансии вычисляет в Python:
- средний балл, тренд (`_compute_trend`: avg последних 3 vs avg предыдущих 3, порог ±0.5), топ-2 тега слабых мест
- Если у пользователя нет вакансий с завершёнными сессиями — заглушка с предложением пройти интервью

На карточке вакансии — клик запускает `activateSpinner(phrases)` (ожидание генерации советов).

### Детальная страница вакансии (`/statistics/vacancy/<id>/`)

View `statistics_vacancy`. Доступ: `vacancy_profile.user == request.user`.

**Ленивая генерация VacancyAdvice** (при каждом визите):
- Если `VacancyAdvice` отсутствует или `session_count_at_generation < текущее_кол-во_сессий` — вызывается `generate_vacancy_advice()`, создаётся/обновляется запись
- `SessionAdvice` не существует — удалено как нефункциональное (данные не отображались в UI, токены тратились впустую)

**Кэш** (`django.core.cache`): используется `FileBasedCache` (`/tmp/django_cache_prepstats`) — межпроцессный, работает при нескольких gunicorn-воркерах. LocMemCache не подходит, так как каждый воркер видит только свою память.

**Защита от двойных API-запросов при сбоях** (`django.core.cache`):
- Перед вызовом `generate_vacancy_advice` в кэш пишется флаг `vacancy_advice_attempt_<id>` (TTL 5 минут)
- Повторные визиты в течение 5 минут не триггерят новый запрос к API
- При успешной генерации флаг удаляется немедленно (`cache.delete`)
- Если генерация упала или кулдаун активен — в шаблон передаётся `advice_stale=True`

**Баннер устаревших данных** (`advice-stale-banner` в шаблоне):
- Если `advice_stale=True` и `VacancyAdvice` существует → «Анализ обновляется — показаны данные предыдущих сессий»
- Если `advice_stale=True` и `VacancyAdvice` нет → «Не удалось получить AI-анализ. Зайдите через пару минут»

**SVG-график** `overall_score` по сессиям (без JS-библиотек):
- Координаты вычисляются в Python (`_build_chart_points`, `_build_chart_labels`): `pad_left=52, plot_w=536, pad_top=8, plot_h=124`, `viewBox="0 0 600 145"`
- Координаты передаются как **целые числа** (не float!) — Django рендерит float через русскую локаль с запятой (`320,0`), что ломает SVG. Округление через `round()` → int решает проблему.
- Ось Y: метки 10/7/4/1 + вертикальная линия оси на x=52

**Динамика навыков** (`_build_tag_stats`): для каждого тега считается в скольких сессиях встречался. Статусы: `chronic` (≥50% сессий), `fixed` (был раньше, отсутствует в последних 3), `active` (остальные).

**VacancyAdvice** отображает: общий прогресс, хронические проблемы, улучшения, следующие шаги, темы для изучения (как pill-бейджи), вердикт.

### Страница подписки (`/users/subscription/`)

View `subscription` в `users/views.py`. Показывает три тарифа (Бесплатный / Базовый 399₽/мес / Премиум 799₽/мес) с текущим статусом пользователя и датой окончания (`subscription_expires_at`). Кнопки «Купить» — реальные формы, ведут на `create_payment`.

Текущий план определяется: `is_premium` → `'premium'`, `is_subscribed` → `'subscribed'`, иначе `'free'`.

Логика кнопок по тарифам (downgrade недоступен):

| Текущий план | Бесплатный | Базовый | Премиум |
|---|---|---|---|
| `free` | Активен | Купить — 399 ₽ | Купить — 799 ₽ |
| `subscribed` | Недоступно | Активен | Купить — 799 ₽ |
| `premium` | Недоступно | Недоступно | Активен |

## Раздел Флэш-карточки

Доступен только подписчикам (`is_subscribed` или `is_premium`). Не-подписчик редиректится на `/users/subscription/`.

### Страница выбора (`/flashcards/`)

View `flashcards`. Показывает список вакансий пользователя, у которых есть хотя бы одна завершённая сессия. Передаёт `vacancies` и `tag_labels` (словарь тег → читаемое название).

### Тренировка (`/flashcards/train/`)

View `flashcards_train`. Принимает GET-параметры:
- `vacancy_id` — обязательный, ID `VacancyProfile`
- `question_type` — `technical` / `behavioral` / `situational` (опционально)
- `tag` — один из `_VALID_TAGS` (фильтр по тегу слабого места)
- `level` — `common` / `junior` / `middle` / `pro` (опционально)
- `weak_only=1` — только вопросы с `feedback.score < 4`

Выбирает `Question` из завершённых сессий вакансии с заполненным `answer` и `feedback`, применяет фильтры, перемешивает через `random.shuffle`. Если после фильтрации нет карточек — `messages.warning` и редирект обратно.

Каждая карточка (`cards` — список dict): `text`, `type_display`, `score`, `hint` (ideal_answer_hint). Отображается в шаблоне `flashcards_train.html` — flip-карточки без JS-фреймворков.

Отдельной модели нет — используются существующие `Question` / `UserAnswer` / `Feedback`.

## Система оплаты (YooKassa)

### Флоу платежа

1. `POST /users/payment/create/` (`create_payment` view) — проверяет план, вызывает `create_yookassa_payment()`, редиректит на `confirmation_url` YooKassa
2. Пользователь оплачивает на сайте YooKassa
3. `POST /users/payment/webhook/` (`payment_webhook` view, `@csrf_exempt`) — получает `payment.succeeded`, находит `Payment` по `yookassa_payment_id`, вызывает `activate_subscription()`
4. `GET /users/payment/return/` (`payment_return` view) — показывает `payment_success.html` если подписка уже активна, иначе `payment_pending.html`

### users/services.py

- **`create_yookassa_payment(user, plan, return_url)`** — создаёт платёж в YooKassa через SDK, сохраняет `Payment(status=pending)` в БД, возвращает `(payment_db, confirmation_url)`. Использует `idempotency_key=uuid4()`.
- **`activate_subscription(user, payment)`** — деактивирует старые подписки, создаёт `Subscription(expires_at=now+30d)`, обновляет `user.is_subscribed`, `user.is_premium`, `user.subscription_expires_at`, `user.interviews_limit_per_day`, отправляет письмо-подтверждение пользователю.
- **`deactivate_user_subscription(user)`** — сбрасывает все поля подписки у пользователя, лимит → 1.
- **`send_subscription_expired_email(user)`** — письмо об истечении с ссылкой на страницу подписки.

### Идемпотентность webhook

Перед активацией проверяется `payment.status == STATUS_SUCCEEDED` — повторный webhook не вызовет двойной активации.

### Проверка IP webhook

`_is_yookassa_ip(request)` в `users/views.py` — проверяет IP через `ipaddress` (стандартная библиотека). Покрывает официальный список ЮKassa: CIDR-диапазоны `185.71.76.0/27`, `185.71.77.0/27`, `77.75.153.0/25`, `77.75.154.128/25`, `2a02:5180::/32` и отдельные IP `77.75.156.11`, `77.75.156.35`. IP берётся через общий хелпер `_client_ip(request)` (`X-Real-IP` от nginx, fallback — `REMOTE_ADDR`). При неверном IP возвращается `200 ok`.

### Чеки для самозанятого

Чек через «Мой налог» настраивается в ЛК YooKassa один раз (Настройки → «Мой налог»). После этого YooKassa автоматически регистрирует доход в ФНС и отправляет чек покупателю на email, который тот вводит на странице оплаты. Подробнее — `YOOKASSA.md`.

## Страница настроек (`/users/settings/`)

Секции:
- **Аккаунт**: email + индикатор подтверждения (зелёный/жёлтый бейдж), кнопка «Подтвердить»; смена пароля
- **Язык интерфейса**: радиокнопки RU/EN (disabled, «Скоро»)
- **Подписка**: текущий план + дата истечения (`subscription_expires_at|date:"d.m.Y"`) + кнопка «Управлять» (disabled, «Скоро»)
- **Документы**: ссылки на политику конфиденциальности и публичную оферту

## Регистрация

`RegisterForm` расширяет `UserCreationForm`:
- Поле `email` (required, unique — проверка в `clean_email`)
- Поле `privacy_policy` (BooleanField) — чекбокс согласия с политикой и офертой; кнопка «Зарегистрироваться» заблокирована JS до отметки чекбокса (проверка начального состояния при загрузке страницы)
- После регистрации: автоматически отправляется письмо подтверждения email

### Защита от ботов

- **Honeypot**: поле `website` в `RegisterForm` — спрятано в шаблоне через CSS-класс `.hp-field` (абсолютный off-screen, не `display:none`/`visibility:hidden` — некоторые боты такие способы скрытия распознают и пропускают поле). `clean_website()` отклоняет форму без объяснения причины, если поле заполнено. **Важно:** `{{ form.website }}` должен рендериться **внутри** `<form>` — 01.07.2026 рестайлинг регистрации случайно вынес его перед `<form>`, из-за чего поле не попадало в POST и honeypot переставал работать для всех ботов, не только headless.
- **Одноразовые почты**: `clean_email` дополнительно проверяет домен против `_DISPOSABLE_EMAIL_DOMAINS` (mailinator, guerrillamail, 10minutemail и т.п.) в `users/forms.py`.
- **Rate-limit**: в `register` view — не более 5 попыток регистрации в час с одного IP, счётчик в `cache` (`FileBasedCache`, ключ `register_attempts_<ip>`, TTL 3600s). IP берётся через хелпер `_client_ip(request)` в `users/views.py` (`X-Real-IP` от nginx, fallback `REMOTE_ADDR`) — используется также в `_is_yookassa_ip` и `payment_webhook`.
- **Логирование IP**: `register` и `confirm_email` пишут IP в лог (`New user registered: ... ip=%s`, `Email confirmed for user=... ip=%s`, включая expired/invalid токен) — добавлено 02.07.2026 для диагностики паттерна бот-регистраций (один источник / ботнет / резидентные прокси).

## Важные детали

- `AUTH_USER_MODEL = 'users.User'` — везде использовать `get_user_model()` или `settings.AUTH_USER_MODEL`
- `RegisterForm` в `users/forms.py` — обязательно использовать вместо стандартного `UserCreationForm`
- Logout — только POST (Django 5+), в шаблоне обёрнут в `<form method="post">`
- `resume` view — находит первый `Question` без `UserAnswer` через `filter(answer__isnull=True)`
- `history` view — аннотирует queryset полями `total` и `answered` через `Count` + `Q`
- Спиннер-оверлей определён в `base.html`, активируется через `activateSpinner(phrases)` — принимает массив фраз, перемешивает случайно. Смена фраз реализована через CSS `@keyframes`-анимацию (percentages считаются в JS один раз при вызове, каждая фраза — отдельный `<span>` со сдвинутым `animation-delay`), **не через `setInterval`**: при обычном POST-сабмите формы страница ждёт навигацию, и на мобильных браузерах JS-таймеры на "уходящей" странице приостанавливаются до ответа сервера (на десктопе — нет), из-за чего фразы зависали, хотя CSS-спиннер (`.spinner`, compositor-поток) продолжал крутиться
- CSS адаптирован для мобильных через `@media (max-width: 600px)` в конце `main.css`
- Карточки истории и блок score-card в отчёте окрашиваются по `overall_score`: `score--low` (< 2, красный), `score--mid` (2–7, жёлтый), `score--high` (> 7, зелёный) — переливающийся градиент через CSS `@keyframes score-shimmer`
- В истории у каждой сессии под датой отображается уровень (`session.get_level_display`), если `level != 'common'`
- `CSRF_TRUSTED_ORIGINS` — автоматически формируется из `ALLOWED_HOSTS` (исключая localhost)

## Раздел Резюме (`resumes/`)

Доступен только подписчикам (`is_subscribed` или `is_premium`). Не-подписчик редиректится на `/users/subscription/`.

### Приложение `resumes/`

```
resumes/
  models.py    — Resume, ResumeSection
  views.py     — resume_list, resume_new, resume_step, resume_edit_section,
                  resume_generate, resume_retry_ai, resume_detail
  services.py  — polish_resume() (один запрос к Claude API)
  urls.py      — маршруты /resume/
  admin.py     — ResumeAdmin (с инлайном), ResumeSectionAdmin
templates/resumes/
  list.html    — список резюме + форма создания нового
  step.html    — универсальный шаблон для всех 7 шагов опроса + режим редактирования (is_edit_mode)
  detail.html  — итоговое резюме в виде документа
```

### Модели

**`Resume`**
| Поле | Тип | Назначение |
|---|---|---|
| `user` | FK → User | Владелец |
| `profession` | CharField | Целевая должность (не редактируется пользователем) |
| `status` | CharField | `draft` / `completed` / `completed_raw` |
| `created_at` | DateTimeField | auto_now_add |
| `updated_at` | DateTimeField | auto_now |

**`ResumeSection`**
| Поле | Тип | Назначение |
|---|---|---|
| `resume` | FK → Resume | Родительское резюме |
| `section_type` | CharField | `contacts` / `summary` / `experience` / `education` / `skills` / `languages` / `certifications` |
| `order` | PositiveSmallIntegerField | Порядок секции |
| `raw_content` | JSONField | Сырые данные от пользователя |
| `ai_content` | JSONField (null) | Улучшенная версия от AI |
| `user_content` | JSONField (null) | Ручные правки пользователя через «Изменить» |

`display_content` — property: возвращает `user_content or ai_content or raw_content`.

**Приоритет слоёв:** ручные правки (`user_content`) > AI-версия (`ai_content`) > сырые данные (`raw_content`). При повторном прогоне через AI (`_run_ai_polish`) `user_content` сбрасывается в `None` — пользователь видит свежую AI-версию. Признак того, что AI точно поработал над секцией: `ai_content is not None`.

Уникальность: `unique_together = [('resume', 'section_type')]`.

### Статусы Resume

- `draft` — опрос ещё не завершён
- `completed` — AI успешно обработал данные
- `completed_raw` — AI не ответил, секции заполнены сырыми данными пользователя

### URL-маршруты

```
/resume/                              → resume_list
/resume/new/                          → resume_new (POST)
/resume/<id>/delete/                  → resume_delete (POST)
/resume/<id>/step/<step>/             → resume_step (GET/POST, только для draft)
/resume/<id>/edit/<step>/             → resume_edit_section (GET/POST, только для completed/completed_raw)
/resume/<id>/generate/                → resume_generate (POST, вызывается из step view)
/resume/<id>/retry-ai/                → resume_retry_ai (POST)
/resume/<id>/                         → resume_detail
```

### Шаги опроса (`RESUME_STEPS`)

7 шагов, каждый сохраняет `ResumeSection.raw_content` в БД при сабмите:
1. `contacts` — контактная информация (ФИО, email, телефон, город, LinkedIn, GitHub)
2. `summary` — о себе (свободный текст, AI улучшает)
3. `experience` — опыт работы (повторяющийся блок с JS-кнопкой "+", **необязательный** — можно оставить пустым)
4. `education` — образование (повторяющийся блок)
5. `skills` — навыки (hard + soft)
6. `languages` — языки (повторяющийся инлайн-блок)
7. `certifications` — курсы и сертификаты (повторяющийся, **необязательный** — есть кнопка "Пропустить этот раздел")

На последнем шаге при сабмите автоматически запускается `_run_ai_polish()` (спиннер активируется через JS).

### Валидация по шагам

Обязательные поля (`_validate_step` в `views.py`):
- `contacts`: full_name + (email или phone)
- `summary`: text
- `experience`: **секция необязательна** (пустой список проходит); если записи добавлены — каждая требует company, period_start, period_end, responsibilities
- `education`: institution, year — для каждой записи
- `skills`: hard_skills
- `languages`: хотя бы один язык
- `certifications`: не валидируется (можно пропустить)

### Редактирование секций (`resume_edit_section`)

Доступно только для завершённых резюме (`completed` / `completed_raw`). URL: `/resume/<id>/edit/<step>/`.

- Форма предзаполняется из `section.display_content` (то, что сейчас видит пользователь)
- Результат сохраняется в `user_content` — имеет наивысший приоритет в `display_content`
- `step.html` при `is_edit_mode=True`: скрывает прогресс-бар, заменяет «Далее» на «Сохранить изменения», добавляет «← Назад к резюме»
- В `detail.html` кнопка «Изменить» у каждой секции (включая шапку с контактами)
- Секция «Опыт работы» отображается всегда, даже если пустая («Опыт работы не указан»)

### Стаж

Вычисляется в `_experience_label(items)` (`views.py`) из `display_content` секции experience. Парсинг дат через `_parse_period_date(text)` — понимает русские названия месяцев и «по настоящее время». Отображается в шапке резюме справа от должности: «Стаж X лет / X года / менее 1 года / 0 лет». При пустой секции — «Стаж 0 лет».

### Баннеры AI на странице резюме

`detail.html` показывает один из двух баннеров над резюме:
- **`completed`** — зелёная плашка «✓ Улучшено с помощью AI»
- **`completed_raw`** — оранжевый баннер «AI не смог обработать резюме» + кнопка «Повторно проконсультироваться с AI» → POST `/resume/<id>/retry-ai/`

### Удаление резюме (`resume_delete`)

`POST /resume/<id>/delete/` — проверяет владельца (`get_object_or_404(..., user=request.user)`), удаляет файл фото с диска (если есть), затем сам `Resume` (`ResumeSection` удаляется каскадно). Редиректит на `resumes:list` с `?deleted=1`.

Кнопка «Удалить» показывается по-разному в зависимости от страницы:
- **`list.html`**: только у резюме со статусом `draft` (черновики) — овальная кнопка `.badge-delete-btn` в том же стиле, что и бейдж «Черновик», только красная. У завершённых резюме (`completed`/`completed_raw`) кнопки на списке нет — удаление только со страницы резюме.
- **`detail.html`**: обычная кнопка `.btn.btn-danger` внизу страницы, для резюме любого статуса.

Перед отправкой — `confirm()` («Удалить это резюме? Это действие необратимо.»). Форма с кнопкой — не внутри `<a>` (в списке карточки — целиком `<a>`, кнопка на них не помещалась бы валидно), поэтому в структуру карточки черновика добавлена обёртка с внутренним `.resume-item-link` + отдельная `<form>`.

При `?deleted=1` в query string `list.html` показывает toast `.toast.toast--success` в правом нижнем углу («Резюме удалено»), который через 2.5 сек плавно исчезает (`.toast--hide`, CSS-transition) и удаляется из DOM.

### Флоу при сбое и повторном запросе AI

Если `polish_resume()` выбросил исключение → `Resume.status = 'completed_raw'`, `ai_content` не пишется.

При повторном прогоне (`resume_retry_ai` → `_run_ai_polish`):
- `polish_resume` читает `display_content` каждой секции (не `raw_content`) — если пользователь редактировал секцию, AI получает его версию
- После успеха: `ai_content` обновляется, `user_content` сбрасывается в `None`, `status → completed`
- После сбоя: `status → completed_raw`, `ai_content` не трогается

### Claude API — `polish_resume(resume)`

Один запрос на всё резюме. Собирает `display_content` всех секций (AI улучшает то, что сейчас видит пользователь), формирует единый промпт, сохранить факты. Возвращает JSON вида `{section_type: улучшенный_контент}`. После успеха каждая секция получает новый `ai_content`, `user_content` обнуляется.

### Повторяющиеся блоки (JS)

`step.html` содержит единый JS-блок для всех повторяющихся шагов:
- Кнопка "+" клонирует первый `.repeating-item`, инкрементирует индексы в `name` атрибутах (`company-0`, `company-1`...)
- Для обычных блоков кнопка "Удалить" добавляется в `.repeating-item-header`
- Для инлайн-блоков (языки, `.repeating-item--inline`) кнопка добавляется с классом `.remove-item-btn--inline` и `grid-column: 1 / -1`
- Первую запись нельзя удалить

### Навигация

"Резюме" добавлено в бургер-меню `base.html` (рядом с Флэш-карточками).

## Запуск (dev)

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```