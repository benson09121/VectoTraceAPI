"""
Alert dispatch: turn an incident event into a Slack / Discord / generic webhook
message, and record every attempt in NotificationLog.

The dedupe rule from the design doc lives in `should_send`, keyed on
(alert_channel, incident) — different channels each notify once for the same
incident, but one channel never notifies twice for it inside the window.
"""

import logging
from datetime import timedelta

import requests
from celery import shared_task
from django.utils import timezone

from .apprise_channel import send_via_apprise
from .net import BlockedTargetError, validate_outbound_url

logger = logging.getLogger(__name__)

DEDUPE_WINDOW = timedelta(minutes=5)
MAX_RETRIES = 3
REQUEST_TIMEOUT_S = 10

STATUS_EMOJI = {'opened': '🔴', 'resolved': '✅'}


# ---------------------------------------------------------------------------
# Payload building
# ---------------------------------------------------------------------------

def build_message(incident, event: str, channel=None) -> str:
    monitor = incident.monitor
    
    custom_msg = (channel.config or {}).get('custom_message') if channel else None
    if custom_msg:
        url = getattr(monitor, 'url', '') or ''
        monitor_type = getattr(monitor, 'type', '') or ''
        return custom_msg.replace('[#service_name#]', monitor.name) \
                         .replace('[#url#]', url) \
                         .replace('[#type#]', monitor_type) \
                         .replace('[#status#]', monitor.last_status) \
                         .replace('[#severity#]', incident.severity) \
                         .replace('[#title#]', incident.title) \
                         .replace('[#event#]', event)

    icon = STATUS_EMOJI.get(event, 'ℹ️')
    if event == 'resolved':
        return (
            f'{icon} *Resolved:* {incident.title}\n'
            f'Monitor: {monitor.name} ({monitor.url})\n'
            f'Duration: {_duration(incident)}'
        )
    return (
        f'{icon} *{incident.severity.upper()}:* {incident.title}\n'
        f'Monitor: {monitor.name} ({monitor.url})\n'
        f'Status: {monitor.last_status}'
    )


