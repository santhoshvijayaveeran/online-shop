from django.urls import path
from . import views

urlpatterns = [
    path('chat/', views.chat, name='sanza_chat'),
    path('feedback/', views.feedback, name='sanza_feedback'),
    path('history/<str:session_id>/', views.history, name='sanza_history'),
    path('analytics/', views.analytics, name='sanza_analytics'),
]
