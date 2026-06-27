import logging
import re
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import Resume, ResumeSection
from .services import polish_resume

logger = logging.getLogger(__name__)

RESUME_STEPS = ['contacts', 'summary', 'experience', 'education', 'skills', 'languages', 'certifications']

STEP_TITLES = {
    'contacts': 'Контактная информация',
    'summary': 'О себе',
    'experience': 'Опыт работы',
    'education': 'Образование',
    'skills': 'Навыки',
    'languages': 'Языки',
    'certifications': 'Курсы и сертификаты',
}

SECTION_ORDER = {step: i for i, step in enumerate(RESUME_STEPS)}

_REPEATING_STEPS = {'experience', 'education', 'languages', 'certifications'}


def _has_subscription(user):
    return user.is_subscribed or user.is_premium


@login_required
def resume_list(request):
    if not _has_subscription(request.user):
        return redirect('users:subscription')

    resumes = Resume.objects.filter(
        user=request.user,
    ).exclude(status=Resume.STATUS_DRAFT)

    drafts = Resume.objects.filter(user=request.user, status=Resume.STATUS_DRAFT)

    return render(request, 'resumes/list.html', {
        'resumes': resumes,
        'drafts': drafts,
    })


@login_required
def resume_new(request):
    if not _has_subscription(request.user):
        return redirect('users:subscription')

    if request.method != 'POST':
        return redirect('resumes:list')

    profession = request.POST.get('profession', '').strip()
    if not profession:
        messages.error(request, 'Укажите целевую должность.')
        return redirect('resumes:list')

    resume = Resume.objects.create(user=request.user, profession=profession)
    logger.info("Resume created: id=%d user=%s profession=%r", resume.id, request.user.username, profession)
    return redirect('resumes:step', resume_id=resume.id, step='contacts')


@login_required
def resume_step(request, resume_id, step):
    if not _has_subscription(request.user):
        return redirect('users:subscription')

    if step not in RESUME_STEPS:
        return redirect('resumes:list')

    resume = get_object_or_404(Resume, id=resume_id, user=request.user)

    if resume.status != Resume.STATUS_DRAFT:
        return redirect('resumes:detail', resume_id=resume.id)

    step_index = RESUME_STEPS.index(step)
    is_last = step_index == len(RESUME_STEPS) - 1

    existing_section = resume.get_section(step)
    existing_content = existing_section.raw_content if existing_section else None

    if request.method == 'POST':
        raw_content = _parse_step_post(request.POST, step)
        action = request.POST.get('action', '')

        skip_validation = (step == 'certifications' and action == 'skip')
        if not skip_validation:
            error = _validate_step(step, raw_content)
            if error:
                return render(request, 'resumes/step.html', {
                    'resume': resume,
                    'step': step,
                    'step_title': STEP_TITLES[step],
                    'step_index': step_index,
                    'step_total': len(RESUME_STEPS),
                    'is_last': is_last,
                    'is_repeating': step in _REPEATING_STEPS,
                    'prev_step': RESUME_STEPS[step_index - 1] if step_index > 0 else None,
                    'existing': raw_content,
                    'error': error,
                })

        if existing_section:
            existing_section.raw_content = raw_content
            existing_section.save()
        else:
            ResumeSection.objects.create(
                resume=resume,
                section_type=step,
                order=SECTION_ORDER[step],
                raw_content=raw_content,
            )

        if is_last:
            _run_ai_polish(resume)
            return redirect('resumes:detail', resume_id=resume.id)

        next_step = RESUME_STEPS[step_index + 1]
        return redirect('resumes:step', resume_id=resume.id, step=next_step)

    return render(request, 'resumes/step.html', {
        'resume': resume,
        'step': step,
        'step_title': STEP_TITLES[step],
        'step_index': step_index,
        'step_total': len(RESUME_STEPS),
        'is_last': is_last,
        'is_repeating': step in _REPEATING_STEPS,
        'prev_step': RESUME_STEPS[step_index - 1] if step_index > 0 else None,
        'existing': existing_content,
    })


