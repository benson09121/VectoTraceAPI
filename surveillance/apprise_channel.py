"""
Apprise-backed alert delivery.

Uptime Kuma hand-wrote ~96 notification providers because it is a Node project.
This is Python, so one BSD-licensed dependency covers 200+ schemas — Telegram,
Matrix, ntfy, Gotify, Teams, Signal, Pushover, email, SMS gateways and the rest.
Writing 96 integrations to match would be strictly worse code.

Security note: an Apprise URL is still an outbound request target. Most schemas
resolve to a fixed vendor host, but the generic ones (`json://`, `xml://`,
`form://`) take an arbitrary host and are exactly as dangerous as a raw
webhook — so those get the same SSRF validation as everything else.
"""

import logging
from urllib.parse import urlparse

from .net import BlockedTargetError, validate_outbound_url

logger = logging.getLogger(__name__)

# Apprise schemas that POST to a host the user chooses, rather than to a fixed
# vendor endpoint. These are user-controlled request targets.
GENERIC_HOST_SCHEMES = {
    'json': 'http', 'jsons': 'https',
    'xml': 'http', 'xmls': 'https',
    'form': 'http', 'forms': 'https',
}


def available_schemas() -> list[str]:
    """Every notification schema this install supports."""
    from apprise.plugins import N_MGR
    return sorted(N_MGR.schemas())


def validate_apprise_url(url: str) -> str:
    """
    Check Apprise can parse the URL, and that it isn't pointed at our own
    network. Raises BlockedTargetError with a readable message.
    """
    import apprise

    obj = apprise.Apprise()
    if not obj.add(url):
        raise BlockedTargetError(
            'Apprise does not recognise this URL. Expected something like '
            'tgram://bottoken/chatid, discord://webhook_id/token, or '
            'ntfy://topic — see the Apprise documentation for the full list.'
        )

    scheme = (urlparse(url).scheme or '').lower()
    if scheme in GENERIC_HOST_SCHEMES:
        parsed = urlparse(url)
        if parsed.hostname:
            port = f':{parsed.port}' if parsed.port else ''
            equivalent = f'{GENERIC_HOST_SCHEMES[scheme]}://{parsed.hostname}{port}'
            # Raises BlockedTargetError for loopback/private/link-local.
            validate_outbound_url(equivalent, allow_unresolvable=True)

    return url


def send_via_apprise(url: str, title: str, body: str) -> tuple[str, str | None]:
    """
    Deliver one notification.

    Returns (status, error) using the same vocabulary as `post_to_channel`:
    'sent' | 'failed' | 'rate_limited'.
    """
    import apprise

    try:
        validate_apprise_url(url)
    except BlockedTargetError as exc:
        return 'failed', str(exc)

    obj = apprise.Apprise()
    if not obj.add(url):
        return 'failed', 'Apprise could not parse the channel URL.'

    try:
        ok = obj.notify(title=title, body=body)
    except Exception as exc:
        # Network-level trouble: retryable, same as a webhook connection error.
        logger.warning('Apprise delivery raised: %s', exc)
        return 'rate_limited', f'Delivery error: {type(exc).__name__}'

    if ok:
        return 'sent', None
    # Apprise returns False for any non-success without distinguishing the
    # cause, so treat it as retryable rather than permanently failed.
    return 'rate_limited', 'Apprise reported delivery failure.'
