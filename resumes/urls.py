from django.urls import path
from . import views

app_name = 'resumes'

urlpatterns = [
    path('', views.resume_list, name='list'),
    path('new/', views.resume_new, name='new'),
    path('<int:resume_id>/step/<str:step>/', views.resume_step, name='step'),
    path('<int:resume_id>/generate/', views.resume_generate, name='generate'),
    path('<int:resume_id>/retry-ai/', views.resume_retry_ai, name='retry_ai'),
    path('<int:resume_id>/', views.resume_detail, name='detail'),
]