def _validate_step(step, raw_content):
    if step == 'contacts':
        if not raw_content.get('full_name'):
            return 'Укажите полное имя.'
        if not raw_content.get('email') and not raw_content.get('phone'):
            return 'Укажите email или телефон.'
    elif step == 'summary':
        if not raw_content.get('text'):
            return 'Напишите что-нибудь о себе — AI улучшит формулировки.'
    elif step == 'experience':
        for i, item in enumerate(raw_content, 1):
            if not item.get('company'):
                return f'Место {i}: укажите название компании.'
            if not item.get('period_start') or not item.get('period_end'):
                return f'Место {i}: укажите период работы (с и по).'
            if not item.get('responsibilities'):
                return f'Место {i}: опишите ключевые обязанности.'
    elif step == 'education':
        if not raw_content:
            return 'Укажите хотя бы одно учебное заведение.'
        for i, item in enumerate(raw_content, 1):
            if not item.get('institution'):
                return f'Запись {i}: укажите учебное заведение.'
            if not item.get('year'):
                return f'Запись {i}: укажите год окончания.'
    elif step == 'skills':
        if not raw_content.get('hard_skills'):
            return 'Укажите хотя бы несколько профессиональных навыков.'
    elif step == 'languages':
        if not raw_content or not any(item.get('language') for item in raw_content):
            return 'Укажите хотя бы один язык.'
    return None


def _parse_step_post(post, step):
    if step == 'contacts':
        return {
            'full_name': post.get('full_name', '').strip(),
            'email': post.get('email', '').strip(),
            'phone': post.get('phone', '').strip(),
            'city': post.get('city', '').strip(),
            'linkedin': post.get('linkedin', '').strip(),
            'github': post.get('github', '').strip(),
        }
    if step == 'summary':
        return {'text': post.get('text', '').strip()}

    if step == 'skills':
        return {
            'hard_skills': post.get('hard_skills', '').strip(),
            'soft_skills': post.get('soft_skills', '').strip(),
        }

    if step == 'experience':
        return _parse_repeating(post, ['company', 'position', 'period_start', 'period_end', 'responsibilities', 'achievements'])

    if step == 'education':
        return _parse_repeating(post, ['institution', 'specialty', 'degree', 'year'])

    if step == 'languages':
        return _parse_repeating(post, ['language', 'level'])

    if step == 'certifications':
        return _parse_repeating(post, ['name', 'platform', 'year'])

    return {}


def _parse_repeating(post, fields):
    items = []
    index = 0
    while True:
        key = f'{fields[0]}-{index}'
        if key not in post:
            break
        item = {f: post.get(f'{f}-{index}', '').strip() for f in fields}
        if any(item.values()):
            items.append(item)
        index += 1
    return items


@login_required
def resume_generate(request, resume_id):
    if not _has_subscription(request.user):
        return redirect('users:subscription')

    resume = get_object_or_404(Resume, id=resume_id, user=request.user)

    if resume.status != Resume.STATUS_DRAFT:
        return redirect('resumes:detail', resume_id=resume.id)

    if request.method != 'POST':
        return redirect('resumes:step', resume_id=resume.id, step='certifications')

    _run_ai_polish(resume)
    return redirect('resumes:detail', resume_id=resume.id)


@login_required
def resume_retry_ai(request, resume_id):
    if not _has_subscription(request.user):
        return redirect('users:subscription')

    resume = get_object_or_404(Resume, id=resume_id, user=request.user)

    if request.method != 'POST':
        return redirect('resumes:detail', resume_id=resume.id)

    _run_ai_polish(resume)
    return redirect('resumes:detail', resume_id=resume.id)


def _run_ai_polish(resume):
    try:
        data = polish_resume(resume)
        for section_type, content in data.items():
            section = resume.get_section(section_type)
            if section:
                section.ai_content = content
                section.user_content = None
                section.save(update_fields=['ai_content', 'user_content'])
        resume.status = Resume.STATUS_COMPLETED
        resume.save(update_fields=['status', 'updated_at'])
        logger.info("Resume AI polish done: id=%d", resume.id)
    except Exception as e:
        logger.error("Resume AI polish failed: id=%d: %s", resume.id, e)
        resume.status = Resume.STATUS_COMPLETED_RAW
        resume.save(update_fields=['status', 'updated_at'])


