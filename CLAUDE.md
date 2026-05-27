# PrepStats — CLAUDE.md

Инструмент подготовки к техническим собеседованиям. Пользователь вставляет текст вакансии, AI генерирует 8 вопросов, пользователь отвечает на каждый, AI оценивает каждый ответ. В конце — итоговый отчёт с баллами и фидбеком.

## Стек

- **Python 3.12**, **Django 6.0**
- **SQLite** (dev) / **PostgreSQL** (prod, через `DATABASE_URL=postgres`)
- **requests** — HTTP-клиент для вызова Claude API через внешний прокси-сервис
- **gevent** — асинхронные воркеры для gunicorn
- **python-dotenv** — переменные окружения из `.env`
- Фронтенд: чистые Django-шаблоны + CSS (без JS-фреймворков)

## Структура проекта

```
prep_mate/        — настройки Django (settings.py, urls.py, wsgi/asgi)
interviews/       — основное приложение
  models.py       — InterviewSession, Question, UserAnswer, Feedback
  views.py        — index, start, question, resume, history, report
  services.py     — generate_questions(), evaluate_answer() (Claude API через прокси)
  urls.py         — маршруты приложения
  admin.py        — регистрация моделей
users/            — кастомная модель пользователя + auth-страницы
  models.py       — User (AbstractUser + доп. поля)
  views.py        — register, settings_page, privacy_policy, public_offer,
                    about, contact, send_confirmation, confirm_email
  forms.py        — RegisterForm, ContactForm
  urls.py         — маршруты users-приложения
  admin.py        — CustomUserAdmin
templates/
  base.html       — навбар, спиннер-оверлей, футер
  interviews/     — index, question, report, history
  users/          — login, register, settings, about, contact,
                    privacy_policy, public_offer,
                    password_change, password_change_done,
                    password_reset, password_reset_done,
                    password_reset_confirm, password_reset_complete,
                    password_reset_email.txt (email-шаблон)
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
| `interviews_limit_per_day` | PositiveSmallIntegerField | 1 | Дневной лимит (настраивается в админке) |
| `is_subscribed` | BooleanField | False | Базовая подписка |
| `is_premium` | BooleanField | False | Расширенная подписка |
| `email_confirmed` | BooleanField | False | Подтверждён ли email |

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

### interviews.SessionAdvice
OneToOne → InterviewSession. Генерируется лениво при первом визите подписчика на страницу статистики вакансии.
| Поле | Тип |
|---|---|
| `summary` | TextField |
| `advice` | JSONField (list) |
| `focus_topics` | JSONField (list) |
| `generated_at` | DateTimeField (auto_now_add) |

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

Инвалидация кэша: при каждом визите сравнивается `session_count_at_generation` с текущим числом завершённых сессий. Если не совпадает — регенерируется.

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

/users/login/                               → login
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
/users/password-change/                     → смена пароля (требует login)
/users/password-change/done/               → успешная смена пароля
/users/password-reset/                      → запрос сброса пароля (email)
/users/password-reset/done/                → "письмо отправлено"
/users/password-reset/<uidb64>/<token>/    → форма нового пароля
/users/password-reset/complete/            → сброс завершён

/admin/                                     → Django admin
```

## Email — подтверждение и уведомления

**Отправка письма подтверждения** — хелпер `_send_confirmation_email(user, request)` в `users/views.py`:
- Вызывается автоматически сразу при регистрации
- Вызывается повторно через кнопку «Подтвердить» в настройках (`/users/send-confirmation/`)
- Токен генерируется через `django.core.signing.dumps({'uid': pk}, salt='email-confirm')`, действителен 24 часа
- Подтверждение: `confirm_email` view верифицирует токен и выставляет `user.email_confirmed = True`

**Уведомление админу при регистрации** — `_notify_admin_new_user(user)`, `fail_silently=True`.

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

