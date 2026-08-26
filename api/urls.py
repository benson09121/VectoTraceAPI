from django.urls import path, include
from .views import liveness, readiness, engine_health
from .views_probes import poll_assignments, submit_result
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

# Sub-routes without namespace (they carry their own app_name)
v1_patterns = [
    # Health probes (no auth required)
    path('health/live/', liveness, name='liveness'),
    path('health/ready/', readiness, name='readiness'),
    path('health/system/', engine_health, name='engine_health'),
    
    # Probe endpoints
    path('probes/assignments/poll/', poll_assignments, name='probe-poll-assignments'),
    path('probes/results/', submit_result, name='probe-submit-result'),

    path('', include('organizations.urls')),
    path('', include('users.urls')),
    path('', include('surveillance.urls')),
    path('', include('core.urls')),
]

urlpatterns = [
    # OpenAPI Schema
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    path('v1/', include((v1_patterns, 'v1'))),
]
