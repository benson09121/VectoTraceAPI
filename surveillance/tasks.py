"""
Celery tasks for the surveillance (monitoring) system.

Tasks:
- run_check(monitor_id, region): Execute one HTTP check, write ApiLog, evaluate state.
- evaluate_monitor_state(monitor, check_passed): Failure-detection + incident lifecycle.
- auto_open_incident(monitor): Open a new incident for a monitor that just went down.
- auto_resolve_incident(monitor): Resolve the open incident when monitor recovers.
- schedule_all_monitors(): Periodic beat task — fans out run_check for every active monitor.
"""

import logging
import math
import random
import socket
import time
import ssl
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
from celery import shared_task
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone as django_timezone

from .net import BlockedTargetError, validate_outbound_url

from .events import publish_monitor_event

logger = logging.getLogger(__name__)


def in_maintenance(monitor) -> bool:
    """
    Is this monitor inside an open maintenance window that suppresses alerts?

    Checked at notify time rather than check time on purpose: the check still
    runs and is still recorded, so the history stays honest — we simply don't
    page anyone about planned work.
    """
    from .models import MaintenanceWindow

    now = django_timezone.now()
    windows = MaintenanceWindow.objects.filter(
        organization_id=monitor.organization_id,
        suppress_alerts=True,
        starts_at__lte=now,
        ends_at__gte=now,
    )
    return any(w.covers(monitor) for w in windows)


def notify_incident(incident_id: int, event: str) -> None:
    """
    Queue alert fan-out for an incident event, plus status page subscribers.

    Falls back to running inline if no broker is reachable, so a missing worker
    silently drops nobody's outage notification.
    """
    from .alerts import dispatch_incident_alert
    from .models import Incident
    from .subscribers import notify_subscribers

    incident = Incident.objects.select_related('monitor').filter(pk=incident_id).first()
    if incident and in_maintenance(incident.monitor):
        logger.info(
            'Monitor %s is in a maintenance window — suppressing %s alerts.',
            incident.monitor_id, event,
        )
        return

    for task in (dispatch_incident_alert, notify_subscribers):
        try:
            task.delay(incident_id, event)
        except Exception:
            logger.warning('Broker unavailable — running %s inline.', task.name, exc_info=True)
            task(incident_id, event)

FAILURE_THRESHOLD = getattr(settings, 'FAILURE_THRESHOLD', 3)
RECOVERY_THRESHOLD = getattr(settings, 'RECOVERY_THRESHOLD', 5)

# Upper bound on dispatch jitter. Kept below the minimum interval so a monitor
# at the 20s floor still gets checked roughly on time.
JITTER_MAX_SECONDS = 5

# One pooled Session for all outbound checks: connection and TLS reuse. Every
# check used to open a fresh socket and redo the handshake, which cost 2-3
# extra round trips and inflated the response times we report as the user's.
_session = requests.Session()
_session.headers['User-Agent'] = 'VectoTrace/1.0 (+uptime monitor)'
_adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=200)
_session.mount('http://', _adapter)
_session.mount('https://', _adapter)


# ---------------------------------------------------------------------------
# Check execution
# ---------------------------------------------------------------------------

def expected_codes(monitor) -> list[int]:
    """Normalize expected_status_codes to a list (legacy rows stored a bare int)."""
    raw = monitor.expected_status_codes
    if isinstance(raw, int):
        return [raw]
    return [int(c) for c in (raw or [200])]


