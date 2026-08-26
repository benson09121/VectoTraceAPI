from django.http import JsonResponse
from django.urls import resolve

class MaintenanceModeMiddleware:
    """
    Intercepts incoming API requests and returns a 503 response if 
    maintenance mode is enabled and the user is not a superuser.
    Allows /admin/, /health/, and /api/v1/config/ routes to bypass.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # We wrap this in a try-except to prevent the entire site from crashing
        # if the database tables haven't been created yet.
        try:
            from .models import SystemSettings
            settings = SystemSettings.get_settings()
            if settings.is_maintenance_mode:
                path = request.path_info
                
                # Check if it's an exempt path
                # Admin and Health endpoints must always be available
                # We also need /api/v1/config/ to be available so the frontend knows when maintenance is over
                is_exempt = (
                    path.startswith('/admin/') or 
                    path.startswith('/api/v1/health/') or
                    path.startswith('/api/v1/config/')
                )

                if not is_exempt:
                    # Let superusers bypass maintenance mode
                    if not (request.user.is_authenticated and request.user.is_superuser):
                        return JsonResponse({
                            "error": "Maintenance Mode",
                            "message": "The system is currently undergoing scheduled maintenance.",
                            "code": "MAINTENANCE_ACTIVE"
                        }, status=503)
        except Exception:
            pass # Tables might not exist during migrations
            
        return self.get_response(request)
