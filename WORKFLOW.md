# Git Workflow — PrepMate

## Структура веток

```
main       — продакшн (prepstats.pro). Только через PR из release.
release    — стейджинг / накопитель фич перед деплоем.
fix_*      — фича-ветки для конкретных изменений (от release).
```

---

## Стандартный цикл

### 1. Начало новой задачи

```bash
git checkout release
git pull origin release
git checkout -b fix_название_задачи
```

### 2. Работа над задачей

```bash
# вносишь изменения...
git add interviews/views.py templates/interviews/some.html
git commit -m "краткое описание что сделано"
```

### 3. Публикация фича-ветки

```bash
git push origin fix_название_задачи
```

### 4. Слияние фичи в release

Вариант А — через GitHub PR (`fix_название_задачи → release`):
- создать PR на GitHub
- смёрджить

Вариант Б — локально напрямую:
```bash
git checkout release
git merge fix_название_задачи
git push origin release
```

### 5. Деплой в продакшн (release → main)

Когда в `release` накопилось достаточно изменений:

1. Создать PR на GitHub: `release → main`
2. Убедиться что CI (тесты) зелёный
3. Смёрджить PR

### 6. Синхронизация release после деплоя

**Обязательно после каждого merge в main:**

```bash
git checkout main
git pull origin main

git checkout release
git merge main
git push origin release
```

Это предотвращает "This branch is out-of-date" при следующем PR.

---

## Схема полного цикла

```
release ──── fix_задача ────┐
   │                        │ merge
   │◄───────────────────────┘
   │
   │  PR release → main
   ▼
 main  (деплой через CI/CD)
   │
   │  git merge main
   ▼
release  (синхронизирован)
```

---

## Частые команды

```bash
# Посмотреть граф веток
git log --oneline --graph --all -15

# Удалить фича-ветку после merge
git branch -d fix_название_задачи
git push origin --delete fix_название_задачи

# Посмотреть текущую ветку и статус
git status
```

---

## Правила

- Никогда не пушить напрямую в `main` — только через PR
- Фича-ветки называть `fix_*` или `feature_*` — понятно и коротко
- После merge PR в `main` — сразу синхронизировать `release`
- Перед началом новой задачи — `git pull origin release`