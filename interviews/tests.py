from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from .models import InterviewSession, Question, UserAnswer, Feedback
from .services import _parse_json, generate_questions, evaluate_answer

User = get_user_model()

MOCK_QUESTIONS_RESPONSE = {
    'job_title': 'Python Developer',
    'company_name': 'ACME',
    'questions': [{'text': f'Вопрос {i}', 'type': 'technical'} for i in range(8)],
}

MOCK_FEEDBACK_RESPONSE = {
    'score': 7,
    'strengths': ['Хорошо'],
    'improvements': ['Улучшить'],
    'ideal_answer_hint': 'Подсказка',
}


def make_user(username='testuser', email_confirmed=True, limit=3):
    user = User.objects.create_user(username=username, password='pass', email=f'{username}@test.com')
    user.email_confirmed = email_confirmed
    user.interviews_limit_per_day = limit
    user.save()
    return user


def make_session(user, num_questions=8):
    session = InterviewSession.objects.create(
        user=user,
        vacancy_text='Тест вакансия',
        job_title='Dev',
        status='in_progress',
    )
    for i in range(num_questions):
        Question.objects.create(session=session, text=f'Вопрос {i}', order=i)
    return session


class ParseJsonTests(TestCase):
    def test_plain_json(self):
        result = _parse_json('{"score": 5}')
        self.assertEqual(result, {'score': 5})

    def test_markdown_wrapped(self):
        result = _parse_json('```json\n{"score": 5}\n```')
        self.assertEqual(result, {'score': 5})

    def test_markdown_no_lang(self):
        result = _parse_json('```\n{"score": 5}\n```')
        self.assertEqual(result, {'score': 5})


class ServicesTests(TestCase):
    @patch('interviews.services.requests.post')
    def test_generate_questions(self, mock_post):
        mock_post.return_value = MagicMock(
            json=lambda: {'response': '{"job_title":"Dev","company_name":"Co","questions":[{"text":"Q","type":"technical"}]}'},
            raise_for_status=lambda: None,
        )
        result = generate_questions('vacancy text')
        self.assertEqual(result['job_title'], 'Dev')
        self.assertEqual(len(result['questions']), 1)

    @patch('interviews.services.requests.post')
    def test_evaluate_answer(self, mock_post):
        mock_post.return_value = MagicMock(
            json=lambda: {'response': '{"score":8,"strengths":[],"improvements":[],"ideal_answer_hint":"hint"}'},
            raise_for_status=lambda: None,
        )
        result = evaluate_answer('вопрос', 'ответ', 'вакансия')
        self.assertEqual(result['score'], 8)


class IndexViewTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_anonymous_sees_landing(self):
        response = self.client.get(reverse('interviews:index'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'vacancy_text')

    def test_authenticated_sees_form(self):
        user = make_user()
        self.client.force_login(user)
        response = self.client.get(reverse('interviews:index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'vacancy_text')


class StartViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse('interviews:start')

    def test_requires_login(self):
        response = self.client.post(self.url, {'vacancy_text': 'текст'})
        self.assertRedirects(response, f'/users/login/?next={self.url}')

    def test_blocks_unconfirmed_email(self):
        user = make_user(email_confirmed=False)
        self.client.force_login(user)
        response = self.client.post(self.url, {'vacancy_text': 'текст'})
        self.assertRedirects(response, reverse('interviews:index'))
        messages = list(response.wsgi_request._messages)
        self.assertTrue(any('email' in str(m).lower() for m in messages))

    def test_blocks_daily_limit(self):
        user = make_user(limit=1)
        InterviewSession.objects.create(user=user, vacancy_text='x', status='completed')
        self.client.force_login(user)
        response = self.client.post(self.url, {'vacancy_text': 'текст'})
        self.assertRedirects(response, reverse('interviews:index'))

    def test_blocks_empty_vacancy(self):
        user = make_user()
        self.client.force_login(user)
        response = self.client.post(self.url, {'vacancy_text': '   '})
        self.assertRedirects(response, reverse('interviews:index'))

    @patch('interviews.views.generate_questions', return_value=MOCK_QUESTIONS_RESPONSE)
    def test_creates_session_and_redirects(self, _):
        user = make_user()
        self.client.force_login(user)
        response = self.client.post(self.url, {'vacancy_text': 'нормальная вакансия'})
        session = InterviewSession.objects.get(user=user)
        self.assertEqual(session.questions.count(), 8)
        self.assertRedirects(response, reverse('interviews:question', args=[session.id, 0]))

    @patch('interviews.views.generate_questions', side_effect=Exception('API error'))
    def test_handles_api_error(self, _):
        user = make_user()
        self.client.force_login(user)
        response = self.client.post(self.url, {'vacancy_text': 'вакансия'})
        self.assertRedirects(response, reverse('interviews:index'))
        self.assertEqual(InterviewSession.objects.count(), 0)


class QuestionViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.client.force_login(self.user)
        self.session = make_session(self.user)

    def test_get_shows_question(self):
        url = reverse('interviews:question', args=[self.session.id, 0])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Вопрос 0')

    def test_post_empty_answer_shows_error(self):
        url = reverse('interviews:question', args=[self.session.id, 0])
        response = self.client.post(url, {'answer_text': '  '})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Введите ответ')

    @patch('interviews.views.evaluate_answer', return_value=MOCK_FEEDBACK_RESPONSE)
    def test_post_saves_answer_and_redirects(self, _):
        url = reverse('interviews:question', args=[self.session.id, 0])
        response = self.client.post(url, {'answer_text': 'мой ответ'})
        self.assertTrue(UserAnswer.objects.filter(question__session=self.session).exists())
        self.assertRedirects(response, reverse('interviews:question', args=[self.session.id, 1]))

    @patch('interviews.views.evaluate_answer', return_value=MOCK_FEEDBACK_RESPONSE)
    def test_last_answer_completes_session(self, _):
        # ответить на все вопросы кроме последнего
        questions = list(self.session.questions.all())
        for q in questions[:-1]:
            answer = UserAnswer.objects.create(question=q, text='ответ')
            Feedback.objects.create(
                answer=answer, score=7, strengths=[], improvements=[], ideal_answer_hint='hint',
            )
        last_order = questions[-1].order
        url = reverse('interviews:question', args=[self.session.id, last_order])
        response = self.client.post(url, {'answer_text': 'финальный ответ'})
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'completed')
        self.assertRedirects(response, reverse('interviews:report', args=[self.session.id]))

    def test_skips_answered_question(self):
        q0 = self.session.questions.get(order=0)
        UserAnswer.objects.create(question=q0, text='уже отвечено')
        url = reverse('interviews:question', args=[self.session.id, 0])
        response = self.client.get(url)
        self.assertRedirects(response, reverse('interviews:question', args=[self.session.id, 1]))

    def test_other_user_cannot_access(self):
        other = make_user('other')
        self.client.force_login(other)
        url = reverse('interviews:question', args=[self.session.id, 0])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class ResumeViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.client.force_login(self.user)

    def test_redirects_to_first_unanswered(self):
        session = make_session(self.user)
        q0 = session.questions.get(order=0)
        UserAnswer.objects.create(question=q0, text='ответ')
        url = reverse('interviews:resume', args=[session.id])
        response = self.client.get(url)
        self.assertRedirects(response, reverse('interviews:question', args=[session.id, 1]))

    def test_completed_session_goes_to_report(self):
        session = make_session(self.user)
        session.status = 'completed'
        session.save()
        url = reverse('interviews:resume', args=[session.id])
        response = self.client.get(url)
        self.assertRedirects(response, reverse('interviews:report', args=[session.id]))


class ReportViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.client.force_login(self.user)

    def test_report_accessible(self):
        session = make_session(self.user)
        session.status = 'completed'
        session.save()
        url = reverse('interviews:report', args=[session.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_other_user_cannot_see_report(self):
        session = make_session(self.user)
        other = make_user('other2')
        self.client.force_login(other)
        url = reverse('interviews:report', args=[session.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class HistoryViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.client.force_login(self.user)

    def test_shows_user_sessions(self):
        make_session(self.user)
        response = self.client.get(reverse('interviews:history'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['sessions']), 1)

    def test_does_not_show_other_users_sessions(self):
        other = make_user('other3')
        make_session(other)
        response = self.client.get(reverse('interviews:history'))
        self.assertEqual(len(response.context['sessions']), 0)