"""
Real-time event delivery (SSE).

Flow, per the design document:

    1. Celery worker writes a check result
    2. Same worker publishes to Redis Pub/Sub
    3. A long-lived Django process subscribes
    4. On event, it pushes to open SSE connections
    5. The dashboard updates

Channel choice: the doc suggests `monitor:{id}`, but a dashboard watches every
monitor in an org at once, which would mean N subscriptions per open tab. We
publish to `org:{orgId}` with `monitor_id` in the payload instead — one
subscription per tab, and the client filters. Same events, less bookkeeping.
"""

import json
import logging
import time
import redis


logger = logging.getLogger(__name__)

# How often an idle stream emits a comment frame. Without this, proxies and
# load balancers quietly close a connection that has been silent too long.
HEARTBEAT_SECONDS = 25

# Ceiling on a single connection's lifetime. Each open SSE stream occupies a
# worker thread under WSGI, so connections are recycled rather than immortal;
# EventSource reconnects on its own.
MAX_STREAM_SECONDS = 3600


def org_channel(org_id) -> str:
    return f'org:{org_id}'


def get_redis():
    """Raw Redis client, borrowed from the configured Django cache."""
    from django_redis import get_redis_connection
    return get_redis_connection('default')


def publish_monitor_event(monitor, event: str, **fields) -> None:
    """
    Announce a monitor state change to any listening dashboard.

    Never raises: a dead Redis must not take down the check that just ran.
    Losing a live update is cosmetic — the check result is already in Postgres.
    """
    payload = {
        'event': event,
        'monitor_id': monitor.pk,
        'monitor_name': monitor.name,
        'organization_id': monitor.organization_id,
        'last_status': monitor.last_status,
        'ts': time.time(),
        **fields,
    }
    try:
        get_redis().publish(org_channel(monitor.organization_id), json.dumps(payload))
    except (redis.exceptions.RedisError, NotImplementedError):
        logger.warning('Could not publish %s for monitor %s.', event, monitor.pk, exc_info=True)


def sse_format(data: dict, event: str | None = None) -> str:
    """Encode one Server-Sent Event frame."""
    prefix = f'event: {event}\n' if event else ''
    return f'{prefix}data: {json.dumps(data)}\n\n'


def event_stream(org_id):
    """
    Generator yielding SSE frames for one organization.

    Blocks on Redis with a short timeout so heartbeats still go out on an
    otherwise silent channel.
    """
    try:
        pubsub = get_redis().pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(org_channel(org_id))
    except (redis.exceptions.RedisError, NotImplementedError):
        logger.warning('SSE: Redis unavailable for org %s.', org_id, exc_info=True)
        yield sse_format({'detail': 'Live updates unavailable.'}, event='error')
        return

    started = time.monotonic()
    last_beat = started

    try:
        # Must be inside the try: a client that disconnects right after the
        # handshake still has to reach the finally and release the subscription.
        yield sse_format({'organization_id': org_id}, event='connected')

        while time.monotonic() - started < MAX_STREAM_SECONDS:
            message = pubsub.get_message(timeout=1.0)
            if message and message.get('type') == 'message':
                try:
                    payload = json.loads(message['data'])
                except (ValueError, TypeError):
                    continue
                yield sse_format(payload, event=payload.get('event'))
                last_beat = time.monotonic()
                continue

            if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
                yield ': keepalive\n\n'
                last_beat = time.monotonic()
    except GeneratorExit:
        # Client hung up.
        raise
    finally:
        try:
            pubsub.close()
        except (redis.exceptions.RedisError, NotImplementedError):
            pass
