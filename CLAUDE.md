# PrepMate — CLAUDE.md

Инструмент подготовки к техническим собеседованиям. Пользователь вставляет текст вакансии, AI генерирует 8 вопросов, пользователь отвечает на каждый, AI оценивает каждый ответ. В конце — итоговый отчёт с баллами и фидбеком.

## Стек

- **Python 3.14**, **Django 6.0**
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
users/            — кастомная модель пользователя
  models.py       — User (AbstractUser + доп. поля)
  views.py        — register
  forms.py        — RegisterForm (кастомная, для users.User)
  admin.py        — CustomUserAdmin
templates/
  base.html       — навбар, подключение CSS, spinner overlay
  interviews/     — index, question, report, history
  users/          — login, register
static/css/main.css — минималистичный стиль (Inter, нейтральная палитра)
```

## Модели

### users.User (AbstractUser +)
| Поле | Тип | По умолчанию | Назначение |
|---|---|---|---|
| `interviews_used` | PositiveIntegerField | 0 | Всего интервью запущено (инкремент при старте) |
| `interviews_limit_per_day` | PositiveSmallIntegerField | 3 | Дневной лимит (настраивается в админке) |
| `is_subscribed` | BooleanField | False | Базовая подписка |
| `is_premium` | BooleanField | False | Расширенная подписка |

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
/                                       → index (форма вакансии)
/start/                                 → start (POST, создаёт сессию)
/history/                               → history (список сессий пользователя)
/session/<id>/resume/                   → resume (редирект на первый неотвеченный вопрос)
/session/<id>/question/<order>/         → question (GET показ / POST сохранение ответа)
/session/<id>/report/                   → report (итоговый отчёт)
/users/login/                           → login
/users/logout/                          → logout (только POST)
/users/register/                        → register
/admin/                                 → Django admin
```

## Claude API — логика вызовов

В `interviews/services.py` два публичных метода:

**`generate_questions(vacancy_text)`** — 1 запрос при старте сессии.
Возвращает `{"job_title": ..., "company_name": ..., "questions": [{text, type}, ...]}`.
Модель и ключ берутся из `settings.CLAUDE_MODEL` / `settings.CLAUDE_API_KEY`.

**`evaluate_answer(question_text, answer_text, vacancy_context)`** — 1 запрос после каждого ответа.
Возвращает `{"score": 1-10, "strengths": [...], "improvements": [...], "ideal_answer_hint": ...}`.

Итого **9 запросов** на одну полную сессию (1 + 8). Ответ всегда парсится через `_parse_json()`, которая снимает markdown-обёртку ` ```json ``` ` если модель её добавила.

## Переменные окружения (.env)

```
SECRET_KEY=...
DEBUG=True
CLAUDE_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-6
DATABASE_URL=          # пусто = SQLite, "postgres" = PostgreSQL
DB_NAME=...
DB_USER=...
DB_PASSWORD=...
DB_HOST=db
DB_PORT=5432
```

## Дневной лимит интервью

Лимит считается динамически через БД — без отдельного счётчика и без сброса:
```python
InterviewSession.objects.filter(user=user, created_at__date=timezone.localdate()).count()
```
Если `used_today >= user.interviews_limit_per_day` — кнопка «Начать интервью» блокируется в UI и `start` view возвращает 302 с сообщением об ошибке.

## Важные детали

- `AUTH_USER_MODEL = 'users.User'` — кастомная модель, везде использовать `get_user_model()` или `settings.AUTH_USER_MODEL`
- `RegisterForm` в `users/forms.py` — обязательно использовать вместо стандартного `UserCreationForm`, иначе `AttributeError: Manager isn't available; 'auth.User' has been swapped`
- Logout — только POST (Django 5+), в шаблоне обёрнут в `<form method="post">`
- `resume` view — находит первый `Question` без `UserAnswer` через `filter(answer__isnull=True)`
- `history` view — аннотирует queryset полями `total` и `answered` через `Count` + `Q`
- Спиннер-оверлей определён в `base.html`, активируется JS-ом в конкретных шаблонах через `.classList.add('active')`

## Запуск

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```
