"""
Status page subscriber notification.

Subscribers were being stored and verified and then never told anything, which
made the whole sign-up flow decorative. This closes it.

Email was a design-doc non-goal because running mail infrastructure means
deliverability, relays and bounces. That reasoning doesn't apply here: the
operator supplies their own Apprise URL (`mailtos://user:pass@smtp.company.com`
or anything else Apprise speaks), so this project still runs no mail server. If
the operator configures nothing, subscribers with a webhook still get notified
and email subscribers are skipped with a log line rather than a crash.
"""

import logging
import secrets
from urllib.parse import quote

from celery import shared_task
from django.conf import settings

from .apprise_channel import send_via_apprise

logger = logging.getLogger(__name__)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def _email_target(email: str) -> str | None:
    """
    Turn a subscriber's address into an Apprise URL using the operator's
    configured mail transport. Returns None when none is configured.
    """
    base = getattr(settings, 'SUBSCRIBER_EMAIL_URL', '') or ''
    if not base:
        return None
    joiner = '&' if '?' in base else '?'
    return f'{base}{joiner}to={quote(email)}'


def _build_message(incident, event: str, page, unsubscribe_url: str) -> tuple[str, str]:
    """Subscriber-facing copy: plain, no internal identifiers, no jargon."""
    monitor = incident.monitor.name
    if event == 'resolved':
        title = f'Resolved: {incident.title}'
        body = (
            f'The issue affecting {monitor} has been resolved.\n\n'
            f'{incident.title}\n'
            f'Started: {incident.started_at:%Y-%m-%d %H:%M %Z}\n'
            f'Resolved: {incident.resolved_at:%Y-%m-%d %H:%M %Z}\n'
        )
    else:
        title = f'Investigating: {incident.title}'
        body = (
            f'We are investigating an issue affecting {monitor}.\n\n'
            f'{incident.title}\n'
            f'Severity: {incident.severity}\n'
            f'Started: {incident.started_at:%Y-%m-%d %H:%M %Z}\n'
        )

    latest = incident.updates.order_by('-posted_at').first()
    if latest:
        body += f'\nLatest update: {latest.message}\n'

    body += f'\nStatus page: {page.title}\nUnsubscribe: {unsubscribe_url}\n'
    return title, body


@shared_task(ignore_result=True)
def notify_subscribers(incident_id: int, event: str, base_url: str = '') -> None:
    """
    Tell every verified subscriber of every public page that lists the affected
    monitor. A subscriber on two pages showing the same monitor is notified
    once, not twice.
    """
    from .models import Incident, StatusPage, Subscriber

    try:
        incident = Incident.objects.select_related('monitor').get(pk=incident_id)
    except Incident.DoesNotExist:
        logger.warning('notify_subscribers: incident %s is gone.', incident_id)
        return

    pages = StatusPage.objects.filter(
        page_monitors__monitor=incident.monitor, is_public=True,
    ).distinct()
    if not pages:
        return

    base_url = base_url or getattr(settings, 'PUBLIC_BASE_URL', '') or ''
    sent = skipped = 0
    already_notified: set[int] = set()

    for page in pages:
        subscribers = Subscriber.objects.filter(status_page=page, verified=True)

        for sub in subscribers:
            if sub.pk in already_notified:
                continue
            already_notified.add(sub.pk)

            if not sub.unsubscribe_token:
                sub.unsubscribe_token = new_token()
                sub.save(update_fields=['unsubscribe_token'])

            unsubscribe_url = f'{base_url}/api/v1/public/unsubscribe/{sub.unsubscribe_token}/'
            title, body = _build_message(incident, event, page, unsubscribe_url)

            # A webhook subscriber is explicit about where to send; otherwise
            # fall back to the operator's mail transport.
            target = sub.webhook_url or _email_target(sub.email)
            if not target:
                skipped += 1
                continue

            status, error = send_via_apprise(target, title, body)
            if status == 'sent':
                sent += 1
            else:
                logger.warning('Subscriber %s notification failed: %s', sub.pk, error)

    if skipped:
        logger.info(
            'notify_subscribers: skipped %d email subscriber(s) — '
            'set SUBSCRIBER_EMAIL_URL to enable email delivery.', skipped,
        )
    logger.info('notify_subscribers: incident %s (%s) — %d sent.', incident_id, event, sent)
