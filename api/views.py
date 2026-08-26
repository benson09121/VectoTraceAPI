from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from django.core.cache import cache
from django.db import connection
from config.celery import app as celery_app
import redis
from django.conf import settings


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def liveness(request):
    """
    Liveness probe — always returns 200 if the process is running.
    No external dependencies checked.
    """
    return Response({'status': 'ok'}, status=status.HTTP_200_OK)


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def readiness(request):
    """
    Readiness probe — checks the dependencies we cannot serve traffic without:
    Postgres and Redis. Returns 200 only if both answer.
    """
    checks = {}

    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        checks['database'] = 'ok'
    except Exception as exc:
        checks['database'] = f'error: {exc}'

    try:
        cache.set('healthcheck', '1', 10)
        checks['redis'] = 'ok' if cache.get('healthcheck') == '1' else 'error: readback failed'
    except Exception as exc:
        checks['redis'] = f'error: {exc}'

    ready = all(v == 'ok' for v in checks.values())
    return Response(
        {'status': 'ok' if ready else 'error', 'checks': checks},
        status=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@api_view(['GET'])
@permission_classes([IsAdminUser])
def engine_health(request):
    """
    Detailed engine health metrics for administrators.
    Exposes queue depth, active workers, and basic scheduler info.
    """
    metrics = {
        'queue_depth': -1,
        'active_workers': 0,
        'scheduler': 'unknown'
    }
    
    try:
        # Check queue depth directly via Redis for speed (assuming default 'celery' queue)
        redis_client = redis.from_url(settings.CELERY_BROKER_URL)
        metrics['queue_depth'] = redis_client.llen('celery')
    except Exception as e:
        metrics['queue_depth_error'] = str(e)
        
    try:
        # Ping workers (with a tight timeout so the API doesn't block forever)
        ping_res = celery_app.control.ping(timeout=1.0)
        if ping_res:
            metrics['active_workers'] = len(ping_res)
            metrics['worker_details'] = ping_res
    except Exception as e:
        metrics['active_workers_error'] = str(e)

    # In a full implementation, the Beat scheduler can write a heartbeat to cache every minute.
    metrics['beat_heartbeat'] = cache.get('celery_beat_heartbeat', 'missing')
    
    return Response({'status': 'ok', 'metrics': metrics})
