from django.db import models
from django.conf import settings


class VacancyProfile(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='vacancy_profiles')
    vacancy_text = models.TextField()
    job_title = models.CharField(max_length=255, blank=True)
    company_name = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Профиль вакансии'
        verbose_name_plural = 'Профили вакансий'

    def __str__(self):
        return f'{self.user.username} — {self.job_title or "Без названия"}'


class InterviewSession(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('in_progress', 'В процессе'),
        ('completed', 'Завершено'),
    ]

    LEVEL_CHOICES = [
        ('common', 'Без уровня'),
        ('junior', 'Junior'),
        ('middle', 'Middle'),
        ('pro', 'Pro'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sessions')
    vacancy_profile = models.ForeignKey(VacancyProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='sessions')
    vacancy_text = models.TextField()
    job_title = models.CharField(max_length=255, blank=True)
    company_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='common')
    overall_score = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Сессия интервью'
        verbose_name_plural = 'Сессии интервью'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} — {self.job_title or "Без названия"} ({self.created_at:%d.%m.%Y})'


class Question(models.Model):
    QUESTION_TYPE_CHOICES = [
        ('technical', 'Техническое'),
        ('behavioral', 'Поведенческое'),
        ('situational', 'Ситуационное'),
    ]

    session = models.ForeignKey(InterviewSession, on_delete=models.CASCADE, related_name='questions')
    text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPE_CHOICES, default='technical')
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f'Q{self.order}: {self.text[:60]}'


class UserAnswer(models.Model):
    question = models.OneToOneField(Question, on_delete=models.CASCADE, related_name='answer')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Ответ на: {self.question}'


class Feedback(models.Model):
    answer = models.OneToOneField(UserAnswer, on_delete=models.CASCADE, related_name='feedback')
    score = models.PositiveSmallIntegerField()
    strengths = models.JSONField(default=list)
    improvements = models.JSONField(default=list)
    ideal_answer_hint = models.TextField()
    weakness_tags = models.JSONField(default=list)
    strength_tags = models.JSONField(default=list)

    def __str__(self):
        return f'Feedback [{self.score}/10] для {self.answer}'


class SessionAdvice(models.Model):
    session = models.OneToOneField(InterviewSession, on_delete=models.CASCADE, related_name='advice')
    summary = models.TextField()
    advice = models.JSONField(default=list)
    focus_topics = models.JSONField(default=list)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Совет по сессии'
        verbose_name_plural = 'Советы по сессиям'

    def __str__(self):
        return f'SessionAdvice для {self.session}'


class VacancyAdvice(models.Model):
    vacancy_profile = models.OneToOneField(VacancyProfile, on_delete=models.CASCADE, related_name='advice')
    overall_progress = models.TextField()
    chronic_issues = models.JSONField(default=list)
    improvements = models.JSONField(default=list)
    next_steps = models.JSONField(default=list)
    focus_topics = models.JSONField(default=list)
    verdict = models.TextField(blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    session_count_at_generation = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Совет по вакансии'
        verbose_name_plural = 'Советы по вакансиям'

    def __str__(self):
        return f'VacancyAdvice для {self.vacancy_profile}'
