from django.contrib import admin
from .models import (
    Monitor, Incident, IncidentUpdate,
    ApiLog, StatusPage, AlertChannel, ApiToken, NotificationLog,
)


@admin.register(Monitor)
class MonitorAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'url', 'organization', 'status', 'last_status', 'interval', 'created_at')
    list_filter = ('status', 'last_status', 'http_method')
    search_fields = ('name', 'url')
    readonly_fields = ('created_at', 'updated_at', 'deleted_at', 'consecutive_failures')


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'monitor', 'organization', 'status', 'severity', 'started_at', 'resolved_at')
    list_filter = ('status', 'severity')
    search_fields = ('title',)


@admin.register(IncidentUpdate)
class IncidentUpdateAdmin(admin.ModelAdmin):
    list_display = ('id', 'incident', 'status', 'posted_at', 'posted_by')


@admin.register(ApiLog)
class ApiLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'monitor', 'region', 'result', 'status_code', 'response_time_ms', 'checked_at')
    list_filter = ('result', 'region')


@admin.register(StatusPage)
class StatusPageAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'organization', 'slug', 'is_public', 'theme')


@admin.register(AlertChannel)
class AlertChannelAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'type', 'is_enabled')


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'name')


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'incident', 'alert_channel', 'status', 'sent_at')
