import secrets
from urllib.parse import urlparse

from rest_framework import serializers

from .apprise_channel import validate_apprise_url
from .net import BlockedTargetError, validate_outbound_url
from .models import (
    Monitor, Incident, IncidentUpdate, ApiLog,
    StatusPage, StatusPageMonitor, Subscriber,
    AlertChannel, NotificationLog, ApiToken, MaintenanceWindow,
)


# ---------------------------------------------------------------------------
# Shared field validation
# ---------------------------------------------------------------------------

def validate_status_codes(value):
    """Accept a list of HTTP status codes; tolerate a bare int for convenience."""
    codes = [value] if isinstance(value, int) else value
    if not isinstance(codes, list) or not codes:
        raise serializers.ValidationError('Must be a non-empty list of status codes.')
    for code in codes:
        if not isinstance(code, int) or not 100 <= code <= 599:
            raise serializers.ValidationError(f'{code!r} is not a valid HTTP status code.')
    return codes


#: Types that dial an HTTP(S) URL. The rest take a bare hostname, or nothing.
URL_TYPES = {'http', 'keyword', 'json'}
HOST_TYPES = {'ping', 'port', 'dns', 'ssl', 'domain'}


def validate_monitor_config(attrs, instance=None):
    """
    Cross-field validation, since what `url` even means depends on the type.

    Each type carries its own required fields; without this a keyword monitor
    with no keyword would silently pass every check forever.
    """
    def current(field, default=None):
        if field in attrs:
            return attrs[field]
        return getattr(instance, field, default) if instance else default

    mtype = current('type', 'http')
    url = (current('url', '') or '').strip()
    errors = {}

    if mtype == 'heartbeat':
        # Nothing is dialled out; the job pushes to us.
        return attrs

    if not url:
        errors['url'] = 'A URL or hostname is required for this monitor type.'
    elif mtype in URL_TYPES:
        if '://' not in url:
            errors['url'] = 'Must be a full http:// or https:// URL.'
        else:
            try:
                validate_outbound_url(url, allow_unresolvable=True)
            except BlockedTargetError as exc:
                errors['url'] = str(exc)

    if mtype == 'keyword' and not (current('keyword', '') or '').strip():
        errors['keyword'] = 'A keyword is required for keyword monitors.'
    if mtype == 'json':
        if not (current('json_path', '') or '').strip():
            errors['json_path'] = 'A JSON path is required for JSON monitors.'
        if current('json_expected', None) in (None, ''):
            errors['json_expected'] = 'An expected value is required for JSON monitors.'
    if mtype == 'port' and not current('port'):
        errors['port'] = 'A port is required for TCP port monitors.'

    if errors:
        raise serializers.ValidationError(errors)
    return attrs


def validate_monitor_url(value):
    """
    Reject monitor targets that point into our own network.

    This is a fail-fast for the user's benefit; it is NOT the security boundary.
    DNS can change between now and the check, so `run_check` re-validates
    immediately before every request. See `surveillance.net`.
    """
    try:
        return validate_outbound_url(value, allow_unresolvable=True)
    except BlockedTargetError as exc:
        raise serializers.ValidationError(str(exc))


# ---------------------------------------------------------------------------
# Monitor Serializers
# ---------------------------------------------------------------------------

class MonitorListSerializer(serializers.ModelSerializer):
    """
    List view with everything the dashboard row needs.

    `heartbeat` and `uptime_24h` are included here on purpose: the monitor list
    renders a heartbeat strip and an uptime badge per row, and fetching those
    separately would be one request per monitor. The view prefetches them, so
    this stays a fixed number of queries regardless of how many monitors exist.
    """
    heartbeat = serializers.SerializerMethodField()
    uptime_24h = serializers.SerializerMethodField()

    class Meta:
        model = Monitor
        fields = [
            'id', 'name', 'type', 'url', 'status', 'last_status',
            'interval', 'http_method', 'created_at', 'last_checked_at',
            'heartbeat', 'uptime_24h',
        ]

    def get_heartbeat(self, obj):
        """Oldest→newest so the strip reads left to right like a timeline."""
        beats = getattr(obj, 'recent_checks', None)
        if beats is None:
            return []
        return [
            {
                'result': b.result,
                'response_time_ms': b.response_time_ms,
                'checked_at': b.checked_at,
            }
            for b in reversed(beats)
        ]

    def get_uptime_24h(self, obj):
        beats = getattr(obj, 'recent_checks', None)
        if not beats:
            return None
        failed = sum(1 for b in beats if b.result == 'failure')
        return round((len(beats) - failed) / len(beats) * 100, 2)


