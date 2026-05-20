from django.db import models
from django.conf import settings


class InterviewSession(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('in_progress', 'В процессе'),
        ('completed', 'Завершено'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sessions')
    vacancy_text = models.TextField()
    job_title = models.CharField(max_length=255, blank=True)
    company_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
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

    def __str__(self):
        return f'Feedback [{self.score}/10] для {self.answer}'