В `interviews/services.py` четыре публичных метода. Claude вызывается **не напрямую через Anthropic SDK**, а через HTTP-прокси: `requests.post(settings.CLAUDE_API_SERVICE_URL, json={"prompt": ...}, headers={"X-API-Key": settings.CLAUDE_API_SERVICE_KEY}, timeout=60)`. Прокси возвращает `{"response": "..."}`.

Адрес прокси задаётся через `CLAUDE_API_SERVICE_URL`, ключ авторизации — через `CLAUDE_API_SERVICE_KEY` (env `SERVICE_API_KEY`).

**`generate_questions(vacancy_text, level='common')`** — 1 запрос при старте сессии.
При `level` ≠ `'common'` добавляет в промпт инструкцию по уровню из `_LEVEL_INSTRUCTIONS`.
Возвращает `{"job_title": ..., "company_name": ..., "questions": [{text, type}, ...]}`.

**`evaluate_answer(question_text, answer_text, vacancy_context)`** — 1 запрос после каждого ответа.
Возвращает `{"score": 1-10, "strengths": [...], "improvements": [...], "ideal_answer_hint": ..., "weakness_tags": [...], "strength_tags": [...]}`.

**`generate_session_advice(session)`** — 1 запрос при первом визите подписчика на статистику вакансии (для каждой сессии без `SessionAdvice`). Передаёт в промпт все вопросы, оценки и замечания сессии. Возвращает `{"summary": ..., "advice": [...], "focus_topics": [...]}`.

**`generate_vacancy_advice(vacancy_profile)`** — 1 запрос при генерации/обновлении `VacancyAdvice`. Передаёт развёрнутую историю всех сессий: тексты вопросов с оценками и главным замечанием фидбека по каждому вопросу, хронические и исправленные теги. Возвращает `{"overall_progress": ..., "chronic_issues": [...], "improvements": [...], "next_steps": [...], "focus_topics": [...], "verdict": ...}`.

Итого **9 запросов** на одну полную сессию (1 + 8). Запросы статистики — дополнительно, только для подписчиков. Ответ парсится через `_parse_json()`, которая снимает markdown-обёртку ` ```json ``` `.

## Переменные окружения (.env)

```
SECRET_KEY=...
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
CLAUDE_API_SERVICE_URL=https://api.fieldlog.online/ask   # прокси к Claude
SERVICE_API_KEY=...                                      # X-API-Key для прокси

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
4. `python manage.py collectstatic --noinput`
5. Запускает gunicorn: `gevent` воркеры, 2 workers, 20 connections, timeout 120s

**nginx** (`nginx/nginx.conf`):
- `default_server` на 80 и 443 → `return 444` (блокирует сканеры с чужим Host)
- `prepstats.pro` → proxy_pass на `web:8000`, таймауты 60s/120s
- `www.prepstats.pro` → редирект на apex
- `/static/` отдаётся напрямую из volume
- `/favicon.ico` и `/robots.txt` — статика без access_log

**CI/CD** (`.github/workflows/ci.yml`):
- `test` job: Python 3.12, pip cache, migrate, `python manage.py test interviews --verbosity=2`
- `deploy` job: только при `push` в `main`, SSH → dump БД → сохранить логи → `git pull` → `docker compose build --no-cache web` → `docker compose up -d`
- Деплой запускается только после успешного прохождения тестов (`needs: test`)

## Логирование

В `settings.py` настроен structured logging (формат `{asctime} {levelname} {name}: {message}`):
- `interviews` и `users` логгеры: `DEBUG` в dev, `INFO` в prod
- `django.request`: только `WARNING` и выше
- `django.security.DisallowedHost`: подавлен (боты с чужим Host не засоряют логи — nginx их отбивает на уровне `return 444`)

## Навигация

**Незалогиненный пользователь** (навбар): бренд → О проекте · Войти · Регистрация
**Залогиненный пользователь** (навбар): бренд → username · Выйти · бургер-меню `≡`
Бургер-меню dropdown: История · Статистика · Настройки · О проекте

При добавлении нового раздела — добавить `<a>` или `<span>` в `#navDropdown` в `base.html`.

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

