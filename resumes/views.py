import logging

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
        if not raw_content:
            return 'Добавьте хотя бы одно место работы.'
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
                section.save(update_fields=['ai_content'])
        resume.status = Resume.STATUS_COMPLETED
        resume.save(update_fields=['status', 'updated_at'])
        logger.info("Resume AI polish done: id=%d", resume.id)
    except Exception as e:
        logger.error("Resume AI polish failed: id=%d: %s", resume.id, e)
        resume.status = Resume.STATUS_COMPLETED_RAW
        resume.save(update_fields=['status', 'updated_at'])


@login_required
def resume_detail(request, resume_id):
    if not _has_subscription(request.user):
        return redirect('users:subscription')

    resume = get_object_or_404(Resume, id=resume_id, user=request.user)

    if resume.status == Resume.STATUS_DRAFT:
        return redirect('resumes:step', resume_id=resume.id, step='contacts')

    sections = {s.section_type: s for s in resume.sections.all()}

    return render(request, 'resumes/detail.html', {
        'resume': resume,
        'sections': sections,
        'ai_failed': resume.status == Resume.STATUS_COMPLETED_RAW,
    })