def _duration(incident) -> str:
    end = incident.resolved_at or timezone.now()
    minutes = int((end - incident.started_at).total_seconds() // 60)
    return f'{minutes} minute(s)'


def build_payload(channel, incident, event: str) -> dict:
    """Shape the message the way each destination expects."""
    channel_type = channel.type
    text = build_message(incident, event, channel)

    if channel_type == 'slack':
        return {'text': text}
    if channel_type == 'discord':
        # Discord rejects Slack's markdown bold markers.
        return {'content': text.replace('*', '**')}

    if channel_type == 'apprise':
        # Apprise takes a title and a plain body; it renders per destination.
        verb = 'Resolved' if event == 'resolved' else incident.severity.upper()
        return {'title': f'[{verb}] {incident.title}', 'body': text}

    # Generic webhook: structured, so the receiver doesn't parse prose.
    return {
        'event': f'incident.{event}',
        'incident': {
            'id': incident.id,
            'title': incident.title,
            'status': incident.status,
            'severity': incident.severity,
            'started_at': incident.started_at.isoformat(),
            'resolved_at': incident.resolved_at.isoformat() if incident.resolved_at else None,
        },
        'monitor': {
            'id': incident.monitor_id,
            'name': incident.monitor.name,
            'url': incident.monitor.url,
            'last_status': incident.monitor.last_status,
        },
        'message': text,
    }


# ---------------------------------------------------------------------------
# Rate limiting / dedupe
# ---------------------------------------------------------------------------

def should_send(channel, incident) -> tuple[bool, str]:
    """
    Decide whether to attempt delivery. Returns (send?, reason).

    Per the design doc, within the dedupe window:
      sent         -> skip, we already told them
      failed       -> skip, likely permanent (bad URL) — retrying just burns calls
      rate_limited -> retry until MAX_RETRIES, then stop
    """
    from .models import NotificationLog

    since = timezone.now() - DEDUPE_WINDOW
    recent = NotificationLog.objects.filter(
        alert_channel=channel, incident=incident, sent_at__gte=since
    )

    if recent.filter(status='sent').exists():
        return False, 'already notified'
    if recent.filter(status='failed').exists():
        return False, 'previous delivery failed permanently'
    if recent.filter(status='rate_limited').count() >= MAX_RETRIES:
        return False, 'max retries reached'
    return True, ''


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def post_to_channel(channel, payload) -> tuple[str, str | None]:
    """
    POST the payload. Returns (status, error_message) where status is one of
    'sent' | 'failed' | 'rate_limited'.
    """
    url = (channel.config or {}).get('url')
    if not url:
        return 'failed', 'Channel config has no "url".'

    # Apprise owns its own transport, URL parsing and validation.
    if channel.type == 'apprise':
        title, body = payload.get('title', 'VectoTrace'), payload.get('body', '')
        return send_via_apprise(url, title, body)

    # Re-checked here, not just at save time: DNS can change underneath a
    # stored webhook URL, and this response is reported back to the caller.
    try:
        validate_outbound_url(url)
    except BlockedTargetError as exc:
        return 'failed', str(exc)

    try:
        # Redirects off: a 30x could otherwise walk this request into the
        # internal network after validation has already passed.
        resp = requests.post(
            url, json=payload, timeout=REQUEST_TIMEOUT_S, allow_redirects=False
        )
    except requests.exceptions.RequestException as exc:
        # Network-level problem: treat as retryable rather than permanent.
        return 'rate_limited', f'Request error: {type(exc).__name__}'

    if resp.status_code == 429:
        return 'rate_limited', 'Destination returned 429.'
    if 500 <= resp.status_code < 600:
        return 'rate_limited', f'Destination returned {resp.status_code}.'
    if not (200 <= resp.status_code < 300):
        # Status only. Echoing resp.text turned this into an SSRF that could
        # read back 200 chars of any internal endpoint's response.
        return 'failed', f'Destination returned {resp.status_code}.'
    return 'sent', None


@shared_task(ignore_result=True)
def dispatch_incident_alert(incident_id: int, event: str) -> None:
    """
    Fan an incident event out to every enabled channel in the org.
    `event` is 'opened' or 'resolved'.
    """
    from .models import Incident, AlertChannel, NotificationLog

    try:
        incident = Incident.objects.select_related('monitor', 'organization').get(pk=incident_id)
    except Incident.DoesNotExist:
        logger.warning('dispatch_incident_alert: incident %s is gone.', incident_id)
        return

    channels = AlertChannel.objects.filter(
        organization=incident.organization, is_enabled=True
    )

    for channel in channels:
        allowed, reason = should_send(channel, incident)
        if not allowed:
            logger.info(
                'Skipping channel %s for incident %s: %s', channel.pk, incident_id, reason
            )
            continue

        payload = build_payload(channel, incident, event)
        result, error = post_to_channel(channel, payload)

        NotificationLog.objects.create(
            alert_channel=channel,
            incident=incident,
            status=result,
            error_message=error,
        )
        logger.info(
            'Alert for incident %s via channel %s: %s', incident_id, channel.pk, result
        )


def send_test_message(channel) -> tuple[str, str | None]:
    """Used by the 'send test' endpoint. Deliberately bypasses dedupe."""
    payload = build_payload(
        channel,
        _TestIncident(),
        'opened',
    )
    if channel.type not in ('slack', 'discord'):
        payload['event'] = 'test'
    return post_to_channel(channel, payload)


class _TestIncident:
    """Stand-in so the test message renders through the same code path."""
    id = 0
    monitor_id = 0
    title = 'Test alert from VectoTrace'
    status = 'investigating'
    severity = 'minor'
    started_at = resolved_at = None

    def __init__(self):
        self.started_at = timezone.now()
        self.monitor = type('M', (), {
            'name': 'Test Monitor',
            'url': 'https://example.com',
            'last_status': 'up',
            'type': 'http',
        })()
