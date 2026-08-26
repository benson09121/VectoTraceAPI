from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from users.models import User
from organizations.models import Organization
from .fields import EncryptedJSONField, EncryptedURLField

# The floor on check frequency. Beat ticks faster than this so a monitor set to
# the minimum actually fires at the minimum rather than at the tick rate.
MIN_INTERVAL_SECONDS = 20


def default_status_codes():
    """Callable default so migrations don't share a mutable list."""
    return [200]


class Monitor(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('archived', 'Archived'),
    ]
    HTTP_REQUEST = [
        ('GET', 'GET'),
        ('POST', 'POST'),
        ('PUT', 'PUT'),
        ('DELETE', 'DELETE'),
        ('HEAD', 'HEAD'),
    ]
    SERVER_STATUS = [
        ('up', 'Up'),
        ('down', 'Down'),
        ('degraded', 'Degraded'),
    ]

    TYPE_CHOICES = [
        ('http', 'HTTP(S)'),
        ('keyword', 'Keyword in body'),
        ('json', 'JSON query'),
        ('ping', 'Ping (ICMP)'),
        ('port', 'TCP port'),
        ('dns', 'DNS record'),
        ('ssl', 'SSL certificate'),
        ('domain', 'Domain expiry'),
        ('heartbeat', 'Heartbeat (push)'),
    ]

    organization = models.ForeignKey(
        Organization, related_name='monitors', on_delete=models.CASCADE
    )
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='http')
    # For http/keyword/json/ssl this is a URL; for ping/port/dns/domain it is a
    # hostname. Heartbeat monitors ignore it entirely — nothing is dialled out.
    url = models.TextField(blank=True)

    # --- type-specific configuration -------------------------------------
    port = models.IntegerField(null=True, blank=True, help_text='TCP port monitors.')
    keyword = models.TextField(blank=True, help_text='Text the response body must contain.')
    keyword_inverted = models.BooleanField(
        default=False, help_text='Fail when the keyword IS present instead.',
    )
    script_content = models.TextField(blank=True, help_text='Playwright/JS script content for browser/script checks.')
    json_path = models.TextField(
        blank=True, help_text='Dotted path into the JSON body, e.g. data.status',
    )
    json_expected = models.TextField(blank=True, help_text='Value that path must equal.')
    dns_record_type = models.CharField(max_length=10, blank=True, default='A')
    dns_expected = models.TextField(blank=True, help_text='Expected record value.')
    # Heartbeat: the job pushes to us. If nothing arrives within
    # interval + grace, the monitor goes down.
    heartbeat_token = models.CharField(max_length=64, blank=True, db_index=True)
    heartbeat_grace_seconds = models.IntegerField(default=60)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    interval = models.IntegerField(
        default=60,
        validators=[MinValueValidator(MIN_INTERVAL_SECONDS)],
        help_text=f'Check interval in seconds (minimum {MIN_INTERVAL_SECONDS}).',
    )
    http_method = models.CharField(max_length=10, choices=HTTP_REQUEST, default='GET')
    request_headers = EncryptedJSONField(default=dict, blank=True)
    request_body = EncryptedJSONField(null=True, blank=True)
    expected_status_codes = models.JSONField(
        default=default_status_codes,
        help_text='List of status codes treated as healthy, e.g. [200, 201, 204].',
    )
    timeout_ms = models.IntegerField(default=30000)
    follow_redirect = models.BooleanField(default=True)
    last_status = models.CharField(max_length=20, choices=SERVER_STATUS, default='up')
    # Denormalised from ApiLog so the dispatcher can find due monitors with one
    # indexed query instead of a MAX(checked_at) subquery per monitor per tick.
    last_checked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # Response time above this marks the monitor 'degraded' rather than 'up'.
    # Null disables the check — a monitor that is merely slow is still up.
    degraded_threshold_ms = models.IntegerField(
        null=True, blank=True,
        help_text='Responses slower than this mark the monitor degraded.',
    )
    # Positive = consecutive failures, negative = consecutive successes while recovering
    consecutive_failures = models.IntegerField(default=0)
    deleted_at = models.DateTimeField(null=True, blank=True)  # soft-delete
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    created_by = models.ForeignKey(User, related_name='created_monitors', on_delete=models.CASCADE)
    
    # Selected probes for execution. Empty means use the default central probe.
    probes = models.ManyToManyField('surveillance.Probe', related_name='monitors', blank=True)
    
    # Escalation policy for incidents triggered by this monitor
    escalation_policy = models.ForeignKey('surveillance.EscalationPolicy', related_name='monitors', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = 'surveillance_monitor'

    def __str__(self):
        return f'{self.name} ({self.url})'

    @property
    def is_archived(self):
        return self.deleted_at is not None


class Incident(models.Model):
    STATUS_CHOICES = [
        ('investigating', 'Investigating'),
        ('identified', 'Identified'),
        ('monitoring', 'Monitoring'),
        ('resolved', 'Resolved'),
    ]
    SEVERITY_CHOICES = [
        ('minor', 'Minor'),
        ('major', 'Major'),
        ('critical', 'Critical'),
    ]

    organization = models.ForeignKey(
        Organization, related_name='incidents', on_delete=models.CASCADE
    )
    monitor = models.ForeignKey(
        Monitor, related_name='incidents', on_delete=models.CASCADE
    )
    title = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='investigating')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='minor')
    started_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    commander = models.ForeignKey(User, related_name='commanded_incidents', on_delete=models.SET_NULL, null=True, blank=True)
    created_by = models.ForeignKey(User, related_name='created_incidents', on_delete=models.CASCADE)

    class Meta:
        db_table = 'surveillance_incident'
        constraints = [
            # DB safety net: at most one unresolved incident per monitor.
            # The app layer guards this too, but two racing workers can both
            # pass the guard — the DB is what actually makes it impossible.
            models.UniqueConstraint(
                fields=['monitor'],
                condition=Q(resolved_at__isnull=True),
                name='unique_open_incident_per_monitor',
            ),
        ]

    def __str__(self):
        return self.title


