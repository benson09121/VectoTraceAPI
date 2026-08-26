"""
Monitor probes.

Every probe returns the same `ProbeResult`, so the failure-detection state
machine, incident lifecycle and alerting downstream of it stay completely
unchanged regardless of what is being checked. Adding a monitor type means
adding one function here and one entry in `PROBES` — nothing else.

SSRF containment applies to all of them, not just HTTP: a TCP port probe aimed
at 127.0.0.1:6379 is just as much an internal port scanner as an HTTP one.
"""

import json
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from django.utils import timezone as django_timezone

from .net import BlockedTargetError, is_blocked_ip, resolve_host, validate_outbound_url


@dataclass
class ProbeResult:
    passed: bool
    status_code: int | None = None
    response_time_ms: int | None = None
    error_message: str | None = None
    ssl_valid: bool | None = None
    ssl_expires_at: datetime | None = None
    timings: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


def _guard_host(host: str) -> str:
    """
    Refuse hostnames that resolve into our own network.

    The URL validator can't be reused directly here because ping/port/dns
    monitors carry a bare hostname rather than a URL.
    """
    from django.conf import settings

    if getattr(settings, 'MONITOR_ALLOW_INTERNAL_TARGETS', False):
        return host

    host = (host or '').strip().lower().rstrip('.')
    if not host:
        raise BlockedTargetError('A hostname is required.')
    if host == 'localhost' or host.endswith('.localhost'):
        raise BlockedTargetError(f'{host} is not an allowed target.')

    for ip in resolve_host(host):
        if is_blocked_ip(ip):
            raise BlockedTargetError(
                f'{host} resolves to a private or reserved address ({ip}).'
            )
    return host


def connect_within_budget(host: str, port: int, budget_s: float):
    """
    Open a TCP connection, bounding the TOTAL time rather than the time per
    address.

    `socket.create_connection` walks every address the host resolves to and
    applies the timeout to each one, so a dual-stack host with an unreachable
    port burns 2x the configured timeout — an 8s timeout took 16s in practice.
    That ties up a worker for twice its budget, so the deadline is enforced
    across all candidates here.
    """
    deadline = time.monotonic() + budget_s
    last_error: Exception | None = None

    for family, socktype, proto, _canon, sockaddr in socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    ):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(remaining)
        try:
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()

    raise last_error or TimeoutError(f'Could not connect to {host}:{port}')


def _hostname_of(monitor) -> str:
    """Accept either a bare hostname or a URL in `monitor.url`."""
    raw = (monitor.url or '').strip()
    if '://' in raw:
        return urlparse(raw).hostname or ''
    return raw.split('/')[0].split(':')[0]


# ---------------------------------------------------------------------------
# HTTP family
# ---------------------------------------------------------------------------

def probe_http(monitor, session) -> ProbeResult:
    """Plain HTTP(S) status-code check. The original behaviour."""
    from .tasks import _peer_cert_from, _request_with_guarded_redirects, expected_codes

    timeout_s = (monitor.timeout_ms or 30000) / 1000.0
    method = monitor.http_method.upper()
    body = monitor.request_body if method in ('POST', 'PUT', 'PATCH') else None

    resp = _request_with_guarded_redirects(
        method=method, url=monitor.url, headers=monitor.request_headers or {},
        json_body=body, timeout_s=timeout_s, follow_redirects=monitor.follow_redirect,
    )
    timings = getattr(resp, 'vt_timings', {}) or {}
    ssl_valid = ssl_expires_at = None
    if monitor.url.startswith('https://'):
        ssl_valid, ssl_expires_at = _peer_cert_from(resp)

    try:
        content = resp.content
    finally:
        resp.close()

    passed = resp.status_code in expected_codes(monitor)
    result = ProbeResult(
        passed=passed,
        status_code=resp.status_code,
        response_time_ms=int(resp.elapsed.total_seconds() * 1000),
        ssl_valid=ssl_valid,
        ssl_expires_at=ssl_expires_at,
        timings=timings,
        error_message=None if passed else f'Unexpected status {resp.status_code}.',
    )
    result._body = content  # consumed by the keyword/json probes
    return result


def probe_keyword(monitor, session) -> ProbeResult:
    """
    HTTP plus a body assertion.

    200 OK with "Database error" in the page is still an outage — this is the
    gap a status-code-only check leaves open.
    """
    result = probe_http(monitor, session)
    if not result.passed:
        return result

    body = getattr(result, '_body', b'') or b''
    text = body.decode('utf-8', errors='replace')
    present = monitor.keyword in text

    if monitor.keyword_inverted:
        result.passed = not present
        if present:
            result.error_message = f'Forbidden keyword {monitor.keyword!r} found in body.'
    else:
        result.passed = present
        if not present:
            result.error_message = f'Keyword {monitor.keyword!r} not found in body.'
    return result


