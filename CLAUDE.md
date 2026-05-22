# PrepStats — CLAUDE.md

Инструмент подготовки к техническим собеседованиям. Пользователь вставляет текст вакансии, AI генерирует 8 вопросов, пользователь отвечает на каждый, AI оценивает каждый ответ. В конце — итоговый отчёт с баллами и фидбеком.

## Стек

- **Python 3.12**, **Django 6.0**
- **SQLite** (dev) / **PostgreSQL** (prod, через `DATABASE_URL=postgres`)
- **Anthropic SDK** — Claude API для генерации вопросов и оценки ответов
- **python-dotenv** — переменные окружения из `.env`
- Фронтенд: чистые Django-шаблоны + CSS (без JS-фреймворков)

## Структура проекта

```
prep_mate/        — настройки Django (settings.py, urls.py, wsgi/asgi)
interviews/       — основное приложение
  models.py       — InterviewSession, Question, UserAnswer, Feedback
  views.py        — index, start, question, resume, history, report
  services.py     — generate_questions(), evaluate_answer() (Claude API)
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
```

## Модели

### users.User (AbstractUser +)
| Поле | Тип | По умолчанию | Назначение |
|---|---|---|---|
| `email` | EmailField | — | Уникальный (unique=True), обязательный при регистрации |
| `interviews_used` | PositiveIntegerField | 0 | Всего интервью запущено (инкремент при старте) |
| `interviews_limit_per_day` | PositiveSmallIntegerField | 3 | Дневной лимит (настраивается в админке) |
| `is_subscribed` | BooleanField | False | Базовая подписка |
| `is_premium` | BooleanField | False | Расширенная подписка |
| `email_confirmed` | BooleanField | False | Подтверждён ли email |

### interviews.InterviewSession
Статусы: `pending` / `in_progress` / `completed`
Хранит: текст вакансии, job_title, company_name, overall_score, created_at, completed_at

### interviews.Question
Типы: `technical` / `behavioral` / `situational`
8 вопросов на сессию, порядок через `order` (0–7)

### interviews.UserAnswer
OneToOne → Question. Хранит текст ответа.

### interviews.Feedback
OneToOne → UserAnswer. Хранит: score (1–10), strengths (JSON), improvements (JSON), ideal_answer_hint.

## URL-маршруты

```
/                                           → index (форма вакансии / лендинг)
/start/                                     → start (POST, создаёт сессию)
/history/                                   → history (список сессий пользователя)
/session/<id>/resume/                       → resume (редирект на первый неотвеченный вопрос)
/session/<id>/question/<order>/             → question (GET показ / POST сохранение ответа)
/session/<id>/report/                       → report (итоговый отчёт)

/users/login/                               → login
/users/logout/                              → logout (только POST)
/users/register/                            → register
/users/settings/                            → settings (требует login)
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
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER   ← важно, иначе PasswordResetView шлёт с webmaster@localhost
```

## Блокировка начала интервью

В `start` view и в UI (шаблон `index.html`) проверки выполняются **в таком порядке**:
1. `not user.email_confirmed` → ошибка «Подтвердите email»
2. `used_today >= user.interviews_limit_per_day` → ошибка «Дневной лимит исчерпан»

Кнопка «Начать интервью» в UI: при блокировке заменяется на `.btn-blocked-wrap` с CSS hover-tooltip (tooltip всплывает при наведении, не всегда виден). Textarea тоже блокируется.

## Claude API — логика вызовов

В `interviews/services.py` два публичных метода:

**`generate_questions(vacancy_text)`** — 1 запрос при старте сессии.
Возвращает `{"job_title": ..., "company_name": ..., "questions": [{text, type}, ...]}`.
Модель и ключ берутся из `settings.CLAUDE_MODEL` / `settings.CLAUDE_API_KEY`.

**`evaluate_answer(question_text, answer_text, vacancy_context)`** — 1 запрос после каждого ответа.
Возвращает `{"score": 1-10, "strengths": [...], "improvements": [...], "ideal_answer_hint": ...}`.

Итого **9 запросов** на одну полную сессию (1 + 8). Ответ парсится через `_parse_json()`, которая снимает markdown-обёртку ` ```json ``` `.

## Переменные окружения (.env)

```
SECRET_KEY=...
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
CLAUDE_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-6

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

## Навигация

**Незалогиненный пользователь** (навбар): бренд → О проекте · Войти · Регистрация
**Залогиненный пользователь** (навбар): бренд → username · Выйти · бургер-меню `≡`
Бургер-меню dropdown: История · Статистика (disabled) · Настройки · О проекте

При добавлении нового раздела — добавить `<a>` или `<span>` в `#navDropdown` в `base.html`.

## Страница index

- **Незалогиненный**: заголовок «Начни свой карьерный путь здесь», кнопки «Зарегистрироваться» + «Войти» (`.landing-cta`)
- **Залогиненный**: заголовок «Готов проверить себя?», форма с textarea
- `index` view передаёт `past_vacancies` — до 5 последних уникальных сессий (дедупликация по `vacancy_text`)
- Dropdown «Из истории» подставляет текст вакансии в textarea через JS
- Textarea: `rows=4`, авторастягивается (`autoGrow`), `resize: none`

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
- Спиннер-оверлей определён в `base.html`, активируется JS через `.classList.add('active')`
- CSS адаптирован для мобильных через `@media (max-width: 600px)` в конце `main.css`

## Запуск

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```