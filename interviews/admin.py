from django.contrib import admin
from .models import InterviewSession, Question, UserAnswer, Feedback


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
