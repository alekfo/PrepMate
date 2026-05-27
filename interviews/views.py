import logging
from collections import Counter

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q

from .models import InterviewSession, Question, UserAnswer, Feedback, VacancyProfile, SessionAdvice, VacancyAdvice
from .services import generate_questions, evaluate_answer, generate_session_advice, generate_vacancy_advice

logger = logging.getLogger(__name__)


def index(request):
    limit_reached = False
    past_vacancies = []
    if request.user.is_authenticated:
        used_today = InterviewSession.objects.filter(
            user=request.user,
            created_at__date=timezone.localdate(),
        ).count()
        limit_reached = used_today >= request.user.interviews_limit_per_day

        seen = set()
        for s in InterviewSession.objects.filter(user=request.user).order_by('-created_at'):
            if s.vacancy_text not in seen:
                seen.add(s.vacancy_text)
                past_vacancies.append(s)
            if len(past_vacancies) >= 5:
                break

    return render(request, 'interviews/index.html', {
        'limit_reached': limit_reached,
        'past_vacancies': past_vacancies,
    })


@login_required
def start(request):
    if request.method != 'POST':
        return redirect('interviews:index')

    if not request.user.email_confirmed:
        messages.error(request, 'Подтвердите email перед началом интервью.')
        return redirect('interviews:index')

    used_today = InterviewSession.objects.filter(
        user=request.user,
        created_at__date=timezone.localdate(),
    ).count()
    if used_today >= request.user.interviews_limit_per_day:
        logger.warning("Daily limit reached for user=%s (%d/%d)", request.user.username, used_today, request.user.interviews_limit_per_day)
        messages.error(request, 'Дневной лимит интервью исчерпан. Возвращайтесь завтра.')
        return redirect('interviews:index')

    vacancy_text = request.POST.get('vacancy_text', '').strip()
    if not vacancy_text:
        messages.error(request, 'Вставьте текст вакансии.')
        return redirect('interviews:index')

    raw_level = request.POST.get('level', '')
    has_subscription = request.user.is_subscribed or request.user.is_premium
    level = raw_level if (has_subscription and raw_level in ('junior', 'middle', 'pro')) else 'common'

    try:
        data = generate_questions(vacancy_text, level)
    except Exception as e:
        logger.error("generate_questions failed for user=%s: %s", request.user.username, e)
        messages.error(request, 'Не удалось сгенерировать вопросы. Попробуйте ещё раз.')
        return redirect('interviews:index')

    job_title = data.get('job_title', '')
    company_name = data.get('company_name', '')

    vacancy_profile, created = VacancyProfile.objects.get_or_create(
        user=request.user,
        vacancy_text=vacancy_text,
        defaults={'job_title': job_title, 'company_name': company_name},
    )
    if not created and (job_title or company_name):
        vacancy_profile.job_title = job_title
        vacancy_profile.company_name = company_name
        vacancy_profile.save(update_fields=['job_title', 'company_name'])

    session = InterviewSession.objects.create(
        user=request.user,
        vacancy_profile=vacancy_profile,
        vacancy_text=vacancy_text,
        job_title=job_title,
        company_name=company_name,
        status='in_progress',
        level=level,
    )
    request.user.__class__.objects.filter(pk=request.user.pk).update(
        interviews_used=request.user.interviews_used + 1
    )

    for order, q in enumerate(data['questions']):
        Question.objects.create(
            session=session,
            text=q['text'],
            question_type=q['type'],
            order=order,
        )

    logger.info("Session %d started: user=%s job=%r company=%r", session.id, request.user.username, session.job_title, session.company_name)
    return redirect('interviews:question', session_id=session.id, order=0)