def probe_json(monitor, session) -> ProbeResult:
    """HTTP plus an assertion on a dotted path into the JSON body."""
    result = probe_http(monitor, session)
    if not result.passed:
        return result

    body = getattr(result, '_body', b'') or b''
    try:
        data = json.loads(body.decode('utf-8', errors='replace'))
    except ValueError:
        result.passed = False
        result.error_message = 'Response body is not valid JSON.'
        return result

    value = data
    for part in filter(None, monitor.json_path.split('.')):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            result.passed = False
            result.error_message = f'JSON path {monitor.json_path!r} not found.'
            return result

    if str(value) != monitor.json_expected:
        result.passed = False
        result.error_message = (
            f'JSON path {monitor.json_path!r} was {value!r}, '
            f'expected {monitor.json_expected!r}.'
        )
    return result


# ---------------------------------------------------------------------------
# Network family
# ---------------------------------------------------------------------------

def probe_port(monitor, session) -> ProbeResult:
    """TCP connect. Does the port accept a connection at all?"""
    host = _guard_host(_hostname_of(monitor))
    port = monitor.port or 80
    timeout_s = (monitor.timeout_ms or 30000) / 1000.0

    start = time.perf_counter()
    try:
        with connect_within_budget(host, port, timeout_s):
            ms = int((time.perf_counter() - start) * 1000)
        return ProbeResult(passed=True, response_time_ms=ms,
                           timings={'connect_ms': ms})
    except OSError as exc:
        return ProbeResult(
            passed=False,
            response_time_ms=int((time.perf_counter() - start) * 1000),
            error_message=f'Cannot connect to {host}:{port} — {exc.__class__.__name__}',
        )


def probe_ping(monitor, session) -> ProbeResult:
    """
    Reachability without raw ICMP.

    True ICMP needs root or CAP_NET_RAW, which a container running as an
    unprivileged user does not have. A TCP handshake against a common port is
    a reachability signal that works everywhere, so that is what this does —
    the field is named 'ping' for familiarity, and the docs say what it means.
    """
    host = _guard_host(_hostname_of(monitor))
    timeout_s = min((monitor.timeout_ms or 30000) / 1000.0, 10)

    start = time.perf_counter()
    last_error = None
    # Split the budget across both ports so the whole probe stays bounded.
    per_port = max(1.0, timeout_s / 2)
    for port in (443, 80):
        try:
            with connect_within_budget(host, port, per_port):
                ms = int((time.perf_counter() - start) * 1000)
            return ProbeResult(passed=True, response_time_ms=ms)
        except OSError as exc:
            last_error = exc

    return ProbeResult(
        passed=False,
        response_time_ms=int((time.perf_counter() - start) * 1000),
        error_message=f'{host} unreachable on 443/80 — {last_error.__class__.__name__}',
    )


def probe_dns(monitor, session) -> ProbeResult:
    """
    Resolve a hostname and optionally assert the answer.

    Catches hijacks and botched migrations, which a plain HTTP check misses
    entirely because it just follows wherever DNS points.
    """
    host = (_hostname_of(monitor) or '').strip().lower()
    if not host:
        return ProbeResult(passed=False, error_message='A hostname is required.')

    start = time.perf_counter()
    try:
        addresses = resolve_host(host)
    except BlockedTargetError as exc:
        return ProbeResult(passed=False, error_message=str(exc))
    ms = int((time.perf_counter() - start) * 1000)

    if monitor.dns_expected:
        expected = {v.strip() for v in monitor.dns_expected.split(',') if v.strip()}
        if not expected & set(addresses):
            return ProbeResult(
                passed=False, response_time_ms=ms, timings={'dns_ms': ms},
                error_message=(
                    f'{host} resolved to {", ".join(addresses)}; '
                    f'expected {", ".join(sorted(expected))}.'
                ),
            )
    return ProbeResult(passed=True, response_time_ms=ms, timings={'dns_ms': ms})


# ---------------------------------------------------------------------------
# Certificate / domain family
# ---------------------------------------------------------------------------

