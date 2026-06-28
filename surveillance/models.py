from django.db import models
from users.models import User
from organizations.models import *


class Monitor(models.Model):
    organization_id = models.ForeignKey(to=Organization,related_name="organization",on_delete=models.CASCADE)
    url = models.TextField()
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("archive", "Archive")
    ]
    HTTP_REQUEST = [
        ("get", "Get"),
        ("post", "Post"),
        ("put", "Put"),
        ("delete", "Delete")
    ]
    SERVER_STATUS = [
        ("up", "Up"),
        ("down", "Down"),
        ("degraded", "Degraded")
    ]
    
    status = models.CharField(max_length=20,choices=STATUS_CHOICES,default="active")
    interval = models.IntegerField(null=True)
    http_method = models.CharField(max_length=20,choices=HTTP_REQUEST, default="get")
    request_headers = models.JSONField()
    request_body = models.JSONField(null=True)
    expected_status_codes = models.IntegerField()
    timeout_ms = models.IntegerField()
    follow_redirect = models.BooleanField()
    last_status = models.CharField(max_length=20,choices=SERVER_STATUS,default="up")
    consecutive_failures = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now_add=True, null=True)
    created_by = models.ForeignKey(to=User, related_name="user", on_delete=models.CASCADE)

class monitorRegion(models.Model):
    monitor_id = models.ForeignKey(to=Monitor,related_name="region_monitors",on_delete=models.CASCADE)
    region = models.CharField(max_length=20)

class Incident(models.Model):
    organization_id = models.ForeignKey(to=Organization,related_name="incident_organizations", on_delete=models.CASCADE)
    monitor_id = models.ForeignKey(to=Monitor, related_name="monitors", on_delete=models.CASCADE)
    title = models.TextField()
    STATUS_CHOICES = [
        ('investigating', 'Investigating'),
        ('identified', 'Identified'),
        ('monitoring', 'Monitoring'),
        ('resolved', 'Resolved')
    ]
    status = models.CharField(max_length=20,choices=STATUS_CHOICES,default='investigating')
    SEVERITY_CHOICES = [
        ('minor', 'Minor'),
        ('major', 'Major'),
        ('critical', 'Critical')
    ]
    severity = models.CharField(max_length=20,choices=SEVERITY_CHOICES,default='minor')
    started_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True)
    created_by = models.ForeignKey(to=User, related_name='users',on_delete=models.CASCADE)

class IncidentUpdate(models.Model):
    incident = models.ForeignKey(to=Incident,related_name='incidents', on_delete=models.CASCADE)
    STATUS_CHOICES = [
        ('investigating', 'Investigating'),
        ('identified', 'Identified'),
        ('monitoring', 'Monitoring'),
        ('resolved', 'Resolved')
    ]
    status = models.CharField(max_length=20,choices=STATUS_CHOICES,default='investigating')
    message = models.TextField()
    posted_at = models.DateTimeField()
    posted_by = models.ForeignKey(to=User,related_name='incident_users', on_delete=models.CASCADE)

class ApiLog(models.Model):
    monitor_id = models.ForeignKey(to=Monitor, related_name="apiLog_monitors",on_delete=models.CASCADE)
    status_code = models.IntegerField()
    response_time = models.IntegerField()
    region = models.CharField(max_length=20)
    error_message = models.TextField()
    ssl_valid = models.BooleanField()
    ssl_expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    models.Index(fields=['monitor_id', '-created_at'])

class StatusPage(models.Model):
    THEME_CHOICES = [
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('auto', 'Auto')
    ]
    organization_id = models.ForeignKey(to=Organization, related_name='status_organization',on_delete=models.CASCADE)
    slug = models.TextField()
    title = models.TextField()
    is_public = models.BooleanField()
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default='auto')
    custom_domain = models.TextField(null=True)

class StatusPageMonitor(models.Model):
    status_page_id = models.ForeignKey(to=StatusPage,related_name="statuspages", on_delete=models.CASCADE)
    monitor_id = models.ForeignKey(to=Monitor, related_name="statuspage_monitor",on_delete=models.CASCADE)
    display_order = models.IntegerField()

class Subscriber(models.Model):
    status_page_id = models.ForeignKey(to=StatusPageMonitor, related_name="statuspagemonitors", on_delete=models.CASCADE)
    email = models.EmailField()
    webhook_url = models.URLField(null=True)
    verified = models.BooleanField()
    verification_token = models.TextField()
    subscribed_at = models.DateTimeField()

class AlertChannel(models.Model):
    organization_id = models.ForeignKey(to=Organization, related_name="alert_organization", on_delete=models.CASCADE)
    TYPE_LIST = [
      ('email', 'Email'),
        ('slack', 'Slack'),
        ('webhook', 'Webhook'),
        ('discord', 'Discord')
    ]
    type = models.CharField(max_length=20,choices=TYPE_LIST,default='email')
    config = models.JSONField()
    is_enabled = models.BooleanField()

class ApiToken(models.Model):
    user_id = models.ForeignKey(to=User, related_name="token_user", on_delete=models.CASCADE)
    name = models.TextField()
    token_hash = models.TextField()

class NotificationLog(models.Model):
    alert_channel_id = models.ForeignKey(to=AlertChannel, related_name="notifications", on_delete=models.CASCADE)
    incident_id = models.ForeignKey(to=Incident,related_name="notif_log", on_delete=models.CASCADE)
    sent_at = models.DateTimeField()
    STATUS_TYPES = [
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('rate_limited', "Rated_Limited")
    ]
    status = models.CharField(max_length=20,choices=STATUS_TYPES, default='sent')
    error_message = models.TextField()