@login_required
def question(request, session_id, order):
    session = get_object_or_404(InterviewSession, id=session_id, user=request.user)
    questions = list(session.questions.all())
    total = len(questions)

    if order >= total:
        return redirect('interviews:report', session_id=session.id)

    current_question = questions[order]

    if hasattr(current_question, 'answer'):
        next_order = order + 1
        if next_order < total:
            return redirect('interviews:question', session_id=session.id, order=next_order)
        return redirect('interviews:report', session_id=session.id)

    if request.method == 'POST':
        answer_text = request.POST.get('answer_text', '').strip()
        if not answer_text:
            return render(request, 'interviews/question.html', {
                'session': session,
                'question': current_question,
                'order': order,
                'total': total,
                'error': 'Введите ответ перед отправкой.',
            })

        user_answer = UserAnswer.objects.create(
            question=current_question,
            text=answer_text,
        )
        logger.info("Answer saved: session=%d question=%d user=%s", session_id, order, request.user.username)

        try:
            feedback_data = evaluate_answer(
                question_text=current_question.text,
                answer_text=answer_text,
                vacancy_context=session.vacancy_text,
            )
            Feedback.objects.create(
                answer=user_answer,
                score=feedback_data['score'],
                strengths=feedback_data['strengths'],
                improvements=feedback_data['improvements'],
                ideal_answer_hint=feedback_data['ideal_answer_hint'],
                weakness_tags=feedback_data.get('weakness_tags', []),
                strength_tags=feedback_data.get('strength_tags', []),
            )
        except Exception as e:
            logger.error("evaluate_answer failed: session=%d question=%d user=%s: %s", session_id, order, request.user.username, e)

        next_order = order + 1
        if next_order < total:
            return redirect('interviews:question', session_id=session.id, order=next_order)

        answered = UserAnswer.objects.filter(question__session=session)
        scores = list(Feedback.objects.filter(answer__in=answered).values_list('score', flat=True))
        session.overall_score = sum(scores) / len(scores) if scores else None
        session.status = 'completed'
        session.completed_at = timezone.now()
        session.save()

        logger.info("Session %d completed: user=%s score=%s", session.id, request.user.username, session.overall_score)
        return redirect('interviews:report', session_id=session.id)

    return render(request, 'interviews/question.html', {
        'session': session,
        'question': current_question,
        'order': order,
        'total': total,
    })


@login_required
def resume(request, session_id):
    session = get_object_or_404(InterviewSession, id=session_id, user=request.user)
    if session.status == 'completed':
        return redirect('interviews:report', session_id=session.id)
    first_unanswered = session.questions.filter(answer__isnull=True).order_by('order').first()
    if first_unanswered:
        return redirect('interviews:question', session_id=session.id, order=first_unanswered.order)
    return redirect('interviews:report', session_id=session.id)


@login_required
def history(request):
    sessions = InterviewSession.objects.filter(user=request.user).annotate(
        total=Count('questions'),
        answered=Count('questions', filter=Q(questions__answer__isnull=False)),
    )
    return render(request, 'interviews/history.html', {'sessions': sessions})


@login_required
def report(request, session_id):
    session = get_object_or_404(InterviewSession, id=session_id, user=request.user)
    questions = session.questions.prefetch_related('answer__feedback').all()
    return render(request, 'interviews/report.html', {
        'session': session,
        'questions': questions,
    })


_TAG_LABELS = {
    'depth': 'Глубина',
    'examples': 'Примеры',
    'structure': 'Структура',
    'communication': 'Коммуникация',
    'confidence': 'Уверенность',
    'relevance': 'Релевантность',
    'experience': 'Опыт',
    'proactivity': 'Проактивность',
}


@login_required
def statistics_overview(request):
    has_subscription = request.user.is_subscribed or request.user.is_premium
    if not has_subscription:
        return redirect('users:subscription')

    vacancies = []

    if True:
        for vp in VacancyProfile.objects.filter(user=request.user).order_by('-created_at'):
            completed = list(
                vp.sessions.filter(status='completed')
                .order_by('completed_at')
                .prefetch_related('questions__answer__feedback')
            )
            if not completed:
                continue

            scores = [s.overall_score for s in completed if s.overall_score is not None]
            avg_score = round(sum(scores) / len(scores), 1) if scores else None
            best_score = round(max(scores), 1) if scores else None

            all_tags = []
            for s in completed:
                for q in s.questions.all():
                    fb = getattr(getattr(q, 'answer', None), 'feedback', None)
                    if fb:
                        all_tags.extend(fb.weakness_tags)
            top_tags = [
                {'tag': t, 'label': _TAG_LABELS.get(t, t)}
                for t, _ in Counter(all_tags).most_common(2)
            ]

            vacancies.append({
                'profile': vp,
                'session_count': len(completed),
                'avg_score': avg_score,
                'best_score': best_score,
                'trend': _compute_trend(scores),
                'top_weakness_tags': top_tags,
                'last_completed_at': completed[-1].completed_at,
            })

    return render(request, 'interviews/statistics.html', {'vacancies': vacancies})