@shared_task(bind=True, max_retries=0, ignore_result=True)
def run_check(self, monitor_id: int, region: str = 'default', checked_at: str | None = None) -> None:
    """
    Execute an HTTP check against the monitor's URL, write an ApiLog record,
    and trigger failure/recovery evaluation.

    `checked_at` (ISO-8601) is the idempotency key: a retry of the same
    dispatched check carries the same value and is rejected by the unique
    constraint on (monitor, checked_at, region) instead of double-counting.
    """
    from surveillance.models import Monitor, ApiLog  # local import avoids circular

    try:
        monitor = Monitor.objects.get(pk=monitor_id, status='active')
    except Monitor.DoesNotExist:
        logger.warning('Monitor %s not found or not active — skipping check.', monitor_id)
        return

    check_ts = datetime.fromisoformat(checked_at) if checked_at else django_timezone.now()

    check_passed = False
    status_code = None
    response_time_ms = None
    error_message = None
    ssl_valid = None
    ssl_expires_at = None
    meta = {}
    # Must exist before the try: a blocked target, timeout or connection error
    # skips the assignment below, and the log row is still written.
    timings: dict = {}

    try:
        # One probe per monitor type; every probe returns the same shape, so
        # everything downstream (state machine, incidents, alerts) is identical
        # regardless of what was checked.
        from .probes import PROBES

        probe = PROBES.get(monitor.type, PROBES['http'])
        result = probe(monitor, _session)

        check_passed = result.passed
        status_code = result.status_code
        response_time_ms = result.response_time_ms
        error_message = result.error_message
        ssl_valid = result.ssl_valid
        ssl_expires_at = result.ssl_expires_at
        timings = result.timings or {}
        meta = result.meta or {}

    except BlockedTargetError as exc:
        # Refused before any packet left the host.
        error_message = f'Blocked target: {exc}'
        logger.warning('Monitor %s blocked: %s', monitor_id, exc)
    except requests.exceptions.Timeout:
        error_message = 'Request timed out.'
    except requests.exceptions.ConnectionError as exc:
        error_message = f'Connection error: {exc}'
    except Exception as exc:
        error_message = f'Unexpected error: {exc}'
        logger.exception('Unexpected error during check for monitor %s', monitor_id)

    # Write log record. A duplicate (same monitor/time/region) means this exact
    # check was already recorded by another worker — drop it rather than let it
    # move the failure counter twice.
    try:
        with transaction.atomic():
            ApiLog.objects.create(
                monitor=monitor,
                region=region,
                checked_at=check_ts,
                status_code=status_code,
                response_time_ms=response_time_ms,
                dns_ms=timings.get('dns_ms'),
                connect_ms=timings.get('connect_ms'),
                tls_ms=timings.get('tls_ms'),
                ttfb_ms=timings.get('ttfb_ms'),
                result='success' if check_passed else 'failure',
                error_message=error_message,
                ssl_valid=ssl_valid,
                ssl_expires_at=ssl_expires_at,
                meta=meta,
            )
    except IntegrityError:
        logger.info(
            'Duplicate check for monitor %s @ %s [%s] — already recorded.',
            monitor_id, check_ts, region,
        )
        return

    # Keep the denormalised column honest even when a check is dispatched
    # outside the scheduler (manual run, retry), so the dispatcher's due-query
    # never re-fires a monitor that was just checked.
    Monitor.objects.filter(pk=monitor_id).update(last_checked_at=check_ts)

    # Update failure counters and open/close incidents
    evaluate_monitor_state(monitor_id, check_passed, response_time_ms)

    # Push the result to any dashboard watching this org.
    monitor.refresh_from_db(fields=['last_status', 'consecutive_failures'])
    publish_monitor_event(
        monitor, 'check',
        result='success' if check_passed else 'failure',
        status_code=status_code,
        response_time_ms=response_time_ms,
        region=region,
        meta=meta,
    )


MAX_REDIRECT_HOPS = 5


