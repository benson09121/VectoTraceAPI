from django.urls import path, include
from .views import *
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

app_name = 'users'

urlpatterns = [
    path('auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('me/', getProfile, name='profile_v1'),
    path("auth/register/", RegisterView.as_view(), name='register_v1'),
    path('auth/logout/', logout_view, name='logout_v1')
]