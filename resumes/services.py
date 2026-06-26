import json
import logging
import re
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _ask(prompt: str, _retries: int = 2) -> str:
    for attempt in range(_retries + 1):
        t0 = time.monotonic()
        try:
            response = requests.post(
                settings.CLAUDE_API_SERVICE_URL,
                json={"prompt": prompt},
                headers={"X-API-Key": settings.CLAUDE_API_SERVICE_KEY},
                timeout=90,
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
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    return json.loads(match.group(1) if match else text.strip())


def polish_resume(resume) -> dict:
    """Отправляет все сырые данные резюме в Claude и возвращает улучшенные секции.

    Возвращает dict вида {section_type: улучшенный_контент}, где контент
    соответствует той же структуре, что и raw_content каждой секции.
    """
    logger.info("Polishing resume id=%d profession=%r", resume.id, resume.profession)

    sections = {s.section_type: s.raw_content for s in resume.sections.all()}

    contacts = sections.get('contacts', {})
    summary = sections.get('summary', {})
    experience = sections.get('experience', [])
    education = sections.get('education', [])
    skills = sections.get('skills', {})
    languages = sections.get('languages', [])
    certifications = sections.get('certifications', [])

    exp_lines = []
    for i, e in enumerate(experience, 1):
        exp_lines.append(
            f"  {i}. {e.get('company', '')} | {e.get('position', '')} | "
            f"{e.get('period_start', '')} — {e.get('period_end', '')}\n"
            f"     Обязанности: {e.get('responsibilities', '')}\n"
            f"     Достижения: {e.get('achievements', '') or 'не указаны'}"
        )

    edu_lines = []
    for i, e in enumerate(education, 1):
        edu_lines.append(
            f"  {i}. {e.get('institution', '')} | {e.get('specialty', '')} | "
            f"{e.get('degree', '')} | {e.get('year', '')}"
        )

    lang_lines = [f"  {l.get('language', '')} — {l.get('level', '')}" for l in languages]

    cert_lines = []
    for c in certifications:
        cert_lines.append(f"  {c.get('name', '')} | {c.get('platform', '')} | {c.get('year', '')}")

    prompt = f"""Ты профессиональный HR-консультант и карьерный коуч. Пользователь предоставил сырые данные для своего резюме. Твоя задача — улучшить формулировки, исправить грамматику, сделать текст профессиональным и убедительным, сохранив все факты.

Целевая должность: {resume.profession}

=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===

КОНТАКТЫ:
  Имя: {contacts.get('full_name', '')}
  Email: {contacts.get('email', '')}
  Телефон: {contacts.get('phone', '')}
  Город: {contacts.get('city', '')}
  LinkedIn: {contacts.get('linkedin', '') or 'не указан'}
  GitHub/Portfolio: {contacts.get('github', '') or 'не указан'}

О СЕБЕ:
{summary.get('text', 'не заполнено')}

ОПЫТ РАБОТЫ:
{chr(10).join(exp_lines) if exp_lines else 'не указан'}

ОБРАЗОВАНИЕ:
{chr(10).join(edu_lines) if edu_lines else 'не указано'}

НАВЫКИ:
  Hard skills: {skills.get('hard_skills', 'не указаны')}
  Soft skills: {skills.get('soft_skills', 'не указаны')}

ЯЗЫКИ:
{chr(10).join(lang_lines) if lang_lines else 'не указаны'}

КУРСЫ И СЕРТИФИКАТЫ:
{chr(10).join(cert_lines) if cert_lines else 'не указаны'}

=== ИНСТРУКЦИИ ===

1. Блок "О себе": перепиши в 2–4 профессиональных предложения, отражающих опыт и ценность кандидата для должности "{resume.profession}".
2. Опыт работы: улучши формулировки обязанностей и достижений — используй глаголы действия, конкретику. Если достижения не указаны — не придумывай цифры.
3. Навыки: структурируй и дополни при необходимости, не добавляй навыки которых нет.
4. Контакты, образование, языки, сертификаты — исправь только грамматику и форматирование, факты не меняй.

Ответь строго в формате JSON:
{{
  "contacts": {{
    "full_name": "...",
    "email": "...",
    "phone": "...",
    "city": "...",
    "linkedin": "...",
    "github": "..."
  }},
  "summary": {{
    "text": "улучшенный текст о себе"
  }},
  "experience": [
    {{
      "company": "...",
      "position": "...",
      "period_start": "...",
      "period_end": "...",
      "responsibilities": "улучшенные обязанности",
      "achievements": "улучшенные достижения или пустая строка"
    }}
  ],
  "education": [
    {{
      "institution": "...",
      "specialty": "...",
      "degree": "...",
      "year": "..."
    }}
  ],
  "skills": {{
    "hard_skills": "...",
    "soft_skills": "..."
  }},
  "languages": [
    {{"language": "...", "level": "..."}}
  ],
  "certifications": [
    {{"name": "...", "platform": "...", "year": "..."}}
  ]
}}"""

    text = _ask(prompt)
    result = _parse_json(text)
    logger.info("Resume polished: id=%d", resume.id)
    return result