**Ленивая генерация советов** (при каждом визите):
1. Для каждой завершённой сессии без `SessionAdvice` — вызывается `generate_session_advice()`, создаётся запись
2. Если `VacancyAdvice` отсутствует или `session_count_at_generation < текущее_кол-во_сессий` — вызывается `generate_vacancy_advice()`, создаётся/обновляется запись

**SVG-график** `overall_score` по сессиям (без JS-библиотек):
- Координаты вычисляются в Python (`_build_chart_points`, `_build_chart_labels`): `pad_left=52, plot_w=536, pad_top=8, plot_h=124`, `viewBox="0 0 600 145"`
- Координаты передаются как **целые числа** (не float!) — Django рендерит float через русскую локаль с запятой (`320,0`), что ломает SVG. Округление через `round()` → int решает проблему.
- Ось Y: метки 10/7/4/1 + вертикальная линия оси на x=52

**Динамика навыков** (`_build_tag_stats`): для каждого тега считается в скольких сессиях встречался. Статусы: `chronic` (≥50% сессий), `fixed` (был раньше, отсутствует в последних 3), `active` (остальные).

**VacancyAdvice** отображает: общий прогресс, хронические проблемы, улучшения, следующие шаги, темы для изучения (как pill-бейджи), вердикт.

### Страница подписки (`/users/subscription/`)

View `subscription` в `users/views.py`. Показывает три тарифа (Бесплатный / Базовый 299₽ / Премиум 599₽) с текущим статусом пользователя. Кнопки оплаты заглушены (tooltip «Оплата появится скоро»).

Текущий план определяется: `is_premium` → `'premium'`, `is_subscribed` → `'subscribed'`, иначе `'free'`.

## Страница настроек (`/users/settings/`)

Секции:
- **Аккаунт**: email + индикатор подтверждения (зелёный/жёлтый бейдж), кнопка «Подтвердить»; смена пароля
- **Язык интерфейса**: радиокнопки RU/EN (disabled, «Скоро»)
- **Подписка**: текущий план из полей модели + кнопка «Управлять» (disabled, «Скоро»)
- **Документы**: ссылки на политику конфиденциальности и публичную оферту

## Регистрация

`RegisterForm` расширяет `UserCreationForm`:
- Поле `email` (required, unique — проверка в `clean_email`)
- Поле `privacy_policy` (BooleanField) — чекбокс согласия с политикой и офертой; кнопка «Зарегистрироваться» заблокирована JS до отметки чекбокса (проверка начального состояния при загрузке страницы)
- После регистрации: автоматически отправляется письмо подтверждения email

## Важные детали

- `AUTH_USER_MODEL = 'users.User'` — везде использовать `get_user_model()` или `settings.AUTH_USER_MODEL`
- `RegisterForm` в `users/forms.py` — обязательно использовать вместо стандартного `UserCreationForm`
- Logout — только POST (Django 5+), в шаблоне обёрнут в `<form method="post">`
- `resume` view — находит первый `Question` без `UserAnswer` через `filter(answer__isnull=True)`
- `history` view — аннотирует queryset полями `total` и `answered` через `Count` + `Q`
- Спиннер-оверлей определён в `base.html`, активируется через `activateSpinner(phrases)` — принимает массив фраз, перемешивает случайно, меняет текст каждые 2.8s с fade-анимацией
- CSS адаптирован для мобильных через `@media (max-width: 600px)` в конце `main.css`
- Карточки истории и блок score-card в отчёте окрашиваются по `overall_score`: `score--low` (< 2, красный), `score--mid` (2–7, жёлтый), `score--high` (> 7, зелёный) — переливающийся градиент через CSS `@keyframes score-shimmer`
- В истории у каждой сессии под датой отображается уровень (`session.get_level_display`), если `level != 'common'`
- `CSRF_TRUSTED_ORIGINS` — автоматически формируется из `ALLOWED_HOSTS` (исключая localhost)

## Запуск (dev)

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```