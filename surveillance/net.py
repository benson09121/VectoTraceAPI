"""
Outbound request safety (SSRF containment).

Fetching URLs the user supplies is this product's entire purpose, so this can
never be an allowlist. What it can be is a hard floor: resolve the hostname and
refuse to connect to loopback, private, link-local, or otherwise internal
addresses — the ones an attacker wants and a monitoring user never does.

Self-hosters monitoring their own LAN are a real use case, so the floor is
lifted by an explicit operator setting rather than by DEBUG. Tying it to DEBUG
meant the protection silently vanished in development and, since DEBUG was
hardcoded on, everywhere else too.
"""

import ipaddress
import socket
from urllib.parse import urlparse

from django.conf import settings

# Ranges an outbound check must never reach. Covers the cloud metadata endpoint
# (169.254.169.254 lives in link-local), RFC1918, CGNAT, and the IPv6
# equivalents including IPv4-mapped forms like ::ffff:127.0.0.1.
BLOCKED_NETWORKS = [
    ipaddress.ip_network('0.0.0.0/8'),        # "this" network
    ipaddress.ip_network('10.0.0.0/8'),       # private
    ipaddress.ip_network('100.64.0.0/10'),    # CGNAT
    ipaddress.ip_network('127.0.0.0/8'),      # loopback
    ipaddress.ip_network('169.254.0.0/16'),   # link-local — cloud metadata
    ipaddress.ip_network('172.16.0.0/12'),    # private
    ipaddress.ip_network('192.0.0.0/24'),     # IETF protocol assignments
    ipaddress.ip_network('192.168.0.0/16'),   # private
    ipaddress.ip_network('198.18.0.0/15'),    # benchmarking
    ipaddress.ip_network('224.0.0.0/4'),      # multicast
    ipaddress.ip_network('240.0.0.0/4'),      # reserved
    ipaddress.ip_network('::1/128'),          # IPv6 loopback
    ipaddress.ip_network('fc00::/7'),         # IPv6 unique-local
    ipaddress.ip_network('fe80::/10'),        # IPv6 link-local
]

# Hostnames that resolve to metadata services on the major clouds. DNS would
# usually catch these via the link-local range, but naming them means a
# poisoned or split-horizon resolver doesn't get a second chance.
BLOCKED_HOSTNAMES = {
    'metadata.google.internal',
    'metadata.goog',
    'instance-data',
}

ALLOWED_SCHEMES = ('http', 'https')


class BlockedTargetError(ValueError):
    """Raised when a URL resolves to an address we refuse to contact."""


def _allow_internal() -> bool:
    return getattr(settings, 'MONITOR_ALLOW_INTERNAL_TARGETS', False)


def is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # not parseable as an address — refuse it

    # ::ffff:127.0.0.1 and friends must be judged as the IPv4 address they wrap.
    if getattr(addr, 'ipv4_mapped', None):
        addr = addr.ipv4_mapped

    return any(addr in net for net in BLOCKED_NETWORKS)


def resolve_host(hostname: str) -> list[str]:
    """Every address the hostname resolves to, v4 and v6."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise BlockedTargetError(f'Could not resolve hostname: {hostname}') from exc
    return sorted({info[4][0] for info in infos})


def validate_outbound_url(url: str, allow_unresolvable: bool = False) -> str:
    """
    Check a URL is safe to request, resolving DNS to do it.

    Must be called immediately before each request — including every redirect
    hop — because a name that resolved to a public address a moment ago can
    resolve somewhere else now (DNS rebinding).

    `allow_unresolvable=True` is for save-time validation only: a user may add
    a monitor for a host whose DNS is currently broken — that is precisely the
    outage they want to watch for. It is safe because the request-time call
    (which uses the strict default) is the actual boundary.

    Returns the URL unchanged; raises BlockedTargetError if it must not be hit.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise BlockedTargetError('URL must use http:// or https://')
    if not parsed.hostname:
        raise BlockedTargetError('URL must include a hostname.')
    if parsed.username or parsed.password:
        raise BlockedTargetError('Credentials in the URL are not allowed.')

    if _allow_internal():
        return url

    hostname = parsed.hostname.lower().rstrip('.')
    if hostname in BLOCKED_HOSTNAMES or hostname == 'localhost' or hostname.endswith('.localhost'):
        raise BlockedTargetError(f'{parsed.hostname} is not an allowed target.')

    # Resolve first, then judge the addresses. Judging the *string* is what let
    # 127.0.0.2, 2130706433 and [::ffff:127.0.0.1] through before.
    try:
        addresses = resolve_host(hostname)
    except BlockedTargetError:
        if allow_unresolvable:
            return url
        raise

    for ip in addresses:
        if is_blocked_ip(ip):
            raise BlockedTargetError(
                f'{parsed.hostname} resolves to a private or reserved address ({ip}).'
            )

    return url
