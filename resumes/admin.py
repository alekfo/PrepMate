from django.contrib import admin
from .models import Resume, ResumeSection


class ResumeSectionInline(admin.TabularInline):
    model = ResumeSection
    extra = 0
    readonly_fields = ['raw_content', 'ai_content', 'user_content']


@admin.register(Resume)
class ResumeAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'profession', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['user__username', 'profession']
    inlines = [ResumeSectionInline]


@admin.register(ResumeSection)
class ResumeSectionAdmin(admin.ModelAdmin):
    list_display = ['id', 'resume', 'section_type', 'order']
    list_filter = ['section_type']
    search_fields = ['resume__user__username', 'resume__profession']
    readonly_fields = ['raw_content', 'ai_content', 'user_content']