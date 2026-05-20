from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q

from .models import InterviewSession, Question, UserAnswer, Feedback
from .services import generate_questions, evaluate_answer


def index(request):
    limit_reached = False
    if request.user.is_authenticated:
        used_today = InterviewSession.objects.filter(
            user=request.user,
            created_at__date=timezone.localdate(),
        ).count()
        limit_reached = used_today >= request.user.interviews_limit_per_day
    return render(request, 'interviews/index.html', {'limit_reached': limit_reached})


@login_required
def start(request):
    if request.method != 'POST':
        return redirect('interviews:index')

    used_today = InterviewSession.objects.filter(
        user=request.user,
        created_at__date=timezone.localdate(),
    ).count()
    if used_today >= request.user.interviews_limit_per_day:
        messages.error(request, 'Дневной лимит интервью исчерпан. Возвращайтесь завтра.')
        return redirect('interviews:index')

    vacancy_text = request.POST.get('vacancy_text', '').strip()
    if not vacancy_text:
        messages.error(request, 'Вставьте текст вакансии.')
        return redirect('interviews:index')

    try:
        data = generate_questions(vacancy_text)
    except Exception:
        messages.error(request, 'Не удалось сгенерировать вопросы. Попробуйте ещё раз.')
        return redirect('interviews:index')

    session = InterviewSession.objects.create(
        user=request.user,
        vacancy_text=vacancy_text,
        job_title=data.get('job_title', ''),
        company_name=data.get('company_name', ''),
        status='in_progress',
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
            )
        except Exception:
            pass

        next_order = order + 1
        if next_order < total:
            return redirect('interviews:question', session_id=session.id, order=next_order)

        answered = UserAnswer.objects.filter(question__session=session)
        scores = list(Feedback.objects.filter(answer__in=answered).values_list('score', flat=True))
        session.overall_score = sum(scores) / len(scores) if scores else None
        session.status = 'completed'
        session.completed_at = timezone.now()
        session.save()

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
