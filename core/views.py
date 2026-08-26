from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAdminUser
from .models import SystemSettings

class SystemSettingsView(APIView):
    """
    Public endpoint to fetch the global system configuration.
    This informs the frontend if the system is in showcase or maintenance mode.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            settings = SystemSettings.get_settings()
            return Response({
                "is_showcase_mode": settings.is_showcase_mode,
                "is_maintenance_mode": settings.is_maintenance_mode,
                "allow_registrations": settings.allow_registrations,
            })
        except Exception:
            # Fallback if DB isn't ready
            return Response({
                "is_showcase_mode": False,
                "is_maintenance_mode": False,
                "allow_registrations": True,
            })


