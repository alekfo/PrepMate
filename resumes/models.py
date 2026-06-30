from django.db import models
from django.conf import settings


class Resume(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_COMPLETED = 'completed'
    STATUS_COMPLETED_RAW = 'completed_raw'

    STATUS_CHOICES = [
        ('draft', 'Черновик'),
        ('completed', 'Готово'),
        ('completed_raw', 'Готово (без AI)'),
    ]

    SECTION_TYPES = [
        ('contacts', 'Контакты'),
        ('summary', 'О себе'),
        ('experience', 'Опыт работы'),
        ('education', 'Образование'),
        ('skills', 'Навыки'),
        ('languages', 'Языки'),
        ('certifications', 'Курсы и сертификаты'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='resumes')
    profession = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    photo = models.FileField(upload_to='resume_photos/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Резюме'
        verbose_name_plural = 'Резюме'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} — {self.profession}'

    def get_section(self, section_type):
        return self.sections.filter(section_type=section_type).first()


class ResumeSection(models.Model):
    SECTION_CHOICES = Resume.SECTION_TYPES

    resume = models.ForeignKey(Resume, on_delete=models.CASCADE, related_name='sections')
    section_type = models.CharField(max_length=20, choices=SECTION_CHOICES)
    order = models.PositiveSmallIntegerField(default=0)
    raw_content = models.JSONField(default=dict)
    ai_content = models.JSONField(null=True, blank=True)
    user_content = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['order']
        unique_together = [('resume', 'section_type')]

    def __str__(self):
        return f'{self.resume} / {self.get_section_type_display()}'

    @property
    def display_content(self):
        return self.user_content or self.ai_content or self.raw_content