def _request_with_guarded_redirects(
    method: str, url: str, headers: dict, json_body, timeout_s: float,
    follow_redirects: bool,
):
    """
    Perform the check request, validating the target before every hop.

    requests' own redirect handling is disabled: letting it follow a 30x would
    mean the *first* URL is validated and the final one — chosen by whoever
    controls the target — is not. That is the standard way an SSRF filter gets
    walked past, so each Location is re-validated before it is followed.
    """
    timings = {'dns_ms': None, 'connect_ms': None, 'tls_ms': None, 'ttfb_ms': None}

    for _ in range(MAX_REDIRECT_HOPS):
        # The resolve is required for SSRF safety anyway, so timing it gives us
        # the DNS phase for free rather than costing an extra lookup.
        dns_start = time.perf_counter()
        validate_outbound_url(url)
        timings['dns_ms'] = int((time.perf_counter() - dns_start) * 1000)

        # `requests`' timeout applies per phase, so a bare number lets a check
        # run for ~2x the configured budget. Split it explicitly: fail fast on
        # connect, give the body the remainder.
        #
        # stream=True keeps the socket attached to the response so the TLS
        # certificate can be read from THIS connection. Without it the
        # connection returns to the pool first, which is why the old code
        # opened a second socket for every HTTPS check.
        wall_start = time.perf_counter()
        resp = _session.request(
            method=method, url=url, headers=headers, json=json_body,
            timeout=(min(10.0, timeout_s), timeout_s), allow_redirects=False,
            stream=True,
        )
        wall_ms = int((time.perf_counter() - wall_start) * 1000)

        # elapsed is time-to-headers. Whatever the wall clock spent beyond that
        # was setup: socket connect plus, on https, the TLS handshake. A pooled
        # connection skips both, so this reads ~0 on reuse — which is correct.
        timings['ttfb_ms'] = int(resp.elapsed.total_seconds() * 1000)
        setup_ms = max(0, wall_ms - timings['ttfb_ms'])
        if url.startswith('https://'):
            timings['tls_ms'] = setup_ms
        else:
            timings['connect_ms'] = setup_ms

        if not (follow_redirects and resp.is_redirect):
            resp.vt_timings = timings
            return resp

        location = resp.headers.get('Location')
        if not location:
            return resp
        # Relative Locations are resolved against the URL we just fetched.
        url = urllib.parse.urljoin(url, location)

    raise BlockedTargetError(f'Exceeded {MAX_REDIRECT_HOPS} redirects.')