class IncidentUpdate(models.Model):
    STATUS_CHOICES = [
        ('investigating', 'Investigating'),
        ('identified', 'Identified'),
        ('monitoring', 'Monitoring'),
        ('resolved', 'Resolved'),
    ]

    incident = models.ForeignKey(Incident, related_name='updates', on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='investigating')
    message = models.TextField()
    posted_at = models.DateTimeField(auto_now_add=True)
    posted_by = models.ForeignKey(User, related_name='incident_updates', on_delete=models.CASCADE)

    class Meta:
        db_table = 'surveillance_incidentupdate'


class ApiLog(models.Model):
    """One record per check execution."""
    CHECK_RESULT = [
        ('success', 'Success'),
        ('failure', 'Failure'),
    ]

    monitor = models.ForeignKey(
        Monitor, related_name='api_logs', on_delete=models.CASCADE, db_index=True
    )
    region = models.CharField(max_length=50)
    status_code = models.IntegerField(null=True, blank=True)
    response_time_ms = models.IntegerField(null=True, blank=True)
    # Where the time actually went. "Your site is slow" is not actionable;
    # "DNS took 800ms" is. Nulls where a phase doesn't apply (no TLS on http://).
    dns_ms = models.IntegerField(null=True, blank=True)
    connect_ms = models.IntegerField(null=True, blank=True)
    tls_ms = models.IntegerField(null=True, blank=True)
    ttfb_ms = models.IntegerField(null=True, blank=True)
    result = models.CharField(max_length=10, choices=CHECK_RESULT, default='success')
    error_message = models.TextField(null=True, blank=True)
    ssl_valid = models.BooleanField(null=True, blank=True)
    ssl_expires_at = models.DateTimeField(null=True, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    # Set explicitly by run_check (not auto_now_add) so a retried task writing
    # the same check dedupes against the unique constraint below.
    checked_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'surveillance_apilog'
        indexes = [
            models.Index(fields=['monitor', '-checked_at'], name='apilog_monitor_checked_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['monitor', 'checked_at', 'region'],
                name='unique_check_per_monitor_time_region',
            ),
        ]

    def __str__(self):
        return f'{self.monitor} [{self.region}] {self.result} @ {self.checked_at}'


class MonitorHourlyStat(models.Model):
    """
    One pre-aggregated row per monitor per hour.

    Uptime used to be COUNT/AVG over raw ApiLog rows on every request, so the
    90-day window scanned ~130k rows per monitor and got slower every day the
    product ran. Rolling up hourly turns that into ~2,160 rows, and lets raw
    check rows be deleted on a retention schedule without losing history.
    """
    monitor = models.ForeignKey(Monitor, related_name='hourly_stats', on_delete=models.CASCADE)
    hour = models.DateTimeField(db_index=True, help_text='Truncated to the hour, UTC.')

    total_checks = models.IntegerField(default=0)
    failed_checks = models.IntegerField(default=0)
    degraded_checks = models.IntegerField(default=0)

    avg_response_time_ms = models.FloatField(null=True, blank=True)
    min_response_time_ms = models.IntegerField(null=True, blank=True)
    max_response_time_ms = models.IntegerField(null=True, blank=True)
    # Averages hide the tail, which is where users actually live.
    p50_response_time_ms = models.IntegerField(null=True, blank=True)
    p95_response_time_ms = models.IntegerField(null=True, blank=True)
    p99_response_time_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'surveillance_monitorhourlystat'
        unique_together = ('monitor', 'hour')
        indexes = [models.Index(fields=['monitor', '-hour'], name='hourly_monitor_hour_idx')]

    def __str__(self):
        return f'{self.monitor} @ {self.hour:%Y-%m-%d %H:00}'

    @property
    def successful_checks(self):
        return self.total_checks - self.failed_checks


class StatusPage(models.Model):
    THEME_CHOICES = [
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('auto', 'Auto'),
    ]
    organization = models.ForeignKey(
        Organization, related_name='status_pages', on_delete=models.CASCADE
    )
    # Slug is the public URL key (/status/{slug}) so it must be globally unique.
    slug = models.SlugField(max_length=63, unique=True)
    title = models.TextField()
    is_public = models.BooleanField(default=True)
    theme = models.CharField(max_length=20, choices=THEME_CHOICES, default='auto')
    custom_domain = models.TextField(null=True, blank=True)
    # Hashed with Django's password hasher, never stored in plaintext — a page
    # password is a credential like any other, even for a "just internal" page.
    password_hash = models.CharField(max_length=255, blank=True)

    def set_password(self, raw: str | None):
        from django.contrib.auth.hashers import make_password
        self.password_hash = make_password(raw) if raw else ''

    def check_password(self, raw: str | None) -> bool:
        from django.contrib.auth.hashers import check_password
        if not self.password_hash:
            return True  # no password set
        return bool(raw) and check_password(raw, self.password_hash)

    @property
    def is_password_protected(self) -> bool:
        return bool(self.password_hash)

    class Meta:
        db_table = 'surveillance_statuspage'

    def __str__(self):
        return f'{self.title} (/{self.slug})'


class StatusPageMonitor(models.Model):
    status_page = models.ForeignKey(StatusPage, related_name='page_monitors', on_delete=models.CASCADE)
    monitor = models.ForeignKey(Monitor, related_name='status_page_entries', on_delete=models.CASCADE)
    display_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'surveillance_statuspagemonitor'
        unique_together = ('status_page', 'monitor')
        ordering = ['display_order', 'id']


class Subscriber(models.Model):
    status_page = models.ForeignKey(StatusPage, related_name='subscribers', on_delete=models.CASCADE)
    email = models.EmailField()
    webhook_url = models.URLField(null=True, blank=True)
    verified = models.BooleanField(default=False)
    verification_token = models.CharField(max_length=64, db_index=True)
    # Long-lived, unlike the single-use verification token: it goes in every
    # notification, and a one-click unsubscribe is the difference between a
    # spam report and a quiet exit.
    unsubscribe_token = models.CharField(max_length=64, blank=True, db_index=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'surveillance_subscriber'
        unique_together = ('status_page', 'email')

    def __str__(self):
        return f'{self.email} → {self.status_page.slug}'


class MaintenanceWindow(models.Model):
    """
    Planned downtime.

    Two jobs: tell the public page's readers before they panic, and stop the
    engine paging the team during their own deploy. Every competitor has this —
    without it, scheduled work looks identical to an outage.
    """
    organization = models.ForeignKey(
        Organization, related_name='maintenance_windows', on_delete=models.CASCADE
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    # Affected monitors. Empty means the whole organization.
    monitors = models.ManyToManyField(Monitor, blank=True, related_name='maintenance_windows')
    # Suppress alerts for the affected monitors while the window is open.
    suppress_alerts = models.BooleanField(default=True)
    # Exclude checks in the window from uptime maths, so planned work doesn't
    # count against the SLA.
    exclude_from_uptime = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User, related_name='maintenance_windows', on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'surveillance_maintenancewindow'
        ordering = ['-starts_at']
        indexes = [models.Index(fields=['organization', '-starts_at'],
                                name='maint_org_starts_idx')]

    def __str__(self):
        return f'{self.title} ({self.starts_at:%Y-%m-%d %H:%M} → {self.ends_at:%H:%M})'

    @property
    def is_active(self) -> bool:
        return self.starts_at <= timezone.now() <= self.ends_at

    @property
    def state(self) -> str:
        now = timezone.now()
        if now < self.starts_at:
            return 'scheduled'
        return 'in_progress' if now <= self.ends_at else 'completed'

    def covers(self, monitor) -> bool:
        """No explicit monitors means the window covers the whole org."""
        if not self.monitors.exists():
            return monitor.organization_id == self.organization_id
        return self.monitors.filter(pk=monitor.pk).exists()


class AlertChannel(models.Model):
    TYPE_LIST = [
        ('slack', 'Slack'),
        ('discord', 'Discord'),
        ('webhook', 'Webhook'),
        # Everything else. One Apprise URL covers 200+ schemas (Telegram,
        # Matrix, ntfy, Gotify, Teams, Signal, email, SMS gateways, …) without
        # hand-writing an integration per service.
        ('apprise', 'Apprise (200+ services)'),
    ]
    organization = models.ForeignKey(
        Organization, related_name='alert_channels', on_delete=models.CASCADE
    )
    type = models.CharField(max_length=20, choices=TYPE_LIST, default='email')
    config = EncryptedJSONField(default=dict)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'surveillance_alertchannel'


class ApiToken(models.Model):
    user = models.ForeignKey(User, related_name='api_tokens', on_delete=models.CASCADE)
    organization = models.ForeignKey(
        Organization, related_name='api_tokens', on_delete=models.CASCADE
    )
    name = models.TextField()
    # sha256 of the plaintext token. The plaintext is returned once at creation
    # and never stored, so a DB leak yields nothing usable.
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    # First few chars of the plaintext, shown in the UI so a user can tell
    # their tokens apart without us keeping the secret.
    prefix = models.CharField(max_length=16)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'surveillance_apitoken'

    def __str__(self):
        return f'{self.name} ({self.prefix}...)'

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at <= timezone.now()


class NotificationLog(models.Model):
    STATUS_TYPES = [
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('rate_limited', 'Rate Limited'),
    ]
    alert_channel = models.ForeignKey(AlertChannel, related_name='notification_logs', on_delete=models.CASCADE)
    incident = models.ForeignKey(Incident, related_name='notification_logs', on_delete=models.CASCADE)
    sent_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_TYPES, default='sent')
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'surveillance_notificationlog'


class Probe(models.Model):
    """A distributed agent capable of running checks."""
    id = models.CharField(max_length=64, primary_key=True, help_text="Stable unique identifier from the probe.")
    organization = models.ForeignKey(Organization, related_name='probes', on_delete=models.CASCADE, null=True, blank=True, help_text="Null if a global public probe.")
    display_name = models.CharField(max_length=255)
    region = models.CharField(max_length=50, db_index=True)
    version = models.CharField(max_length=50, blank=True)
    capabilities = models.JSONField(default=list, help_text="List of supported check types.")
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'surveillance_probe'

    def __str__(self):
        return f"{self.display_name} ({self.region})"


class ProbeToken(models.Model):
    """Revocable credentials for a Probe to authenticate with VectoTrace."""
    probe = models.ForeignKey(Probe, related_name='tokens', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    prefix = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'surveillance_probetoken'

    @property
    def is_valid(self):
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return False
        return True


class ProbeHeartbeat(models.Model):
    """Immutable log of a probe checking in."""
    probe = models.ForeignKey(Probe, related_name='heartbeats', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    queue_utilization = models.FloatField(null=True, blank=True)
    clock_offset_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'surveillance_probeheartbeat'


class ProbeAssignment(models.Model):
    """A monitor assigned to a specific probe to be executed."""
    probe = models.ForeignKey(Probe, related_name='assignments', on_delete=models.CASCADE)
    monitor = models.ForeignKey(Monitor, related_name='probe_assignments', on_delete=models.CASCADE)
    # The UTC time this check is due to be executed
    due_at = models.DateTimeField(db_index=True)
    # When the probe pulled the assignment. Prevents double-dispatch.
    dispatched_at = models.DateTimeField(null=True, blank=True, db_index=True)
    # When the check actually finished and the result was stored.
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = 'surveillance_probeassignment'
        indexes = [
            models.Index(fields=['probe', 'due_at'], name='probe_assignment_due_idx'),
        ]
        # Prevent assigning the exact same monitor tick to the same probe twice
        unique_together = ('probe', 'monitor', 'due_at')

    def __str__(self):
        return f"{self.monitor} -> {self.probe} @ {self.due_at}"


# -----------------------------------------------------------------------------
# Phase 4: On-Call and Escalation
# -----------------------------------------------------------------------------

class OnCallSchedule(models.Model):
    organization = models.ForeignKey(Organization, related_name='schedules', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    time_zone = models.CharField(max_length=64, default='UTC')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'surveillance_oncallschedule'

    def __str__(self):
        return self.name

class EscalationPolicy(models.Model):
    organization = models.ForeignKey(Organization, related_name='escalation_policies', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'surveillance_escalationpolicy'

    def __str__(self):
        return self.name

class EscalationStep(models.Model):
    TARGET_TYPE_CHOICES = [
        ('user', 'User'),
        ('schedule', 'Schedule'),
        ('channel', 'Channel'),
    ]
    policy = models.ForeignKey(EscalationPolicy, related_name='steps', on_delete=models.CASCADE)
    delay_minutes = models.IntegerField(default=0, help_text="Wait time before executing this step.")
    target_type = models.CharField(max_length=20, choices=TARGET_TYPE_CHOICES)
    # Target IDs (could be User ID, Schedule ID, or AlertChannel ID based on target_type)
    target_id = models.IntegerField()
    order = models.IntegerField(default=0)

    class Meta:
        db_table = 'surveillance_escalationstep'
        ordering = ['order']

    def __str__(self):
        return f"{self.policy.name} Step {self.order} (+{self.delay_minutes}m)"


# -----------------------------------------------------------------------------
# Phase 5: SLOs, error budgets, and reporting
# -----------------------------------------------------------------------------

class ServiceLevelObjective(models.Model):
    organization = models.ForeignKey(Organization, related_name='slos', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    # Target percentage, e.g., 99.9 or 99.99
    target_percentage = models.FloatField(default=99.9)
    # Rolling window in days, typically 30, 28, or 7
    window_days = models.IntegerField(default=30)
    # Which monitors are included in this SLO calculation
    monitors = models.ManyToManyField(Monitor, related_name='slos', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'surveillance_servicelevelobjective'

    def __str__(self):
        return f"{self.name} ({self.target_percentage}%)"


# -----------------------------------------------------------------------------
# Phase 6: Status Page Components
# -----------------------------------------------------------------------------

class StatusComponentGroup(models.Model):
    status_page = models.ForeignKey(StatusPage, related_name='component_groups', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    display_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'surveillance_statuscomponentgroup'
        ordering = ['display_order']

    def __str__(self):
        return self.name

class StatusComponent(models.Model):
    STATE_CHOICES = [
        ('operational', 'Operational'),
        ('degraded_performance', 'Degraded Performance'),
        ('partial_outage', 'Partial Outage'),
        ('major_outage', 'Major Outage'),
        ('under_maintenance', 'Under Maintenance'),
    ]
    status_page = models.ForeignKey(StatusPage, related_name='components', on_delete=models.CASCADE)
    group = models.ForeignKey(StatusComponentGroup, related_name='components', null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    state = models.CharField(max_length=50, choices=STATE_CHOICES, default='operational')
    display_order = models.IntegerField(default=0)
    
    # Auto-update state based on linked monitors
    linked_monitors = models.ManyToManyField(Monitor, related_name='linked_components', blank=True)

    class Meta:
        db_table = 'surveillance_statuscomponent'
        ordering = ['display_order']

    def __str__(self):
        return self.name


# -----------------------------------------------------------------------------
# Phase 8: Postmortems
# -----------------------------------------------------------------------------

class Postmortem(models.Model):
    incident = models.OneToOneField(Incident, related_name='postmortem', on_delete=models.CASCADE)
    content = models.TextField(help_text="Markdown content detailing root cause, timeline, and lessons learned.")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'surveillance_postmortem'

    def __str__(self):
        return f"Postmortem for {self.incident.title}"

class CorrectiveAction(models.Model):
    postmortem = models.ForeignKey(Postmortem, related_name='corrective_actions', on_delete=models.CASCADE)
    description = models.TextField()
    assignee = models.ForeignKey(User, related_name='corrective_actions', on_delete=models.SET_NULL, null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'surveillance_correctiveaction'

    def __str__(self):
        return self.description


# -----------------------------------------------------------------------------
# Phase 10: Audit and Governance
# -----------------------------------------------------------------------------

class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('login', 'Login'),
        ('export', 'Data Export'),
    ]
    organization = models.ForeignKey(Organization, related_name='audit_logs', on_delete=models.CASCADE, null=True, blank=True)
    actor = models.ForeignKey(User, related_name='audit_logs', on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=100, null=True, blank=True)
    old_state = models.JSONField(null=True, blank=True)
    new_state = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'surveillance_auditlog'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.actor} performed {self.action} on {self.resource_type} at {self.timestamp}"


# -----------------------------------------------------------------------------
# Phase 11: Extensibility
# -----------------------------------------------------------------------------

class WebhookDelivery(models.Model):
    organization = models.ForeignKey(Organization, related_name='webhook_deliveries', on_delete=models.CASCADE)
    endpoint_url = EncryptedURLField()
    event_type = models.CharField(max_length=100)
    payload = models.JSONField()
    status_code = models.IntegerField(null=True, blank=True)
    response_body = models.TextField(null=True, blank=True)
    success = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'surveillance_webhookdelivery'
        ordering = ['-created_at']

    def __str__(self):
        return f"Webhook Delivery to {self.endpoint_url} ({'Success' if self.success else 'Failed'})"
