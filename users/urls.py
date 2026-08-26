from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import RegisterView, ThrottledTokenObtainPairView, getProfile, logout_view


urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='register_v1'),
    path('auth/login/', ThrottledTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/logout/', logout_view, name='logout_v1'),
    path('auth/me/', getProfile, name='profile_v1'),
]
