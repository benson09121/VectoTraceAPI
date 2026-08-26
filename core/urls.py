from django.urls import path
from .views import SystemSettingsView

urlpatterns = [
    path('config/', SystemSettingsView.as_view(), name='config'),
]