@login_required
def resume_edit_section(request, resume_id, step):
    if not _has_subscription(request.user):
        return redirect('users:subscription')

    if step not in RESUME_STEPS:
        return redirect('resumes:list')

    resume = get_object_or_404(Resume, id=resume_id, user=request.user)

    if resume.status == Resume.STATUS_DRAFT:
        return redirect('resumes:step', resume_id=resume.id, step=step)

    existing_section = resume.get_section(step)
    existing_content = existing_section.display_content if existing_section else None

    if request.method == 'POST':
        raw_content = _parse_step_post(request.POST, step)
        error = _validate_step(step, raw_content)
        if error:
            return render(request, 'resumes/step.html', {
                'resume': resume,
                'step': step,
                'step_title': STEP_TITLES[step],
                'step_index': RESUME_STEPS.index(step),
                'step_total': len(RESUME_STEPS),
                'is_last': False,
                'is_repeating': step in _REPEATING_STEPS,
                'existing': raw_content,
                'error': error,
                'is_edit_mode': True,
            })

        if existing_section:
            existing_section.user_content = raw_content
            existing_section.save(update_fields=['user_content'])
        else:
            ResumeSection.objects.create(
                resume=resume,
                section_type=step,
                order=SECTION_ORDER[step],
                raw_content=raw_content,
                user_content=raw_content,
            )

        logger.info("Resume section edited: id=%d step=%s user=%s", resume.id, step, request.user.username)
        messages.success(request, 'Секция обновлена.')
        return redirect('resumes:detail', resume_id=resume.id)

    return render(request, 'resumes/step.html', {
        'resume': resume,
        'step': step,
        'step_title': STEP_TITLES[step],
        'step_index': RESUME_STEPS.index(step),
        'step_total': len(RESUME_STEPS),
        'is_last': False,
        'is_repeating': step in _REPEATING_STEPS,
        'existing': existing_content,
        'is_edit_mode': True,
    })


_RU_MONTH_PATTERNS = [
    (r'январ', 1), (r'феврал', 2), (r'март', 3), (r'апрел', 4),
    (r'ма[йя]', 5), (r'июн', 6), (r'июл', 7), (r'август', 8),
    (r'сентябр', 9), (r'октябр', 10), (r'ноябр', 11), (r'декабр', 12),
]


def _parse_period_date(text):
    if not text:
        return None
    t = text.lower()
    if any(kw in t for kw in ('настоящ', 'н.в', 'present', 'сейчас', 'сих пор')):
        return date.today()
    year_m = re.search(r'\b(20\d{2}|19\d{2})\b', t)
    if not year_m:
        return None
    year = int(year_m.group(1))
    month = 1
    for pattern, num in _RU_MONTH_PATTERNS:
        if re.search(pattern, t):
            month = num
            break
    return date(year, month, 1)


def _experience_label(items):
    total = 0
    for item in items:
        start = _parse_period_date(item.get('period_start', ''))
        end = _parse_period_date(item.get('period_end', ''))
        if start and end and end >= start:
            total += (end.year - start.year) * 12 + (end.month - start.month)
    total = max(0, total)
    years = total // 12
    if years == 0:
        return '0 лет' if total == 0 else 'менее 1 года'
    if 11 <= years % 100 <= 19:
        suffix = 'лет'
    elif years % 10 == 1:
        suffix = 'год'
    elif 2 <= years % 10 <= 4:
        suffix = 'года'
    else:
        suffix = 'лет'
    return f'{years} {suffix}'


@login_required
def resume_detail(request, resume_id):
    if not _has_subscription(request.user):
        return redirect('users:subscription')

    resume = get_object_or_404(Resume, id=resume_id, user=request.user)

    if resume.status == Resume.STATUS_DRAFT:
        return redirect('resumes:step', resume_id=resume.id, step='contacts')

    sections = {s.section_type: s for s in resume.sections.all()}

    exp_section = sections.get('experience')
    exp_items = exp_section.display_content if exp_section else []
    if not isinstance(exp_items, list):
        exp_items = []

    return render(request, 'resumes/detail.html', {
        'resume': resume,
        'sections': sections,
        'ai_failed': resume.status == Resume.STATUS_COMPLETED_RAW,
        'experience_label': _experience_label(exp_items),
    })