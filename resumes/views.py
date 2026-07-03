import json
import logging
import mimetypes
import os
import re
from datetime import date

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import Resume, ResumeSection
from .services import polish_resume, refine_section

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


_AI_REFINE_SECTIONS = {'summary', 'experience', 'education', 'skills', 'certifications'}
_AI_REFINE_CACHE_PREFIX = 'resume_ai_uses'
_AI_REFINE_LIST_SECTIONS = {'experience', 'education', 'certifications'}


def _ai_refine_uses_today(user):
    key = f'{_AI_REFINE_CACHE_PREFIX}_{user.id}_{date.today()}'
    return cache.get(key, 0)


def _ai_refine_increment(user):
    key = f'{_AI_REFINE_CACHE_PREFIX}_{user.id}_{date.today()}'
    used = cache.get(key, 0) + 1
    cache.set(key, used, timeout=86400)
    return used


def _resumes_created_today(user):
    return Resume.objects.filter(user=user, created_at__date=timezone.localdate()).count()


@login_required
def resume_list(request):
    if not _has_subscription(request.user):
        return redirect('users:subscription')

    resumes = Resume.objects.filter(
        user=request.user,
    ).exclude(status=Resume.STATUS_DRAFT)

    drafts = Resume.objects.filter(user=request.user, status=Resume.STATUS_DRAFT)
    limit_reached = _resumes_created_today(request.user) >= request.user.interviews_limit_per_day

    return render(request, 'resumes/list.html', {
        'resumes': resumes,
        'drafts': drafts,
        'limit_reached': limit_reached,
        'limit': request.user.interviews_limit_per_day,
    })


@login_required
def resume_new(request):
    if not _has_subscription(request.user):
        return redirect('users:subscription')

    if request.method != 'POST':
        return redirect('resumes:list')

    if _resumes_created_today(request.user) >= request.user.interviews_limit_per_day:
        messages.error(request, 'Дневной лимит создания резюме исчерпан. Возвращайтесь завтра.')
        return redirect('resumes:list')

    profession = request.POST.get('profession', '').strip()
    if not profession:
        messages.error(request, 'Укажите целевую должность.')
        return redirect('resumes:list')

    resume = Resume.objects.create(user=request.user, profession=profession)
    logger.info("Resume created: id=%d user=%s profession=%r", resume.id, request.user.username, profession)
    return redirect('resumes:step', resume_id=resume.id, step='contacts')


@login_required
def resume_delete(request, resume_id):
    if not _has_subscription(request.user):
        return redirect('users:subscription')
    if request.method != 'POST':
        return redirect('resumes:list')

    resume = get_object_or_404(Resume, id=resume_id, user=request.user)
    if resume.photo:
        resume.photo.delete(save=False)
    profession = resume.profession
    resume.delete()
    logger.info("Resume deleted: id=%d user=%s profession=%r", resume_id, request.user.username, profession)
    return redirect(reverse('resumes:list') + '?deleted=1')


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


_PHOTO_ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
_PHOTO_ALLOWED_CONTENT_TYPES = {'image/jpeg', 'image/jpg', 'image/png', 'image/webp'}
_PHOTO_MAX_SIZE = 5 * 1024 * 1024  # 5 MB


def _photo_url(resume):
    """URL фото с версией по updated_at в query string.

    /resume/<id>/photo/ сам по себе не меняется между заменами фото (после
    delete+upload файл на диске часто получает то же имя) — без версии браузер
    кеширует ответ по URL и после замены фото продолжает показывать старое.
    """
    ts = int(resume.updated_at.timestamp()) if resume.updated_at else 0
    return f"{reverse('resumes:photo', args=[resume.id])}?v={ts}"