class MonitorDetailSerializer(serializers.ModelSerializer):
    """Full detail including all config fields."""
    heartbeat_url = serializers.SerializerMethodField()

    def get_heartbeat_url(self, obj):
        """The URL a cron job should curl. Only meaningful for heartbeats."""
        if obj.type != 'heartbeat' or not obj.heartbeat_token:
            return None
        request = self.context.get('request')
        path = f'/api/v1/heartbeat/{obj.heartbeat_token}/'
        return request.build_absolute_uri(path) if request else path

    class Meta:
        model = Monitor
        fields = [
            'id', 'name', 'url', 'status', 'last_status',
            'interval', 'http_method', 'request_headers', 'request_body',
            'expected_status_codes', 'timeout_ms', 'follow_redirect',
            'consecutive_failures', 'degraded_threshold_ms', 'last_checked_at',
            'created_at', 'updated_at', 'created_by',
            'type', 'port', 'keyword', 'keyword_inverted', 'json_path',
            'json_expected', 'dns_record_type', 'dns_expected',
            'heartbeat_grace_seconds',
            'heartbeat_token', 'heartbeat_url', 'last_heartbeat_at',
        ]
        read_only_fields = ['id', 'last_status', 'consecutive_failures', 'created_at', 'updated_at', 'created_by']


class MonitorCreateSerializer(serializers.ModelSerializer):
    """Create a monitor."""
    def validate_expected_status_codes(self, value):
        return validate_status_codes(value)

    def validate(self, attrs):
        return validate_monitor_config(attrs, getattr(self, 'instance', None))

    class Meta:
        model = Monitor
        fields = [
            'name', 'url', 'interval', 'http_method',
            'request_headers', 'request_body', 'expected_status_codes',
            'timeout_ms', 'follow_redirect', 'degraded_threshold_ms',
            'type', 'port', 'keyword', 'keyword_inverted', 'json_path',
            'json_expected', 'dns_record_type', 'dns_expected',
            'heartbeat_grace_seconds',
        ]

    def create(self, validated_data):
        org = self.context['organization']
        user = self.context['request'].user

        # Heartbeat monitors need a token before they can be pinged; minting it
        # here means the URL is available the moment the monitor exists.
        if validated_data.get('type') == 'heartbeat':
            validated_data['heartbeat_token'] = secrets.token_urlsafe(24)

        monitor = Monitor.objects.create(
            organization=org,
            created_by=user,
            **validated_data,
        )
        return monitor


class MonitorUpdateSerializer(serializers.ModelSerializer):
    """Partial update — any of the config fields."""
    def validate_expected_status_codes(self, value):
        return validate_status_codes(value)

    def validate(self, attrs):
        return validate_monitor_config(attrs, getattr(self, 'instance', None))

    class Meta:
        model = Monitor
        fields = [
            'name', 'url', 'interval', 'http_method',
            'request_headers', 'request_body', 'expected_status_codes',
            'timeout_ms', 'follow_redirect', 'degraded_threshold_ms',
            'type', 'port', 'keyword', 'keyword_inverted', 'json_path',
            'json_expected', 'dns_record_type', 'dns_expected',
            'heartbeat_grace_seconds',
        ]

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        return instance


# ---------------------------------------------------------------------------
# ApiLog / Check History Serializer
# ---------------------------------------------------------------------------

class ApiLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApiLog
        fields = [
            'id', 'region', 'status_code', 'response_time_ms', 'result',
            'dns_ms', 'connect_ms', 'tls_ms', 'ttfb_ms',
            'error_message', 'ssl_valid', 'ssl_expires_at', 'checked_at',
        ]


# ---------------------------------------------------------------------------
# Incident Serializers
# ---------------------------------------------------------------------------

class IncidentUpdateSerializer(serializers.ModelSerializer):
    posted_by_email = serializers.ReadOnlyField(source='posted_by.email')

    class Meta:
        model = IncidentUpdate
        fields = ['id', 'status', 'message', 'posted_at', 'posted_by_email']
        read_only_fields = ['id', 'posted_at', 'posted_by_email']


class IncidentSerializer(serializers.ModelSerializer):
    updates = IncidentUpdateSerializer(many=True, read_only=True)
    monitor_name = serializers.ReadOnlyField(source='monitor.name')

    class Meta:
        model = Incident
        fields = [
            'id', 'title', 'status', 'severity', 'monitor_name',
            'started_at', 'resolved_at', 'updates',
        ]
        read_only_fields = ['id', 'started_at', 'monitor_name']


class IncidentPostUpdateSerializer(serializers.ModelSerializer):
    """For posting a new status update to an incident."""
    class Meta:
        model = IncidentUpdate
        fields = ['status', 'message']


# ---------------------------------------------------------------------------
# Uptime Stats Serializer
# ---------------------------------------------------------------------------

