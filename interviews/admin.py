from django.contrib import admin
from .models import InterviewSession, Question, UserAnswer, Feedback, VacancyProfile, SessionAdvice, VacancyAdvice


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0
    readonly_fields = ('order',)


@admin.register(InterviewSession)
class InterviewSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'job_title', 'company_name', 'status', 'overall_score', 'created_at')
    list_filter = ('status',)
    search_fields = ('user__username', 'job_title', 'company_name')
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('session', 'order', 'question_type', 'text')
    list_filter = ('question_type',)


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ('answer', 'score')


@admin.register(VacancyProfile)
class VacancyProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'job_title', 'company_name', 'created_at')
    search_fields = ('user__username', 'job_title', 'company_name')


@admin.register(SessionAdvice)
class SessionAdviceAdmin(admin.ModelAdmin):
    list_display = ('session', 'generated_at')
    readonly_fields = ('generated_at',)


@admin.register(VacancyAdvice)
class VacancyAdviceAdmin(admin.ModelAdmin):
    list_display = ('vacancy_profile', 'session_count_at_generation', 'generated_at')
    readonly_fields = ('generated_at',)