@login_required
def statistics_vacancy(request, vacancy_id):
    has_subscription = request.user.is_subscribed or request.user.is_premium
    if not has_subscription:
        return redirect('users:subscription')

    vacancy_profile = get_object_or_404(VacancyProfile, id=vacancy_id, user=request.user)
    completed_sessions = list(
        vacancy_profile.sessions
        .filter(status='completed')
        .order_by('completed_at')
        .prefetch_related('questions__answer__feedback')
    )

    vacancy_advice = None

    if completed_sessions:
        existing_advice = set(
            SessionAdvice.objects.filter(session__in=completed_sessions)
            .values_list('session_id', flat=True)
        )
        for session in completed_sessions:
            if session.id not in existing_advice:
                try:
                    data = generate_session_advice(session)
                    SessionAdvice.objects.create(
                        session=session,
                        summary=data.get('summary', ''),
                        advice=data.get('advice', []),
                        focus_topics=data.get('focus_topics', []),
                    )
                except Exception as e:
                    logger.error("generate_session_advice failed: session=%d: %s", session.id, e)

        current_count = len(completed_sessions)
        try:
            vacancy_advice = vacancy_profile.advice
        except VacancyAdvice.DoesNotExist:
            vacancy_advice = None

        if vacancy_advice is None or vacancy_advice.session_count_at_generation < current_count:
            try:
                data = generate_vacancy_advice(vacancy_profile)
                fields = {
                    'overall_progress': data.get('overall_progress', ''),
                    'chronic_issues': data.get('chronic_issues', []),
                    'improvements': data.get('improvements', []),
                    'next_steps': data.get('next_steps', []),
                    'focus_topics': data.get('focus_topics', []),
                    'verdict': data.get('verdict', ''),
                    'session_count_at_generation': current_count,
                }
                if vacancy_advice is None:
                    vacancy_advice = VacancyAdvice.objects.create(
                        vacancy_profile=vacancy_profile, **fields
                    )
                else:
                    for k, v in fields.items():
                        setattr(vacancy_advice, k, v)
                    vacancy_advice.save()
            except Exception as e:
                logger.error("generate_vacancy_advice failed: vacancy_profile=%d: %s", vacancy_profile.id, e)

    sessions_display = [
        {'session': s, 'number': len(completed_sessions) - i}
        for i, s in enumerate(reversed(completed_sessions))
    ]

    return render(request, 'interviews/statistics_vacancy.html', {
        'vacancy': vacancy_profile,
        'sessions': sessions_display,
        'session_count': len(completed_sessions),
        'chart_points': _build_chart_points(completed_sessions),
        'chart_labels': _build_chart_labels(completed_sessions),
        'tag_stats': _build_tag_stats(completed_sessions),
        'vacancy_advice': vacancy_advice,
    })


def _compute_trend(scores: list) -> str:
    if len(scores) < 4:
        return 'neutral'
    recent = sum(scores[-3:]) / 3
    prev_slice = scores[:-3]
    prev_avg = sum(prev_slice[-3:]) / len(prev_slice[-3:])
    diff = recent - prev_avg
    if diff > 0.5:
        return 'up'
    if diff < -0.5:
        return 'down'
    return 'neutral'


def _build_chart_points(sessions: list) -> str:
    if not sessions:
        return ''
    pad_left, plot_w = 52, 536   # viewBox 600, right pad 12
    pad_top, plot_h = 8, 124     # viewBox 172, bottom pad 40
    n = len(sessions)
    pts = []
    for i, s in enumerate(sessions):
        score = s.overall_score or 0
        x = round(pad_left + (i * plot_w / (n - 1)) if n > 1 else pad_left + plot_w / 2)
        y = round(pad_top + (10 - score) / 9 * plot_h)
        pts.append(f'{x},{y}')
    return ' '.join(pts)


def _build_chart_labels(sessions: list) -> list:
    if not sessions:
        return []
    pad_left, plot_w = 52, 536
    pad_top, plot_h = 8, 124
    n = len(sessions)
    labels = []
    for i, s in enumerate(sessions):
        score = s.overall_score or 0
        x = round(pad_left + (i * plot_w / (n - 1)) if n > 1 else pad_left + plot_w / 2, 1)
        y = round(pad_top + (10 - score) / 9 * plot_h, 1)
        labels.append({
            'x': round(x),
            'y': round(y),
            'score': score,
            'date': s.completed_at.strftime('%d.%m') if s.completed_at else '',
        })
    return labels


def _build_tag_stats(sessions: list) -> list:
    if not sessions:
        return []
    total = len(sessions)
    session_tag_sets = []
    for s in sessions:
        tags = set()
        for q in s.questions.all():
            fb = getattr(getattr(q, 'answer', None), 'feedback', None)
            if fb:
                tags.update(fb.weakness_tags)
        session_tag_sets.append(tags)

    all_tags = set().union(*session_tag_sets)
    tag_counts = {t: sum(1 for ts in session_tag_sets if t in ts) for t in all_tags}
    last_3 = set().union(*session_tag_sets[-3:]) if session_tag_sets else set()

    result = []
    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
        if count / total >= 0.5:
            status = 'chronic'
        elif total > 3 and tag not in last_3:
            status = 'fixed'
        else:
            status = 'active'
        result.append({
            'tag': tag,
            'label': _TAG_LABELS.get(tag, tag),
            'count': count,
            'total': total,
            'status': status,
        })
    return result