def _peer_cert_from(resp):
    """
    Read the peer certificate off a live streamed response.

    Returns (ssl_valid, expires_at). Only works while the response is still
    streaming — once the body is drained the connection goes back to the pool
    and the socket is gone, which is exactly why `stream=True` is used.
    """
    conn = getattr(resp.raw, 'connection', None) or getattr(resp.raw, '_connection', None)
    sock = getattr(conn, 'sock', None) if conn else None
    if sock is None:
        return None, None

    try:
        cert = sock.getpeercert()
    except Exception:
        return False, None

    if not cert:
        return None, None

    expires_str = cert.get('notAfter')
    expires_at = None
    if expires_str:
        try:
            expires_at = datetime.strptime(
                expires_str, '%b %d %H:%M:%S %Y %Z'
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    # Python verified the chain during the handshake; an invalid cert would
    # have raised an SSLError before we ever got a response object.
    return True, expires_at


def _check_ssl(url: str):
    """Return (ssl_valid: bool, expires_at: datetime | None)."""
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname
        port = parsed.port or 443
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(socket.create_connection((hostname, port), timeout=5), server_hostname=hostname) as sock:
            cert = sock.getpeercert()
            expires_str = cert.get('notAfter')
            expires_at = None
            if expires_str:
                expires_at = datetime.strptime(expires_str, '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
            return True, expires_at
    except Exception:
        return False, None


# ---------------------------------------------------------------------------
# Failure detection algorithm
# ---------------------------------------------------------------------------

def evaluate_monitor_state(
    monitor_id: int, check_passed: bool, response_time_ms: int | None = None,
) -> None:
    """
    Core failure-detection + recovery algorithm.

    State machine:
    - consecutive_failures > 0  → counting failures
    - consecutive_failures <= 0 → counting recoveries (negative = success run since going down)

    Rules:
    - 3 consecutive failures  → set last_status='down', open incident
    - 5 consecutive successes (while status is 'down') → set last_status='up', resolve incident
    - 1 success while up → reset failure counter to 0
    - a passing but slow check → 'degraded' (reachable, but not healthy)

    'degraded' is deliberately NOT treated as down: the site answers correctly,
    it is just slow, so it must not start the recovery counter or hold an
    incident open. It exists to stop a crawling service reading as fully "up".
    """
    from surveillance.models import Monitor

    with transaction.atomic():
        # Use select_for_update to prevent race conditions
        monitor = Monitor.objects.select_for_update().get(pk=monitor_id)

        previous_status = monitor.last_status
        currently_down = previous_status == 'down'

        # Healthy-but-slow, decided per check.
        healthy_status = 'up'
        if (
            check_passed
            and monitor.degraded_threshold_ms
            and response_time_ms is not None
            and response_time_ms > monitor.degraded_threshold_ms
        ):
            healthy_status = 'degraded'

        if check_passed:
            if currently_down:
                # Count consecutive successes towards recovery (use negative counter)
                monitor.consecutive_failures = min(monitor.consecutive_failures - 1, -1)

                if abs(monitor.consecutive_failures) >= RECOVERY_THRESHOLD:
                    # Recovery achieved
                    logger.info('Monitor %s recovered after %d successes.', monitor_id, RECOVERY_THRESHOLD)
                    monitor.last_status = healthy_status
                    monitor.consecutive_failures = 0
                    monitor.save(update_fields=['last_status', 'consecutive_failures', 'updated_at'])
                    auto_resolve_incident(monitor)
                else:
                    monitor.save(update_fields=['consecutive_failures', 'updated_at'])
            else:
                # Up or degraded: reset any partial failure run, and re-evaluate
                # whether this check was fast enough to still count as healthy.
                fields = ['updated_at']
                if monitor.consecutive_failures != 0:
                    monitor.consecutive_failures = 0
                    fields.append('consecutive_failures')
                if monitor.last_status != healthy_status:
                    monitor.last_status = healthy_status
                    fields.append('last_status')
                if len(fields) > 1:
                    monitor.save(update_fields=fields)
        else:
            # Failed check
            monitor.consecutive_failures = max(monitor.consecutive_failures + 1, 1)

            if monitor.consecutive_failures >= FAILURE_THRESHOLD and previous_status != 'down':
                logger.warning('Monitor %s reached failure threshold — marking DOWN.', monitor_id)
                monitor.last_status = 'down'
                monitor.save(update_fields=['last_status', 'consecutive_failures', 'updated_at'])
                auto_open_incident(monitor)
            else:
                monitor.save(update_fields=['consecutive_failures', 'updated_at'])


# ---------------------------------------------------------------------------
# Incident lifecycle
# ---------------------------------------------------------------------------

def auto_open_incident(monitor) -> None:
    """Open a new 'investigating' incident for a monitor that just went down."""
    from surveillance.models import Incident, IncidentUpdate

    # Guard: don't open if there's already an open incident
    open_exists = Incident.objects.filter(
        monitor=monitor,
        resolved_at__isnull=True,
    ).exists()

    if open_exists:
        logger.debug('Monitor %s already has an open incident — skipping.', monitor.pk)
        return

    # Use the monitor's creator as the system actor for auto-created incidents.
    # The partial unique index is the real guard: if another worker opened an
    # incident between the check above and this insert, the DB rejects ours.
    try:
        with transaction.atomic():
            incident = Incident.objects.create(
                organization=monitor.organization,
                monitor=monitor,
                title=f'[Auto] {monitor.name} is DOWN',
                status='investigating',
                severity='major',
                created_by=monitor.created_by,
            )
    except IntegrityError:
        logger.info('Concurrent open incident for monitor %s — skipping.', monitor.pk)
        return

    IncidentUpdate.objects.create(
        incident=incident,
        status='investigating',
        message=(
            f'Automatic incident opened after {FAILURE_THRESHOLD} consecutive '
            f'failed checks for monitor "{monitor.name}".'
        ),
        posted_by=monitor.created_by,
    )
    logger.info('Auto-opened incident %s for monitor %s.', incident.pk, monitor.pk)
    notify_incident(incident.pk, 'opened')
    publish_monitor_event(
        monitor, 'incident_opened',
        incident_id=incident.pk, title=incident.title, severity=incident.severity,
    )


def auto_resolve_incident(monitor) -> None:
    """Resolve the open incident for a monitor that just recovered."""
    from surveillance.models import Incident, IncidentUpdate

    open_incident = Incident.objects.filter(
        monitor=monitor,
        resolved_at__isnull=True,
    ).order_by('-started_at').first()

    if not open_incident:
        return

    now = django_timezone.now()
    open_incident.status = 'resolved'
    open_incident.resolved_at = now
    open_incident.save(update_fields=['status', 'resolved_at'])

    IncidentUpdate.objects.create(
        incident=open_incident,
        status='resolved',
        message=(
            f'Automatic resolution after {RECOVERY_THRESHOLD} consecutive '
            f'successful checks for monitor "{monitor.name}".'
        ),
        posted_by=monitor.created_by,
    )
    logger.info('Auto-resolved incident %s for monitor %s.', open_incident.pk, monitor.pk)
    notify_incident(open_incident.pk, 'resolved')
    publish_monitor_event(
        monitor, 'incident_resolved',
        incident_id=open_incident.pk, title=open_incident.title,
    )


# ---------------------------------------------------------------------------
# Beat scheduler task
# ---------------------------------------------------------------------------

@shared_task(ignore_result=True)
def schedule_all_monitors() -> None:
    """
    Celery Beat periodic task.
    Dispatches run_check for every active (non-archived, non-paused) monitor.
    Each monitor defines its own interval; Beat calls this task frequently
    and we filter by next-due time based on last check.
    """
    from surveillance.models import Monitor

    now = django_timezone.now()

    # One indexed query finds everything due. This used to run a
    # MAX(checked_at) aggregate per monitor per tick — an N+1 that cost 1,000
    # queries every tick at 1,000 monitors. `last_checked_at` is denormalised
    # onto Monitor precisely so this comparison can happen in the database.
    due = Monitor.objects.filter(
        status='active',
        deleted_at__isnull=True,
    ).filter(
        Q(last_checked_at__isnull=True)
        | Q(last_checked_at__lte=now - timedelta(seconds=1) * F('interval'))
    ).values_list('pk', flat=True)

    region = getattr(settings, 'INSTANCE_REGION', 'default')
    dispatched = 0

    for monitor_id in due:
        # Claim the monitor before queueing. The conditional update is atomic,
        # so if two beats overlap only one of them wins the row and the check
        # is queued once. Without this a slow tick double-dispatches.
        claimed = Monitor.objects.filter(
            pk=monitor_id,
        ).filter(
            Q(last_checked_at__isnull=True)
            | Q(last_checked_at__lte=now - timedelta(seconds=1) * F('interval'))
        ).update(last_checked_at=now)

        if not claimed:
            continue

        # Spread dispatch across the interval instead of firing every due
        # monitor in the same instant. Without jitter, load arrives as a spike
        # each tick rather than a smooth rate.
        countdown = random.uniform(0, min(JITTER_MAX_SECONDS, 5))
        run_check.apply_async(
            args=(monitor_id, region, now.isoformat()),
            countdown=countdown,
        )
        dispatched += 1

    if dispatched:
        logger.info('schedule_all_monitors: dispatched %d check task(s).', dispatched)


# ---------------------------------------------------------------------------
# SSL certificate expiry
# ---------------------------------------------------------------------------

# Days-until-expiry -> incident severity. Checked most-urgent-first.
SSL_SEVERITY_THRESHOLDS = [
    (0, 'critical'),   # already expired
    (7, 'major'),
    (30, 'minor'),
]


def ssl_severity_for(days_left: int) -> str | None:
    """Return the severity an expiry this close warrants, or None if it's fine."""
    for threshold, severity in SSL_SEVERITY_THRESHOLDS:
        if days_left <= threshold:
            return severity
    return None


@shared_task(ignore_result=True)
def check_ssl_expiry() -> None:
    """
    Daily sweep: open (or escalate) an incident for certificates nearing expiry.

    Uses the newest recorded ssl_expires_at per monitor rather than re-dialling
    every host — run_check already captured it on the last https check.
    """
    from surveillance.models import Monitor, ApiLog, Incident, IncidentUpdate

    now = django_timezone.now()
    opened = escalated = 0

    monitors = Monitor.objects.filter(status='active', deleted_at__isnull=True)

    for monitor in monitors:
        latest = (
            ApiLog.objects
            .filter(monitor=monitor, ssl_expires_at__isnull=False)
            .order_by('-checked_at')
            .first()
        )
        if latest is None:
            continue

        days_left = (latest.ssl_expires_at - now).days
        severity = ssl_severity_for(days_left)
        if severity is None:
            continue

        item_name = 'Domain' if monitor.type == 'domain' else 'SSL certificate'
        
        title = f'{item_name} expiring soon for {monitor.name}'
        message = (
            f'{item_name} for {monitor.url or monitor.name} has already expired.'
            if days_left <= 0
            else f'{item_name} for {monitor.url or monitor.name} expires in {days_left} day(s).'
        )

        existing = Incident.objects.filter(
            monitor=monitor, title=title, resolved_at__isnull=True
        ).first()

        if existing is None:
            # A down-incident may already hold the one-open-incident slot for
            # this monitor; the cert warning can wait until that clears.
            try:
                with transaction.atomic():
                    incident = Incident.objects.create(
                        organization=monitor.organization,
                        monitor=monitor,
                        title=title,
                        status='investigating',
                        severity=severity,
                        created_by=monitor.created_by,
                    )
            except IntegrityError:
                logger.info(
                    'Monitor %s already has an open incident — SSL warning deferred.',
                    monitor.pk,
                )
                continue

            IncidentUpdate.objects.create(
                incident=incident, status='investigating',
                message=message, posted_by=monitor.created_by,
            )
            opened += 1

        elif existing.severity != severity:
            # Expiry only ever gets closer, so this is always an escalation.
            existing.severity = severity
            existing.save(update_fields=['severity'])
            IncidentUpdate.objects.create(
                incident=existing, status=existing.status,
                message=f'Escalated to {severity}. {message}',
                posted_by=monitor.created_by,
            )
            escalated += 1

    logger.info('check_ssl_expiry: opened %d, escalated %d.', opened, escalated)


# ---------------------------------------------------------------------------
# Retention and rollups
# ---------------------------------------------------------------------------

RAW_RETENTION_DAYS = getattr(settings, 'RAW_CHECK_RETENTION_DAYS', 90)


def _percentile(sorted_values: list[int], pct: float) -> int | None:
    """
    Nearest-rank percentile: the smallest value at or below which `pct` of the
    series falls. No numpy for three numbers.
    """
    if not sorted_values:
        return None
    rank = math.ceil(pct / 100 * len(sorted_values))
    return sorted_values[max(0, min(len(sorted_values) - 1, rank - 1))]


@shared_task(ignore_result=True)
def rollup_hourly_stats(hours_back: int = 3) -> None:
    """
    Aggregate raw checks into MonitorHourlyStat.

    Recomputes the last few hours rather than only the previous one, so a late
    or retried check still lands in its bucket. Upserts, so running it twice
    changes nothing.
    """
    from surveillance.models import ApiLog, MonitorHourlyStat

    now = django_timezone.now()
    start = (now - timedelta(hours=hours_back)).replace(minute=0, second=0, microsecond=0)

    logs = (
        ApiLog.objects
        .filter(checked_at__gte=start)
        .values('monitor_id', 'checked_at', 'result', 'response_time_ms')
        .order_by('monitor_id', 'checked_at')
    )

    # Bucket in Python: the row count here is bounded by hours_back, and this
    # keeps percentile logic identical across database backends.
    buckets: dict[tuple[int, datetime], list] = {}
    for row in logs.iterator(chunk_size=2000):
        hour = row['checked_at'].replace(minute=0, second=0, microsecond=0)
        buckets.setdefault((row['monitor_id'], hour), []).append(row)

    written = 0
    for (monitor_id, hour), rows in buckets.items():
        times = sorted(r['response_time_ms'] for r in rows if r['response_time_ms'] is not None)
        failed = sum(1 for r in rows if r['result'] == 'failure')

        MonitorHourlyStat.objects.update_or_create(
            monitor_id=monitor_id, hour=hour,
            defaults={
                'total_checks': len(rows),
                'failed_checks': failed,
                'degraded_checks': 0,
                'avg_response_time_ms': (sum(times) / len(times)) if times else None,
                'min_response_time_ms': times[0] if times else None,
                'max_response_time_ms': times[-1] if times else None,
                'p50_response_time_ms': _percentile(times, 50),
                'p95_response_time_ms': _percentile(times, 95),
                'p99_response_time_ms': _percentile(times, 99),
            },
        )
        written += 1

    logger.info('rollup_hourly_stats: wrote %d bucket(s).', written)


@shared_task(ignore_result=True)
def purge_old_checks() -> None:
    """
    Delete raw checks past the retention window.

    Safe because the hourly rollups keep the history the uptime endpoints and
    status pages actually read. Without this, api_logs grows forever — 1,000
    monitors at 60s is 1.44 million rows a day.
    """
    from surveillance.models import ApiLog, MonitorHourlyStat

    now = django_timezone.now()
    cutoff = now - timedelta(days=RAW_RETENTION_DAYS)

    # Roll up everything still unaggregated before deleting it, or the history
    # vanishes with the rows. The window must reach the OLDEST row, not just
    # the retention cutoff — rows being deleted are by definition older than
    # the cutoff, so a retention-sized window would miss every one of them.
    oldest = ApiLog.objects.order_by('checked_at').values_list('checked_at', flat=True).first()
    if oldest:
        hours_to_cover = math.ceil((now - oldest).total_seconds() / 3600) + 1
        rollup_hourly_stats(hours_back=hours_to_cover)

    deleted, _ = ApiLog.objects.filter(checked_at__lt=cutoff).delete()

    # Rollups are tiny; keep them far longer than the raw rows.
    stat_cutoff = django_timezone.now() - timedelta(days=RAW_RETENTION_DAYS * 4)
    MonitorHourlyStat.objects.filter(hour__lt=stat_cutoff).delete()

    logger.info('purge_old_checks: deleted %d raw check(s) older than %d days.',
                deleted, RAW_RETENTION_DAYS)


@shared_task(ignore_result=True)
def watchdog() -> None:
    """
    Dead man's switch for the engine itself.

    If beat or the worker dies, nothing gets checked and nothing complains —
    the dashboard just keeps showing the last known state, which reads as "all
    green". This notices that active monitors have gone unchecked for far
    longer than their interval and says so loudly.
    """
    from surveillance.models import Monitor

    now = django_timezone.now()
    stalled = Monitor.objects.filter(
        status='active',
        deleted_at__isnull=True,
        last_checked_at__isnull=False,
        last_checked_at__lt=now - timedelta(seconds=1) * F('interval') * 10,
    ).count()

    if stalled:
        logger.error(
            'WATCHDOG: %d active monitor(s) have not been checked in 10x their '
            'interval. Is the Celery worker running?', stalled,
        )
    return None

# ---------------------------------------------------------------------------
# Phase 4: Escalations
# ---------------------------------------------------------------------------

@shared_task(ignore_result=True)
def evaluate_escalations() -> None:
    """
    Evaluates open, unacknowledged incidents and triggers escalation steps.
    """
    from surveillance.models import Incident
    
    now = django_timezone.now()
    incidents = Incident.objects.filter(
        resolved_at__isnull=True,
        acknowledged_at__isnull=True,
        monitor__escalation_policy__isnull=False
    ).select_related('monitor__escalation_policy')

    executed = 0
    for incident in incidents:
        minutes_open = (now - incident.started_at).total_seconds() / 60
        policy = incident.monitor.escalation_policy
        
        # Here we would normally join against an execution log to ensure we only
        # fire a step once. For MVP, we just identify that a step *should* fire.
        steps = policy.steps.filter(delay_minutes__lte=minutes_open)
        if steps.exists():
            logger.info("Incident %s has %d escalation steps due.", incident.pk, steps.count())
            executed += 1
            
    if executed:
        logger.info('evaluate_escalations: Processed %d incident(s).', executed)

# ---------------------------------------------------------------------------
# Phase 5: SLO Compliance Rollup
# ---------------------------------------------------------------------------

@shared_task(ignore_result=True)
def calculate_slo_compliance() -> None:
    """
    Rolls up MonitorHourlyStat data to determine SLO compliance percentages.
    """
    from surveillance.models import ServiceLevelObjective, MonitorHourlyStat
    from django.db.models import Sum

    now = django_timezone.now()
    slos = ServiceLevelObjective.objects.all()
    
    calculated = 0
    for slo in slos:
        cutoff = now - timedelta(days=slo.window_days)
        # Sum all checks across all monitors in this SLO for the rolling window
        stats = MonitorHourlyStat.objects.filter(
            monitor__in=slo.monitors.all(),
            hour__gte=cutoff
        ).aggregate(
            total=Sum('total_checks'),
            failed=Sum('failed_checks')
        )
        
        total = stats['total'] or 0
        failed = stats['failed'] or 0
        if total > 0:
            compliance = ((total - failed) / total) * 100
            # We would normally save this compliance to a SLOHistory model.
            logger.info("SLO '%s' compliance is %.3f%% (Target: %.3f%%)", slo.name, compliance, slo.target_percentage)
            calculated += 1

    if calculated:
        logger.info('calculate_slo_compliance: Processed %d SLO(s).', calculated)