def probe_ssl(monitor, session) -> ProbeResult:
    """
    Certificate validity and expiry as a monitor in its own right, rather than
    a side effect of an HTTP check.
    """
    host = _guard_host(_hostname_of(monitor))
    parsed = urlparse(monitor.url if '://' in monitor.url else f'https://{monitor.url}')
    port = parsed.port or 443
    timeout_s = min((monitor.timeout_ms or 30000) / 1000.0, 15)

    start = time.perf_counter()
    ctx = ssl.create_default_context()
    try:
        with connect_within_budget(host, port, timeout_s) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
        ms = int((time.perf_counter() - start) * 1000)
    except ssl.SSLError as exc:
        return ProbeResult(passed=False, ssl_valid=False,
                           error_message=f'TLS error: {exc}')
    except OSError as exc:
        return ProbeResult(passed=False,
                           error_message=f'Cannot connect to {host}:{port} — {exc}')

    expires_at = None
    issuer = 'Unknown Issuer'
    if cert and cert.get('notAfter'):
        try:
            expires_at = datetime.strptime(
                cert['notAfter'], '%b %d %H:%M:%S %Y %Z'
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

        issuer_parts = []
        for rdn in cert.get('issuer', []):
            for part in rdn:
                if len(part) >= 2 and part[0] in ('organizationName', 'commonName'):
                    issuer_parts.append(part[1])
        if issuer_parts:
            issuer = ', '.join(issuer_parts)

    expired = expires_at is not None and expires_at <= django_timezone.now()
    return ProbeResult(
        passed=not expired,
        response_time_ms=ms,
        ssl_valid=not expired,
        ssl_expires_at=expires_at,
        timings={'tls_ms': ms},
        meta={'issuer': issuer},
        error_message='Certificate has expired.' if expired else None,
    )


def probe_domain(monitor, session) -> ProbeResult:
    """
    Domain registration expiry via RDAP (the modern replacement for WHOIS).

    Domains lapse and take everything down with them, which no uptime check
    catches until it is already too late.
    """
    host = _hostname_of(monitor)
    if not host:
        return ProbeResult(passed=False, error_message='A domain is required.')

    # Registrable domain: RDAP answers for the registered name, not the host.
    parts = host.split('.')
    domain = '.'.join(parts[-2:]) if len(parts) >= 2 else host

    url = f'https://rdap.org/domain/{domain}'
    validate_outbound_url(url, allow_unresolvable=True)

    start = time.perf_counter()
    try:
        resp = session.get(url, timeout=15, allow_redirects=True)
    except Exception as exc:
        return ProbeResult(passed=False,
                           error_message=f'RDAP lookup failed: {type(exc).__name__}')
    ms = int((time.perf_counter() - start) * 1000)

    if resp.status_code == 404:
        return ProbeResult(passed=False, status_code=404, response_time_ms=ms,
                           error_message=f'{domain} is not registered.')
    if resp.status_code != 200:
        return ProbeResult(passed=False, status_code=resp.status_code,
                           response_time_ms=ms,
                           error_message=f'RDAP returned {resp.status_code}.')

    data = resp.json()

    registrar = 'Unknown'
    for entity in data.get('entities', []):
        if 'registrar' in entity.get('roles', []):
            vcard = entity.get('vcardArray', [])
            if len(vcard) >= 2:
                for prop in vcard[1]:
                    if len(prop) >= 4 and prop[0] == 'fn':
                        registrar = prop[3]
                        break

    expires_at = None
    for event in (data.get('events') or []):
        if event.get('eventAction') == 'expiration':
            try:
                expires_at = datetime.fromisoformat(
                    event['eventDate'].replace('Z', '+00:00')
                )
            except (ValueError, KeyError):
                pass

    expired = expires_at is not None and expires_at <= django_timezone.now()
    return ProbeResult(
        passed=not expired,
        status_code=200,
        response_time_ms=ms,
        ssl_expires_at=expires_at,  # reuse the expiry column for the alerting task
        error_message=f'{domain} registration has expired.' if expired else None,
        meta={'registrar': registrar},
    )


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

def probe_heartbeat(monitor, session) -> ProbeResult:
    """
    Inverted check: the job pings us, we alert when it stops.

    Nothing is dialled out — this evaluates whether a ping arrived inside
    interval + grace. Catches the failed nightly backup that nobody notices
    for three weeks, which no outbound check can ever see.
    """
    deadline_seconds = monitor.interval + (monitor.heartbeat_grace_seconds or 0)
    last = monitor.last_heartbeat_at

    if last is None:
        return ProbeResult(
            passed=False,
            error_message='No heartbeat received yet.',
        )

    silence = (django_timezone.now() - last).total_seconds()
    if silence > deadline_seconds:
        return ProbeResult(
            passed=False,
            error_message=(
                f'No heartbeat for {int(silence)}s '
                f'(expected within {deadline_seconds}s).'
            ),
        )
    return ProbeResult(passed=True, response_time_ms=int(silence * 1000))


PROBES = {
    'http': probe_http,
    'keyword': probe_keyword,
    'json': probe_json,
    'ping': probe_ping,
    'port': probe_port,
    'dns': probe_dns,
    'ssl': probe_ssl,
    'domain': probe_domain,
    'heartbeat': probe_heartbeat,
    'push': probe_heartbeat,  # legacy alias
}