class UptimeWindowSerializer(serializers.Serializer):
    window = serializers.CharField()
    total_checks = serializers.IntegerField()
    successful_checks = serializers.IntegerField()
    failed_checks = serializers.IntegerField()
    uptime_pct = serializers.FloatField()
    avg_response_time_ms = serializers.FloatField(allow_null=True)
    # Averages hide the tail; percentiles are where the slow requests show up.
    p50_response_time_ms = serializers.IntegerField(allow_null=True, required=False)
    p95_response_time_ms = serializers.IntegerField(allow_null=True, required=False)
    p99_response_time_ms = serializers.IntegerField(allow_null=True, required=False)


# ---------------------------------------------------------------------------
# Status Page Serializers
# ---------------------------------------------------------------------------

class StatusPageMonitorSerializer(serializers.ModelSerializer):
    id = serializers.ReadOnlyField(source='monitor.id')
    name = serializers.ReadOnlyField(source='monitor.name')
    last_status = serializers.ReadOnlyField(source='monitor.last_status')

    class Meta:
        model = StatusPageMonitor
        fields = ['id', 'name', 'last_status', 'display_order']


class StatusPageSerializer(serializers.ModelSerializer):
    monitors = StatusPageMonitorSerializer(source='page_monitors', many=True, read_only=True)
    subscriber_count = serializers.SerializerMethodField()

    class Meta:
        model = StatusPage
        fields = [
            'id', 'slug', 'title', 'is_public', 'theme',
            'custom_domain', 'monitors', 'subscriber_count',
            'is_password_protected',
        ]

    def get_subscriber_count(self, obj):
        return obj.subscribers.filter(verified=True).count()


class StatusPageWriteSerializer(serializers.ModelSerializer):
    """
    Create/update a status page, optionally replacing its monitor list.

    `monitors` is the full desired set of monitor ids — sending it replaces
    what's attached, which is what "add/remove monitors" means for a PATCH
    from an editor UI.
    """
    monitors = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True
    )
    # Write-only: set to a string to protect the page, empty string to remove
    # the password. It is never echoed back.
    password = serializers.CharField(
        required=False, allow_blank=True, write_only=True,
    )

    class Meta:
        model = StatusPage
        fields = ['slug', 'title', 'is_public', 'theme', 'custom_domain',
                  'monitors', 'password']

    def validate_monitors(self, value):
        org = self.context['organization']
        owned = set(
            Monitor.objects.filter(
                id__in=value, organization=org, deleted_at__isnull=True
            ).values_list('id', flat=True)
        )
        missing = [mid for mid in value if mid not in owned]
        if missing:
            raise serializers.ValidationError(
                f'Monitors not found in this organization: {missing}'
            )
        return value

    def _sync_monitors(self, page, monitor_ids):
        page.page_monitors.exclude(monitor_id__in=monitor_ids).delete()
        existing = set(page.page_monitors.values_list('monitor_id', flat=True))
        for order, monitor_id in enumerate(monitor_ids):
            if monitor_id in existing:
                page.page_monitors.filter(monitor_id=monitor_id).update(display_order=order)
            else:
                StatusPageMonitor.objects.create(
                    status_page=page, monitor_id=monitor_id, display_order=order
                )

    def create(self, validated_data):
        monitor_ids = validated_data.pop('monitors', [])
        password = validated_data.pop('password', None)
        page = StatusPage(organization=self.context['organization'], **validated_data)
        if password is not None:
            page.set_password(password)
        page.save()
        self._sync_monitors(page, monitor_ids)
        return page

    def update(self, instance, validated_data):
        monitor_ids = validated_data.pop('monitors', None)
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        # An explicit empty string removes the password; omitting the field
        # leaves it untouched.
        if password is not None:
            instance.set_password(password)
        instance.save()
        if monitor_ids is not None:
            self._sync_monitors(instance, monitor_ids)
        return instance


# ---------------------------------------------------------------------------
# Public (unauthenticated) Serializers
# ---------------------------------------------------------------------------

class PublicIncidentSerializer(serializers.ModelSerializer):
    monitor = serializers.ReadOnlyField(source='monitor.name')
    updates = IncidentUpdateSerializer(many=True, read_only=True)

    class Meta:
        model = Incident
        fields = ['id', 'title', 'status', 'severity', 'monitor',
                  'started_at', 'resolved_at', 'updates']


class SubscribeSerializer(serializers.Serializer):
    email = serializers.EmailField()


# ---------------------------------------------------------------------------
# Alert Channel Serializers
# ---------------------------------------------------------------------------

WEBHOOK_TYPES = ('slack', 'discord', 'webhook', 'apprise')


class AlertChannelSerializer(serializers.ModelSerializer):
    """
    Read view. `config` is masked because it holds the webhook secret — the URL
    itself is the credential for Slack and Discord.
    """
    config = serializers.SerializerMethodField()

    class Meta:
        model = AlertChannel
        fields = ['id', 'type', 'config', 'is_enabled']

    def get_config(self, obj):
        config = dict(obj.config or {})
        url = config.get('url')
        if url:
            config['url'] = url[:30] + '…' if len(url) > 30 else url
        return config


class AlertChannelWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlertChannel
        fields = ['type', 'config', 'is_enabled']

    def validate_type(self, value):
        if value not in WEBHOOK_TYPES:
            raise serializers.ValidationError(
                f'Email is a non-goal for v1. Choose one of: {", ".join(WEBHOOK_TYPES)}.'
            )
        return value

    def validate(self, attrs):
        """
        Validated as a whole because the rules depend on the channel type:
        Apprise URLs use service schemes (tgram://, ntfy://) that would fail an
        https-only check, while Slack/Discord/webhook must stay https.
        """
        channel_type = attrs.get('type') or getattr(self.instance, 'type', None)
        config = attrs.get('config')
        if config is None:
            config = getattr(self.instance, 'config', None) or {}
        if not isinstance(config, dict):
            raise serializers.ValidationError({'config': 'config must be an object.'})

        url = config.get('url')
        if not url:
            raise serializers.ValidationError({'config': 'config.url is required.'})

        if channel_type == 'apprise':
            try:
                validate_apprise_url(url)
            except BlockedTargetError as exc:
                raise serializers.ValidationError({'config': str(exc)})
            return attrs

        if urlparse(url).scheme != 'https':
            raise serializers.ValidationError(
                {'config': 'config.url must be an https:// URL.'}
            )
        # A webhook URL is an outbound request target like any other; without
        # this it was an SSRF sink that reported results back to the caller.
        try:
            validate_outbound_url(url, allow_unresolvable=True)
        except BlockedTargetError as exc:
            raise serializers.ValidationError({'config': f'config.url: {exc}'})
        return attrs

    def create(self, validated_data):
        return AlertChannel.objects.create(
            organization=self.context['organization'], **validated_data
        )


class NotificationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationLog
        fields = ['id', 'alert_channel', 'incident', 'status', 'sent_at', 'error_message']


# ---------------------------------------------------------------------------
# API Token Serializers
# ---------------------------------------------------------------------------

class ApiTokenSerializer(serializers.ModelSerializer):
    """List view — never exposes anything that can be replayed."""
    created_by = serializers.ReadOnlyField(source='user.email')

    class Meta:
        model = ApiToken
        fields = ['id', 'name', 'prefix', 'created_by',
                  'last_used_at', 'expires_at', 'created_at']


class ApiTokenCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    expires_in_days = serializers.IntegerField(
        required=False, min_value=1, max_value=3650,
        help_text='Omit for a token that never expires.',
    )


# ---------------------------------------------------------------------------
# Maintenance windows
# ---------------------------------------------------------------------------

class MaintenanceWindowSerializer(serializers.ModelSerializer):
    state = serializers.ReadOnlyField()
    monitor_ids = serializers.PrimaryKeyRelatedField(
        source='monitors', many=True, read_only=True,
    )

    class Meta:
        model = MaintenanceWindow
        fields = [
            'id', 'title', 'description', 'starts_at', 'ends_at',
            'suppress_alerts', 'exclude_from_uptime', 'state',
            'monitor_ids', 'created_at',
        ]


class MaintenanceWindowWriteSerializer(serializers.ModelSerializer):
    monitors = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True,
        help_text='Monitor ids. Omit or leave empty to cover the whole organization.',
    )

    class Meta:
        model = MaintenanceWindow
        fields = [
            'title', 'description', 'starts_at', 'ends_at',
            'suppress_alerts', 'exclude_from_uptime', 'monitors',
        ]

    def validate(self, attrs):
        starts = attrs.get('starts_at') or getattr(self.instance, 'starts_at', None)
        ends = attrs.get('ends_at') or getattr(self.instance, 'ends_at', None)
        if starts and ends and ends <= starts:
            raise serializers.ValidationError(
                {'ends_at': 'The window must end after it starts.'}
            )
        return attrs

    def validate_monitors(self, value):
        org = self.context['organization']
        owned = set(
            Monitor.objects.filter(id__in=value, organization=org)
            .values_list('id', flat=True)
        )
        missing = [m for m in value if m not in owned]
        if missing:
            raise serializers.ValidationError(
                f'Monitors not found in this organization: {missing}'
            )
        return value

    def create(self, validated_data):
        monitor_ids = validated_data.pop('monitors', [])
        window = MaintenanceWindow.objects.create(
            organization=self.context['organization'],
            created_by=self.context['request'].user,
            **validated_data,
        )
        if monitor_ids:
            window.monitors.set(monitor_ids)
        return window

    def update(self, instance, validated_data):
        monitor_ids = validated_data.pop('monitors', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if monitor_ids is not None:
            instance.monitors.set(monitor_ids)
        return instance