@login_required
def resume_upload_photo(request, resume_id):
    if not _has_subscription(request.user):
        return JsonResponse({'error': 'subscription_required'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    resume = get_object_or_404(Resume, id=resume_id, user=request.user)

    photo = request.FILES.get('photo')
    if not photo:
        return JsonResponse({'error': 'no_file'}, status=400)
    if photo.size > _PHOTO_MAX_SIZE:
        return JsonResponse({'error': 'too_large'}, status=400)

    ext = os.path.splitext(photo.name)[1].lower()
    ct = (photo.content_type or '').lower()
    logger.debug("Photo upload: name=%r ext=%r content_type=%r size=%d", photo.name, ext, ct, photo.size)

    if ext not in _PHOTO_ALLOWED_EXTENSIONS or ct not in _PHOTO_ALLOWED_CONTENT_TYPES:
        logger.warning("Photo rejected: name=%r ext=%r content_type=%r user=%s", photo.name, ext, ct, request.user.username)
        return JsonResponse({'error': 'invalid_type'}, status=400)

    if resume.photo:
        resume.photo.delete(save=False)

    resume.photo = photo
    resume.save(update_fields=['photo', 'updated_at'])
    logger.info("Resume photo uploaded: id=%d user=%s content_type=%r", resume.id, request.user.username, ct)
    return JsonResponse({'url': _photo_url(resume)})


@login_required
def resume_photo(request, resume_id):
    """Отдаёт фото резюме только его владельцу.

    /media/ в nginx закрыт (internal) — наружу фото отдаются только через этот
    view, который проверяет владельца и на проде перекладывает раздачу на nginx
    через X-Accel-Redirect (сам файл через Python не гоняем).
    """
    resume = get_object_or_404(Resume, id=resume_id, user=request.user)
    if not resume.photo:
        raise Http404

    content_type = mimetypes.guess_type(resume.photo.name)[0] or 'application/octet-stream'
    # URL версионирован через ?v=<updated_at> (см. _photo_url) — можно кешировать
    # надолго: если фото поменяется, поменяется и версия в URL.
    cache_control = 'private, max-age=31536000, immutable'

    if settings.DEBUG:
        # Локально (runserver) nginx не участвует — X-Accel-Redirect работать не будет.
        response = FileResponse(resume.photo.open('rb'), content_type=content_type)
        response['Cache-Control'] = cache_control
        return response

    response = HttpResponse(content_type=content_type)
    response['Cache-Control'] = cache_control
    response['X-Accel-Redirect'] = f'/protected-media/{resume.photo.name}'
    return response


@login_required
def resume_delete_photo(request, resume_id):
    if not _has_subscription(request.user):
        return JsonResponse({'error': 'subscription_required'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    resume = get_object_or_404(Resume, id=resume_id, user=request.user)
    if resume.photo:
        resume.photo.delete(save=False)
        resume.photo = None
        resume.save(update_fields=['photo', 'updated_at'])
        logger.info("Resume photo deleted: id=%d user=%s", resume.id, request.user.username)
    return JsonResponse({'ok': True})


@login_required
def resume_ai_refine_section(request, resume_id, step):
    if not request.user.is_premium:
        return JsonResponse({'error': 'premium_required'}, status=403)
    if step not in _AI_REFINE_SECTIONS:
        return JsonResponse({'error': 'not_supported'}, status=400)
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    resume = get_object_or_404(Resume, id=resume_id, user=request.user)
    section = get_object_or_404(ResumeSection, resume=resume, section_type=step)

    limit = request.user.interviews_limit_per_day
    used_today = _ai_refine_uses_today(request.user)
    if used_today >= limit:
        return JsonResponse({'error': 'limit_reached', 'limit': limit}, status=429)

    wish = request.POST.get('wish', '').strip()[:500]

    try:
        content = refine_section(section, wish, resume.profession)
    except Exception as e:
        logger.error("AI section refine failed: resume_id=%d step=%s: %s", resume_id, step, e)
        return JsonResponse({'error': 'ai_failed'}, status=500)

    used = _ai_refine_increment(request.user)
    remaining = max(0, limit - used)
    return JsonResponse({'content': content, 'remaining': remaining})


@login_required
def resume_ai_accept_section(request, resume_id, step):
    if not request.user.is_premium:
        return redirect('users:subscription')
    if step not in _AI_REFINE_SECTIONS or request.method != 'POST':
        return redirect('resumes:detail', resume_id=resume_id)

    resume = get_object_or_404(Resume, id=resume_id, user=request.user)
    section = get_object_or_404(ResumeSection, resume=resume, section_type=step)

    try:
        content = json.loads(request.POST.get('content', ''))
    except (ValueError, TypeError):
        messages.error(request, 'Ошибка при сохранении. Попробуйте ещё раз.')
        return redirect('resumes:detail', resume_id=resume_id)

    expected_type = list if step in _AI_REFINE_LIST_SECTIONS else dict
    if not isinstance(content, expected_type):
        messages.error(request, 'Ошибка формата данных.')
        return redirect('resumes:detail', resume_id=resume_id)

    section.ai_content = content
    section.user_content = None
    section.save(update_fields=['ai_content', 'user_content'])

    logger.info("AI section accepted: resume_id=%d step=%s user=%s", resume_id, step, request.user.username)
    messages.success(request, 'Секция обновлена с помощью AI.')
    return redirect('resumes:detail', resume_id=resume_id)


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

    ai_refine_remaining = max(0, request.user.interviews_limit_per_day - _ai_refine_uses_today(request.user))

    return render(request, 'resumes/detail.html', {
        'resume': resume,
        'sections': sections,
        'ai_failed': resume.status == Resume.STATUS_COMPLETED_RAW,
        'experience_label': _experience_label(exp_items),
        'ai_refine_remaining': ai_refine_remaining,
    })


@login_required
def resume_export_pdf(request, resume_id):
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

    from .export import generate_pdf
    try:
        pdf_bytes = generate_pdf(resume, sections, _experience_label(exp_items))
    except Exception as e:
        logger.error("PDF export failed: resume_id=%d: %s", resume.id, e)
        messages.error(request, 'Не удалось сформировать PDF. Попробуйте позже.')
        return redirect('resumes:detail', resume_id=resume.id)

    safe_name = re.sub(r'[^\w\-]', '_', resume.profession)[:40]
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="resume_{safe_name}.pdf"'
    return response


@login_required
def resume_export_docx(request, resume_id):
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

    from .export import generate_docx
    try:
        docx_bytes = generate_docx(resume, sections, _experience_label(exp_items))
    except Exception as e:
        logger.error("DOCX export failed: resume_id=%d: %s", resume.id, e)
        messages.error(request, 'Не удалось сформировать DOCX. Попробуйте позже.')
        return redirect('resumes:detail', resume_id=resume.id)

    safe_name = re.sub(r'[^\w\-]', '_', resume.profession)[:40]
    response = HttpResponse(
        docx_bytes,
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    response['Content-Disposition'] = f'attachment; filename="resume_{safe_name}.docx"'
    return response