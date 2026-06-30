from django.urls import path
from . import views

app_name = 'resumes'

urlpatterns = [
    path('', views.resume_list, name='list'),
    path('new/', views.resume_new, name='new'),
    path('<int:resume_id>/step/<str:step>/', views.resume_step, name='step'),
    path('<int:resume_id>/edit/<str:step>/', views.resume_edit_section, name='edit_section'),
    path('<int:resume_id>/generate/', views.resume_generate, name='generate'),
    path('<int:resume_id>/retry-ai/', views.resume_retry_ai, name='retry_ai'),
    path('<int:resume_id>/photo/upload/', views.resume_upload_photo, name='upload_photo'),
    path('<int:resume_id>/photo/delete/', views.resume_delete_photo, name='delete_photo'),
    path('<int:resume_id>/ai-section/<str:step>/', views.resume_ai_refine_section, name='ai_refine_section'),
    path('<int:resume_id>/ai-section/<str:step>/accept/', views.resume_ai_accept_section, name='ai_accept_section'),
    path('<int:resume_id>/export/pdf/', views.resume_export_pdf, name='export_pdf'),
    path('<int:resume_id>/export/docx/', views.resume_export_docx, name='export_docx'),
    path('<int:resume_id>/', views.resume_detail, name='detail'),
]