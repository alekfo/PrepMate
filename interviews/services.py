import json
import re
from xml.etree.ElementTree import indent

import anthropic
from django.conf import settings


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.CLAUDE_API_KEY)


def _parse_json(text: str) -> dict | list:
    # strip markdown code fences if present
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    return json.loads(match.group(1) if match else text.strip())


def generate_questions(vacancy_text: str) -> list[dict]:
    client = _get_client()
    response = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=1500,
        messages=[{
            'role': 'user',
            'content': f"""Ты эксперт по техническим собеседованиям. Проанализируй вакансию и сгенерируй вопросы для интервью.

                        Вакансия:
                        {vacancy_text}
                        
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
                        }}"""
        }],
    )
    return _parse_json(response.content[0].text)


def evaluate_answer(question_text: str, answer_text: str, vacancy_context: str) -> dict:
    client = _get_client()
    response = client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=1000,
        messages=[{
            'role': 'user',
            'content': f"""Оцени ответ кандидата на вопрос интервью.

                        Контекст вакансии: {vacancy_context[:500]}
                        
                        Вопрос: {question_text}
                        Ответ кандидата: {answer_text}
                        
                        Ответь строго в формате JSON:
                        {{
                          "score": <число от 1 до 10>,
                          "strengths": ["сильная сторона 1", "сильная сторона 2"],
                          "improvements": ["что улучшить 1", "что улучшить 2"],
                          "ideal_answer_hint": "краткий намёк на идеальный ответ"
                        }}"""
        }],
    )
    return _parse_json(response.content[0].text)

if __name__ == "__main__":
    import django, os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "prep_mate.settings")
    django.setup()
    res = generate_questions("Python backend разработчик")
    print(res)