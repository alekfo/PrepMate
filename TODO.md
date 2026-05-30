# PrepStats — TODO

## Реализовано

- [x] **Статистика** — раздел полностью реализован (`is_subscribed` / `is_premium`)
  - Обзор вакансий с трендом, средним баллом, топ слабых мест
  - Детальная страница: SVG-график, динамика навыков, VacancyAdvice с вердиктом
  - Ленивая генерация SessionAdvice и VacancyAdvice, кэш по session_count_at_generation
  - `backfill_vacancy_profiles` в entrypoint.sh для миграции старых данных

- [x] **Флэш-карточки** — `/flashcards/` и `/flashcards/train/` (только подписчики)
  - Фильтры: тип вопроса, тег слабого места, уровень сессии, только слабые (score < 4)
  - Данные из существующих Question / UserAnswer / Feedback, отдельной модели нет

- [x] **Оплата подписки через ЮKassa**
  - Модели `Payment` и `Subscription` в `users/models.py`
  - `users/services.py`: create_yookassa_payment, activate_subscription, deactivate_user_subscription
  - Webhook `POST /users/payment/webhook/` с проверкой IP по официальному списку ЮKassa
  - Страница возврата `/users/payment/return/` (success / pending)
  - `interviews_limit_per_day` управляется автоматически: free→1, subscribed→2, premium→5
  - Письмо-подтверждение пользователю после успешной оплаты
  - Письмо об истечении подписки при деактивации
  - Management command `deactivate_expired_subscriptions` + cron ежедневно в 3:00
  - Paywall-страница `/users/subscription/` с реальными кнопками «Купить»

- [x] **Безопасность webhook** — проверка IP через `ipaddress` (CIDR + отдельные IP)
- [x] **FileBasedCache** — межпроцессный кэш вместо LocMemCache (работает при 2 воркерах)

---

## Функциональность — следующие этапы

### Без API (из существующих данных)

- [ ] **Удаление сессии** — кнопка «Удалить» в истории и отчёте. Простой DELETE view с подтверждением. Убирает сессию вместе с вопросами, ответами и фидбеком (cascade).
- [ ] **Фильтры и поиск в истории** — фильтр по уровню (junior/middle/pro), фильтр «только завершённые», сортировка по баллу (лучшие/худшие сверху), поиск по названию должности и компании. Всё через GET-параметры.
- [ ] **История вакансий** — страница управления сохранёнными вакансиями (переименовать, удалить).

---

### Прочее

- [ ] **Экспорт PDF** — итоговый отчёт сессии в PDF (`weasyprint` или `reportlab`).
- [ ] **Behavioral/STAR режим** — отдельный режим с фокусом на поведенческие вопросы и структуру STAR-ответа.
- [ ] **Telegram-бот** — интеграция для прохождения интервью через бота.
- [ ] **Язык интерфейса EN** — поле в настройках сейчас disabled.

---

## Технический долг

- [ ] **N+1 в `flashcards` view** — `vp.sessions.filter(status='completed').exists()` вызывается в Python-цикле, один SQL на каждую вакансию. Переписать через аннотацию `Count` + фильтр в ORM.
- [ ] **`index` view грузит все сессии без лимита** — `InterviewSession.objects.filter(user=request.user)` без среза. Добавить `[:50]` или переписать дедупликацию через SQL `DISTINCT ON`.
- [ ] **`if True:` в `statistics_overview`** — мёртвый блок, убрать лишний уровень отступа.
- [ ] **`interviews_used` race condition** — обновляется через `update()` без `F()` в `start` view, потенциальный race при одновременных запросах одного пользователя. Заменить на `F('interviews_used') + 1`.
- [ ] **Старые `Feedback` без тегов** — поля `weakness_tags` / `strength_tags` пустые для сессий до введения тегов. Блок «Динамика навыков» для них будет пустым. Решение: мириться или сделать ретроспективную оценку.
- [ ] **`SessionAdvice` генерируется синхронно** — при большом числе сессий без советов страница статистики будет долго грузиться. Решение: фоновая задача (Celery) или пагинация генерации.
- [ ] **Нет health check в docker-compose** — при падении `web` контейнера nginx будет отдавать 502 до рестарта. Добавить `healthcheck` в docker-compose.yml.