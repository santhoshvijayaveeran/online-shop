from django.urls import path, re_path
from . import views

urlpatterns = [
    re_path(r'^manifest\.json$', views.manifest, name='manifest'),
    re_path(r'^serviceworker\.js$', views.serviceworker, name='serviceworker'),
    path('offline/', views.offline, name='offline'),
]