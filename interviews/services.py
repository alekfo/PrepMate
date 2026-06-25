import json
import logging
import re
import time
from collections import Counter

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _ask(prompt: str, _retries: int = 2) -> str:
    """Отправляет промпт в Claude через HTTP-прокси. До 3 попыток с экспоненциальной паузой.

    Повторяет запрос при сетевых ошибках и при пустом ответе.
    Бросает RuntimeError если все попытки исчерпаны.
    """
    for attempt in range(_retries + 1):
        t0 = time.monotonic()
        try:
            response = requests.post(
                settings.CLAUDE_API_SERVICE_URL,
                json={"prompt": prompt},
                headers={"X-API-Key": settings.CLAUDE_API_SERVICE_KEY},
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            if attempt < _retries:
                logger.warning("Claude API request failed, retry %d/%d: %s", attempt + 1, _retries, e)
                time.sleep(2 ** attempt)
                continue
            logger.error("Claude API request failed (%.1fs): %s", time.monotonic() - t0, e)
            raise
        elapsed = time.monotonic() - t0
        text = response.json().get("response", "")
        if text.strip():
            logger.debug("Claude API response in %.1fs, %d chars", elapsed, len(text))
            return text
        if attempt < _retries:
            logger.warning("Empty response from Claude API, retry %d/%d", attempt + 1, _retries)
            time.sleep(2 ** attempt)
    raise RuntimeError("Claude API returned empty response after retries")


def _parse_json(text: str) -> dict | list:
    """Парсит JSON из ответа Claude, снимая markdown-обёртку ```json``` если она есть."""
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    return json.loads(match.group(1) if match else text.strip())


_VALID_TAGS = frozenset({
    'depth', 'examples', 'structure', 'communication',
    'confidence', 'relevance', 'experience', 'proactivity',
})


_LEVEL_INSTRUCTIONS = {
    'junior': (
        'Уровень кандидата: Junior (до 2 лет опыта). '
        'Вопросы должны быть базового уровня — фундаментальные концепции, '
        'простые практические задачи, понимание основ.'
    ),
    'middle': (
        'Уровень кандидата: Middle (2–5 лет опыта). '
        'Вопросы среднего уровня — системное мышление, типичные рабочие сценарии, '
        'проектирование решений, понимание trade-off\'ов.'
    ),
    'pro': (
        'Уровень кандидата: Senior/Pro (более 5 лет опыта). '
        'Вопросы высокого уровня — архитектурные решения, сложные нестандартные сценарии, '
        'масштабирование, технические решения в условиях жёстких ограничений.'
    ),
}


def generate_questions(vacancy_text: str, level: str = 'common') -> list[dict]:
    """Генерирует 8 вопросов для интервью на основе текста вакансии и уровня кандидата.

    Возвращает dict с ключами job_title, company_name и questions (список {text, type}).
    """
    logger.info("Generating questions for vacancy (%d chars), level=%s", len(vacancy_text), level)
    level_instruction = _LEVEL_INSTRUCTIONS.get(level, '')
    level_line = f'\n{level_instruction}\n' if level_instruction else ''
    text = _ask(f"""Ты эксперт по техническим собеседованиям. Проанализируй вакансию и сгенерируй вопросы для интервью.

                        Вакансия:
                        {vacancy_text}
{level_line}
                        Сгенерируй 8 вопросов: 5 технических, 2 поведенческих (STAR-метод), 1 ситуационный.
                        Каждый раз генерируй уникальный набор — варьируй формулировки, углы подхода, уровень глубины и конкретности. Избегай банальных и предсказуемых вопросов.
                        Также определи название должности и компанию из текста вакансии (если указаны).

                        Ответь строго в формате JSON:
                        {{
                          "job_title": "название должности или пустая строка",
                          "company_name": "название компании или пустая строка",
                          "questions": [
                            {{"text": "вопрос", "type": "technical|behavioral|situational"}},
                            ...
                          ]
                        }}""")
    result = _parse_json(text)
    logger.info(
        "Questions generated: job=%r company=%r count=%d",
        result.get('job_title', ''), result.get('company_name', ''), len(result.get('questions', [])),
    )
    return result


def evaluate_answer(question_text: str, answer_text: str, vacancy_context: str) -> dict:
    """Оценивает ответ кандидата на вопрос интервью.

    Возвращает dict: score (1–10), strengths, improvements, ideal_answer_hint,
    weakness_tags и strength_tags (только теги из _VALID_TAGS).
    """
    logger.debug("Evaluating answer (%d chars) for question: %.60s…", len(answer_text), question_text)
    text = _ask(f"""Оцени ответ кандидата на вопрос интервью.

                        Контекст вакансии: {vacancy_context[:500]}

                        Вопрос: {question_text}
                        Ответ кандидата: {answer_text}

                        Ответь строго в формате JSON:
                        {{
                          "score": <число от 1 до 10>,
                          "strengths": ["сильная сторона 1", "сильная сторона 2"],
                          "improvements": ["что улучшить 1", "что улучшить 2"],
                          "ideal_answer_hint": "краткий намёк на идеальный ответ",
                          "weakness_tags": [],
                          "strength_tags": []
                        }}

                        Для weakness_tags выбери 0–2 тега из списка (только если явно выражено):
                        depth, examples, structure, communication, confidence, relevance, experience, proactivity
                        Для strength_tags — те же теги, но только если сторона явно продемонстрирована.
                        Используй исключительно теги из этого списка, без собственных значений.""")
    result = _parse_json(text)
    result['weakness_tags'] = [t for t in result.get('weakness_tags', []) if t in _VALID_TAGS]
    result['strength_tags'] = [t for t in result.get('strength_tags', []) if t in _VALID_TAGS]
    logger.info("Answer evaluated: score=%s weakness=%s strength=%s",
                result.get('score'), result.get('weakness_tags'), result.get('strength_tags'))
    return result



def generate_vacancy_advice(vacancy_profile) -> dict:
    """Генерирует агрегированный AI-анализ прогресса по всем сессиям вакансии.

    Передаёт в промпт историю всех сессий (баллы, вопросы, первое замечание),
    хронические и исправленные теги слабых мест, уровни подготовки.
    Возвращает dict: overall_progress, chronic_issues, improvements,
    next_steps, focus_topics, verdict.
    """
    logger.info("Generating vacancy advice for vacancy_profile=%d", vacancy_profile.id)

    sessions = list(
        vacancy_profile.sessions
        .filter(status='completed')
        .order_by('completed_at')
        .prefetch_related('questions__answer__feedback')
    )

    # Собираем детальные данные по каждой сессии
    session_rows = []
    all_weakness_tags: list[str] = []
    all_strength_tags: list[str] = []

    for s in sessions:
        questions = list(s.questions.all())
        qa_lines = []
        for q in questions:
            answer = getattr(q, 'answer', None)
            feedback = getattr(answer, 'feedback', None) if answer else None
            if feedback:
                all_weakness_tags.extend(feedback.weakness_tags)
                all_strength_tags.extend(feedback.strength_tags)
                top_issue = feedback.improvements[0] if feedback.improvements else ''
                qa_lines.append(
                    f'    [{feedback.score}/10] {q.text[:120]}'
                    + (f'\n      → {top_issue}' if top_issue else '')
                )

        date_str = s.completed_at.strftime('%Y-%m-%d') if s.completed_at else '—'
        qa_block = '\n'.join(qa_lines) if qa_lines else '    (нет данных)'
        session_rows.append(
            f'  Сессия {date_str}, общий балл {s.overall_score:.1f}:\n{qa_block}'
        )

    sessions_block = '\n\n'.join(session_rows)
    total = len(sessions)

    level_counts = Counter(s.get_level_display() for s in sessions)
    levels_used = ', '.join(
        f'{label} ({count} сес.)' if count > 1 else label
        for label, count in level_counts.most_common()
    )

    # Хронические и исправленные теги
    chronic = _chronic_tags(sessions, threshold=0.5)
    fixed = _fixed_tags(sessions, last_n=3)

    chronic_line = f'Хронические слабые места: {", ".join(f"{t} ({c}/{total})" for t, c in chronic)}' if chronic else ''
    fixed_line = f'Исправлено (не встречается в последних 3 сессиях): {", ".join(fixed)}' if fixed else ''

    text = _ask(f"""Ты мотивирующий карьерный коуч. Проанализируй прогресс кандидата по вакансии на основе всех прошедших интервью и дай конкретные, персональные рекомендации.

Вакансия: {vacancy_profile.job_title or "не указана"}{f", {vacancy_profile.company_name}" if vacancy_profile.company_name else ""}
Требования вакансии: {vacancy_profile.vacancy_text[:500]}
Уровень подготовки: {levels_used}

Важно: кандидат проходил mock-интервью на уровне «{levels_used}». Оценивай прогресс и готовность относительно этого уровня подготовки — не как финальный вердикт по всей вакансии.

История интервью ({total}):
{sessions_block}

{chronic_line}
{fixed_line}

Пиши конкретно — ссылайся на реальные вопросы и замечания из истории выше. Избегай общих фраз.

Ответь строго в формате JSON:
{{
  "overall_progress": "Общая оценка динамики — 2-3 предложения со ссылками на конкретные результаты. Отметь рост там, где он есть.",
  "chronic_issues": ["Конкретная хроническая проблема со ссылкой на вопрос/тему", "..."],
  "improvements": ["Конкретное улучшение с примером из истории", "..."],
  "next_steps": [
    "Конкретный шаг привязанный к слабым местам этого кандидата",
    "...",
    "..."
  ],
  "focus_topics": ["Конкретная тема из вопросов, где были проблемы", "..."],
  "verdict": "Оцени где сейчас находится кандидат на пути к этой вакансии: что уже работает на нужном уровне, 1-2 темы которые блокируют прохождение, реалистичный срок до готовности при целенаправленной подготовке. Тон — поддерживающий, без приговора."
}}

focus_topics — только темы, в которых кандидат реально ошибался. Не генерируй URL.""")

    result = _parse_json(text)
    logger.info("Vacancy advice generated for vacancy_profile=%d, sessions=%d", vacancy_profile.id, total)
    return result


def _top_tags(tags: list[str], n: int = 2) -> list[str]:
    """Возвращает n самых частых тегов из плоского списка."""
    counts: dict[str, int] = {}
    for t in tags:
        counts[t] = counts.get(t, 0) + 1
    return [t for t, _ in sorted(counts.items(), key=lambda x: -x[1])[:n]]


def _chronic_tags(sessions: list, threshold: float = 0.5) -> list[tuple[str, int]]:
    """Возвращает теги слабых мест, встречающиеся в >= threshold доли сессий (по умолчанию 50%).

    Результат: список кортежей (tag, count), отсортированных по убыванию.
    """
    total = len(sessions)
    if not total:
        return []
    counts: dict[str, int] = {}
    for s in sessions:
        seen = set()
        for q in s.questions.all():
            feedback = getattr(getattr(q, 'answer', None), 'feedback', None)
            if feedback:
                for t in feedback.weakness_tags:
                    if t not in seen:
                        counts[t] = counts.get(t, 0) + 1
                        seen.add(t)
    return [(t, c) for t, c in counts.items() if c / total >= threshold]


def _fixed_tags(sessions: list, last_n: int = 3) -> list[str]:
    """Возвращает теги, которые встречались в ранних сессиях, но исчезли в последних last_n.

    Используется для определения исправленных слабых мест кандидата.
    """
    if len(sessions) <= last_n:
        return []
    early = sessions[:-last_n]
    recent = sessions[-last_n:]

    def session_tags(s) -> set[str]:
        result = set()
        for q in s.questions.all():
            feedback = getattr(getattr(q, 'answer', None), 'feedback', None)
            if feedback:
                result.update(feedback.weakness_tags)
        return result

    early_tags = set().union(*[session_tags(s) for s in early])
    recent_tags = set().union(*[session_tags(s) for s in recent])
    return sorted(early_tags - recent_tags)