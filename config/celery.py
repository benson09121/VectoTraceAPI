import os
from celery import Celery

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('vectotrace')

# Use Django settings with the CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all INSTALLED_APPS
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')


@app.task(ignore_result=True)
def beat_heartbeat():
    from django.core.cache import cache
    from django.utils import timezone
    cache.set('celery_beat_heartbeat', timezone.now().isoformat(), timeout=120)

app.conf.beat_schedule = {
    'heartbeat-every-minute': {
        'task': 'config.celery.beat_heartbeat',
        'schedule': 60.0,
    },
    'evaluate-escalations-every-minute': {
        'task': 'surveillance.tasks.evaluate_escalations',
        'schedule': 60.0,
    },
    'calculate-slos-hourly': {
        'task': 'surveillance.tasks.calculate_slo_compliance',
        'schedule': 3600.0,
    },
    'schedule-monitors-frequently': {
        'task': 'surveillance.tasks.schedule_all_monitors',
        'schedule': 5.0,  # Run every 5 seconds to accurately dispatch checks
    },
    'check-expiring-certificates-daily': {
        'task': 'surveillance.tasks.check_expiring_certificates',
        'schedule': 86400.0,  # Run once a day
    },
}
