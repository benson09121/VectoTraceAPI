import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from surveillance.models import Monitor, Organization, ApiLog
from surveillance.probes import probe_domain
from surveillance.tasks import run_check
from users.models import User
import requests

org = Organization.objects.first()
if not org:
    org = Organization.objects.create(name="Test Org")
    
user = User.objects.first()
if not user:
    user = User.objects.create(email="test@test.com", password="x")

monitor = Monitor.objects.create(
    organization=org,
    name="Test Domain",
    url="google.com",
    type="domain",
    created_by=user
)

# Run the domain probe directly
with requests.Session() as session:
    result = probe_domain(monitor, session)
    print("PROBE RESULT:", result)

# Run the task directly to test ApiLog creation
run_check(monitor.id)

# Fetch the log
log = ApiLog.objects.filter(monitor=monitor).first()
print("API LOG META:", log.meta if log else None)

monitor.delete()
