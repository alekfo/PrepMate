from django.urls import path
from . import views

app_name = 'interviews'

urlpatterns = [
    path('', views.index, name='index'),
    path('start/', views.start, name='start'),
    path('history/', views.history, name='history'),
    path('session/<int:session_id>/resume/', views.resume, name='resume'),
    path('session/<int:session_id>/question/<int:order>/', views.question, name='question'),
    path('session/<int:session_id>/report/', views.report, name='report'),
    path('statistics/', views.statistics_overview, name='statistics'),
    path('statistics/vacancy/<int:vacancy_id>/', views.statistics_vacancy, name='statistics_vacancy'),
    path('statistics/vacancy/<int:vacancy_id>/refresh/', views.vacancy_advice_refresh, name='vacancy_advice_refresh'),
    path('flashcards/', views.flashcards, name='flashcards'),
    path('flashcards/train/', views.flashcards_train, name='flashcards_train'),
]
