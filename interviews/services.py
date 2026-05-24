import json
import logging
import re
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _ask(prompt: str) -> str:
    t0 = time.monotonic()
    try:
        response = requests.post(
            settings.CLAUDE_API_SERVICE_URL,
            json={"prompt": prompt},
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error("Claude API request failed (%.1fs): %s", time.monotonic() - t0, e)
        raise
    elapsed = time.monotonic() - t0
    logger.debug("Claude API response in %.1fs, %d chars", elapsed, len(response.text))
    return response.json()["response"]


def _parse_json(text: str) -> dict | list:
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    return json.loads(match.group(1) if match else text.strip())


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
                          "ideal_answer_hint": "краткий намёк на идеальный ответ"
                        }}""")
    result = _parse_json(text)
    logger.info("Answer evaluated: score=%s", result.get('score'))
    return result