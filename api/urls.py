from rest_framework.routers import DefaultRouter
from django.urls import path, include



urlpatterns = [
    # path('v1/', include('users.urls', namespace='v1'))
    path('v1/', include('organizations.urls', namespace='v1')),
    path('v1/auth/', include('users.urls'))
]