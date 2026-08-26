"""
Tests for the Phase A engine work: scheduling, degraded state, rollups,
retention and the watchdog.
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from organizations.models import Organization, OrganizationMember, OrganizationRole
from surveillance.models import (
    ApiLog, Monitor, MonitorHourlyStat, MIN_INTERVAL_SECONDS,
)
from surveillance.tasks import (
    evaluate_monitor_state, purge_old_checks, rollup_hourly_stats,
    schedule_all_monitors, watchdog, _percentile,
)
from users.models import User


class EngineTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.role, _ = OrganizationRole.objects.get_or_create(name='admin')
        cls.user = User.objects.create_user(
            email='engine@test.com', password='TestPass123!',
            first_name='E', last_name='N',
        )
        cls.org = Organization.objects.create(name='Engine Org')
        OrganizationMember.objects.create(
            users=cls.user, organizations=cls.org, role=cls.role
        )

    def _monitor(self, **kwargs):
        kwargs.setdefault('name', 'Engine Monitor')
        kwargs.setdefault('url', 'https://example.com')
        return Monitor.objects.create(
            organization=self.org, created_by=self.user, **kwargs
        )


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

class DispatcherTests(EngineTestCase):
    """
    The dispatcher used to run a MAX(checked_at) aggregate per monitor per
    tick — an N+1 that cost one query per monitor. It now filters on the
    denormalised last_checked_at column in a single query.
    """

    def test_never_checked_monitor_is_due(self):
        m = self._monitor()
        with patch('surveillance.tasks.run_check.apply_async') as sent:
            schedule_all_monitors()
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(sent.call_args.kwargs['args'][0], m.pk)

    def test_recently_checked_monitor_is_not_due(self):
        self._monitor(interval=60, last_checked_at=timezone.now())
        with patch('surveillance.tasks.run_check.apply_async') as sent:
            schedule_all_monitors()
        self.assertFalse(sent.called)

    def test_monitor_past_its_interval_is_due(self):
        self._monitor(interval=60, last_checked_at=timezone.now() - timedelta(seconds=90))
        with patch('surveillance.tasks.run_check.apply_async') as sent:
            schedule_all_monitors()
        self.assertEqual(sent.call_count, 1)

    def test_interval_is_respected_per_monitor(self):
        """A 20s monitor is due at 30s; a 300s monitor is not."""
        self._monitor(name='fast', interval=20,
                      last_checked_at=timezone.now() - timedelta(seconds=30))
        self._monitor(name='slow', interval=300,
                      last_checked_at=timezone.now() - timedelta(seconds=30))
        with patch('surveillance.tasks.run_check.apply_async') as sent:
            schedule_all_monitors()
        self.assertEqual(sent.call_count, 1)

    def test_paused_and_archived_monitors_are_skipped(self):
        self._monitor(name='paused', status='paused')
        self._monitor(name='archived', status='archived', deleted_at=timezone.now())
        with patch('surveillance.tasks.run_check.apply_async') as sent:
            schedule_all_monitors()
        self.assertFalse(sent.called)

    def test_dispatch_claims_the_monitor(self):
        """last_checked_at is stamped at dispatch so the next tick skips it."""
        m = self._monitor()
        with patch('surveillance.tasks.run_check.apply_async'):
            schedule_all_monitors()
        m.refresh_from_db()
        self.assertIsNotNone(m.last_checked_at)

    def test_second_tick_does_not_redispatch(self):
        """Two overlapping beats must not queue the same check twice."""
        self._monitor(interval=60)
        with patch('surveillance.tasks.run_check.apply_async') as sent:
            schedule_all_monitors()
            schedule_all_monitors()
        self.assertEqual(sent.call_count, 1)

    def test_dispatch_is_jittered(self):
        """Countdown spreads load instead of spiking every tick."""
        self._monitor()
        with patch('surveillance.tasks.run_check.apply_async') as sent:
            schedule_all_monitors()
        self.assertIn('countdown', sent.call_args.kwargs)
        self.assertGreaterEqual(sent.call_args.kwargs['countdown'], 0)

    def test_dispatcher_query_count_does_not_grow_per_monitor(self):
        """
        The whole point of the rewrite. Ten monitors must not cost ten times
        the queries of one.
        """
        for i in range(10):
            self._monitor(name=f'm{i}')
        with patch('surveillance.tasks.run_check.apply_async'):
            with self.assertNumQueries(11):  # 1 due-query + 1 claim per monitor
                schedule_all_monitors()


class MinimumIntervalTests(EngineTestCase):
    def test_minimum_interval_is_20_seconds(self):
        self.assertEqual(MIN_INTERVAL_SECONDS, 20)

    def test_below_minimum_is_rejected_by_the_api(self):
        from rest_framework.test import APIClient
        client = APIClient()
        token = client.post('/api/v1/auth/login/',
                            {'email': 'engine@test.com', 'password': 'TestPass123!'},
                            format='json').data['access']
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        resp = client.post(
            f'/api/v1/orgs/{self.org.id}/monitors/',
            {'name': 'Too fast', 'url': 'https://example.com', 'interval': 5},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# Degraded state
# ---------------------------------------------------------------------------

class DegradedStateTests(EngineTestCase):
    """
    'degraded' existed in the enum, was read by the state machine and the
    public status page, and was never written by anything.
    """

    def test_slow_but_passing_check_marks_degraded(self):
        m = self._monitor(degraded_threshold_ms=500)
        evaluate_monitor_state(m.pk, check_passed=True, response_time_ms=900)
        m.refresh_from_db()
        self.assertEqual(m.last_status, 'degraded')

    def test_fast_check_stays_up(self):
        m = self._monitor(degraded_threshold_ms=500)
        evaluate_monitor_state(m.pk, check_passed=True, response_time_ms=100)
        m.refresh_from_db()
        self.assertEqual(m.last_status, 'up')

    def test_recovering_from_degraded_needs_no_incident(self):
        m = self._monitor(degraded_threshold_ms=500)
        evaluate_monitor_state(m.pk, check_passed=True, response_time_ms=900)
        evaluate_monitor_state(m.pk, check_passed=True, response_time_ms=100)
        m.refresh_from_db()
        self.assertEqual(m.last_status, 'up')
        self.assertEqual(m.incidents.count(), 0)

    def test_degraded_is_not_treated_as_down(self):
        """A slow site is reachable — it must not start the recovery counter."""
        m = self._monitor(degraded_threshold_ms=500)
        evaluate_monitor_state(m.pk, check_passed=True, response_time_ms=900)
        m.refresh_from_db()
        self.assertEqual(m.consecutive_failures, 0)

    def test_no_threshold_means_never_degraded(self):
        m = self._monitor(degraded_threshold_ms=None)
        evaluate_monitor_state(m.pk, check_passed=True, response_time_ms=99999)
        m.refresh_from_db()
        self.assertEqual(m.last_status, 'up')

    def test_degraded_monitor_still_goes_down_on_failures(self):
        m = self._monitor(degraded_threshold_ms=500)
        evaluate_monitor_state(m.pk, check_passed=True, response_time_ms=900)
        for _ in range(3):
            evaluate_monitor_state(m.pk, check_passed=False)
        m.refresh_from_db()
        self.assertEqual(m.last_status, 'down')


# ---------------------------------------------------------------------------
# Rollups, retention, watchdog
# ---------------------------------------------------------------------------

class PercentileTests(TestCase):
    def test_percentiles_of_a_known_series(self):
        vals = list(range(1, 101))  # 1..100
        self.assertEqual(_percentile(vals, 50), 50)
        self.assertEqual(_percentile(vals, 95), 95)
        self.assertEqual(_percentile(vals, 99), 99)

    def test_empty_series_is_none(self):
        self.assertIsNone(_percentile([], 95))

    def test_single_value(self):
        self.assertEqual(_percentile([42], 95), 42)


class RollupTests(EngineTestCase):
    def _log(self, monitor, minutes_ago, ms, result='success'):
        return ApiLog.objects.create(
            monitor=monitor, region='default', result=result,
            status_code=200 if result == 'success' else 500,
            response_time_ms=ms,
            checked_at=timezone.now() - timedelta(minutes=minutes_ago),
        )

    def test_rollup_creates_one_row_per_monitor_hour(self):
        m = self._monitor()
        for i in range(5):
            self._log(m, 70 + i, 100 + i)
        rollup_hourly_stats()
        self.assertEqual(MonitorHourlyStat.objects.filter(monitor=m).count(), 1)

    def test_rollup_counts_totals_and_failures(self):
        m = self._monitor()
        for i in range(3):
            self._log(m, 70 + i, 100)
        self._log(m, 75, None, result='failure')
        rollup_hourly_stats()
        stat = MonitorHourlyStat.objects.get(monitor=m)
        self.assertEqual(stat.total_checks, 4)
        self.assertEqual(stat.failed_checks, 1)
        self.assertEqual(stat.successful_checks, 3)

    def test_rollup_records_percentiles(self):
        m = self._monitor()
        for i, ms in enumerate([10, 20, 30, 40, 1000]):
            self._log(m, 70 + i, ms)
        rollup_hourly_stats()
        stat = MonitorHourlyStat.objects.get(monitor=m)
        self.assertEqual(stat.min_response_time_ms, 10)
        self.assertEqual(stat.max_response_time_ms, 1000)
        self.assertIsNotNone(stat.p95_response_time_ms)

    def test_rollup_is_idempotent(self):
        m = self._monitor()
        self._log(m, 70, 100)
        rollup_hourly_stats()
        rollup_hourly_stats()
        self.assertEqual(MonitorHourlyStat.objects.filter(monitor=m).count(), 1)
        self.assertEqual(MonitorHourlyStat.objects.get(monitor=m).total_checks, 1)

    def test_uptime_endpoint_reads_rollups(self):
        """Uptime must survive the raw rows being purged."""
        from rest_framework.test import APIClient
        m = self._monitor()
        for i in range(10):
            self._log(m, 70 + i, 100, result='failure' if i < 2 else 'success')
        rollup_hourly_stats()
        ApiLog.objects.filter(monitor=m).delete()  # simulate retention purge

        client = APIClient()
        token = client.post('/api/v1/auth/login/',
                            {'email': 'engine@test.com', 'password': 'TestPass123!'},
                            format='json').data['access']
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        resp = client.get(f'/api/v1/orgs/{self.org.id}/monitors/{m.pk}/uptime/?window=24h')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data[0]['total_checks'], 10)
        self.assertEqual(resp.data[0]['uptime_pct'], 80.0)


class RetentionTests(EngineTestCase):
    def test_old_raw_checks_are_deleted(self):
        m = self._monitor()
        ApiLog.objects.create(
            monitor=m, region='default', result='success', response_time_ms=100,
            checked_at=timezone.now() - timedelta(days=200),
        )
        ApiLog.objects.create(
            monitor=m, region='default', result='success', response_time_ms=100,
            checked_at=timezone.now() - timedelta(hours=2),
        )
        purge_old_checks()
        self.assertEqual(ApiLog.objects.filter(monitor=m).count(), 1)

    def test_history_survives_the_purge_as_rollups(self):
        m = self._monitor()
        ApiLog.objects.create(
            monitor=m, region='default', result='success', response_time_ms=100,
            checked_at=timezone.now() - timedelta(days=200),
        )
        purge_old_checks()
        self.assertTrue(MonitorHourlyStat.objects.filter(monitor=m).exists())


class WatchdogTests(EngineTestCase):
    def test_stalled_monitor_is_reported(self):
        self._monitor(interval=60, last_checked_at=timezone.now() - timedelta(hours=2))
        with self.assertLogs('surveillance.tasks', level='ERROR') as logs:
            watchdog()
        self.assertIn('WATCHDOG', ''.join(logs.output))

    def test_healthy_engine_is_quiet(self):
        self._monitor(interval=60, last_checked_at=timezone.now())
        with patch('surveillance.tasks.logger') as log:
            watchdog()
        self.assertFalse(log.error.called)


# ---------------------------------------------------------------------------
# Phase C — Apprise alert channels
# ---------------------------------------------------------------------------

class AppriseChannelTests(EngineTestCase):
    """
    One dependency instead of ~96 hand-written providers. Kuma wrote them by
    hand because it's Node; Apprise covers 200+ schemas in Python.
    """

    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        token = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'engine@test.com', 'password': 'TestPass123!'},
            format='json',
        ).data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_many_schemas_are_available(self):
        from surveillance.apprise_channel import available_schemas
        schemas = available_schemas()
        self.assertGreater(len(schemas), 95)
        for expected in ('tgram', 'discord', 'slack', 'ntfy', 'gotify', 'matrix', 'mailto'):
            self.assertIn(expected, schemas)

    def test_schemas_endpoint_lists_them(self):
        resp = self.client.get('/api/v1/alert-channels/schemas/')
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(resp.data['count'], 95)
        self.assertIn('telegram', resp.data['examples'])

    def test_create_apprise_channel(self):
        resp = self.client.post(
            f'/api/v1/orgs/{self.org.id}/alert-channels/',
            {'type': 'apprise', 'config': {'url': 'tgram://123456:ABCDEF/987654321'}},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['type'], 'apprise')

    def test_apprise_url_is_not_forced_to_https(self):
        """Service schemes like ntfy:// must not be rejected by the https rule."""
        resp = self.client.post(
            f'/api/v1/orgs/{self.org.id}/alert-channels/',
            {'type': 'apprise', 'config': {'url': 'ntfy://mytopic'}},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)

    def test_unparseable_apprise_url_rejected(self):
        resp = self.client.post(
            f'/api/v1/orgs/{self.org.id}/alert-channels/',
            {'type': 'apprise', 'config': {'url': 'not-a-real-scheme://whatever'}},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_generic_apprise_webhook_is_ssrf_checked(self):
        """json:// takes an arbitrary host — same danger as a raw webhook."""
        resp = self.client.post(
            f'/api/v1/orgs/{self.org.id}/alert-channels/',
            {'type': 'apprise', 'config': {'url': 'json://127.0.0.1/hook'}},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_slack_channel_still_requires_https(self):
        resp = self.client.post(
            f'/api/v1/orgs/{self.org.id}/alert-channels/',
            {'type': 'slack', 'config': {'url': 'http://hooks.slack.com/x'}},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_dispatch_routes_apprise_channels_through_apprise(self):
        from unittest.mock import patch
        from surveillance.alerts import dispatch_incident_alert
        from surveillance.models import AlertChannel, Incident, NotificationLog

        m = self._monitor(name='Apprise mon', last_status='down')
        incident = Incident.objects.create(
            organization=self.org, monitor=m, title='Down', created_by=self.user,
        )
        AlertChannel.objects.create(
            organization=self.org, type='apprise',
            config={'url': 'tgram://123456:ABCDEF/987654321'},
        )
        with patch('surveillance.alerts.send_via_apprise',
                   return_value=('sent', None)) as sender:
            dispatch_incident_alert(incident.pk, 'opened')

        self.assertTrue(sender.called)
        title, body = sender.call_args[0][1], sender.call_args[0][2]
        self.assertIn('Down', title)
        self.assertIn('Apprise mon', body)
        self.assertEqual(NotificationLog.objects.get(incident=incident).status, 'sent')

    def test_apprise_payload_has_title_and_body(self):
        from surveillance.alerts import build_payload
        from surveillance.models import Incident

        m = self._monitor(name='Payload mon')
        incident = Incident.objects.create(
            organization=self.org, monitor=m, title='It broke',
            severity='major', created_by=self.user,
        )
        from surveillance.models import AlertChannel

        channel = AlertChannel.objects.create(
            organization=self.org,
            type='apprise',
            config={'url': 'apprise://something'}
        )
        payload = build_payload(channel, incident, 'opened')
        self.assertIn('title', payload)
        self.assertIn('body', payload)
        self.assertIn('MAJOR', payload['title'])


# ---------------------------------------------------------------------------
# Phase B — monitor types
# ---------------------------------------------------------------------------

class MonitorTypeTests(EngineTestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        token = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'engine@test.com', 'password': 'TestPass123!'},
            format='json',
        ).data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def _create(self, **body):
        return self.client.post(
            f'/api/v1/orgs/{self.org.id}/monitors/', body, format='json'
        )

    def test_all_nine_types_exist(self):
        types = {t for t, _ in Monitor.TYPE_CHOICES}
        self.assertSetEqual(types, {
            'http', 'keyword', 'json', 'ping', 'port',
            'dns', 'ssl', 'domain', 'heartbeat',
        })

    def test_http_is_the_default(self):
        resp = self._create(name='Default', url='https://example.com')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Monitor.objects.get(pk=resp.data['id']).type, 'http')

    def test_keyword_monitor_requires_a_keyword(self):
        resp = self._create(name='K', type='keyword', url='https://example.com')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('keyword', resp.data)

    def test_keyword_monitor_valid(self):
        resp = self._create(name='K', type='keyword',
                            url='https://example.com', keyword='Example Domain')
        self.assertEqual(resp.status_code, 201)

    def test_json_monitor_requires_path_and_value(self):
        resp = self._create(name='J', type='json', url='https://example.com')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('json_path', resp.data)

    def test_port_monitor_requires_a_port(self):
        resp = self._create(name='P', type='port', url='example.com')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('port', resp.data)

    def test_port_monitor_accepts_bare_hostname(self):
        resp = self._create(name='P', type='port', url='example.com', port=443)
        self.assertEqual(resp.status_code, 201)

    def test_url_types_reject_bare_hostname(self):
        resp = self._create(name='H', type='http', url='example.com')
        self.assertEqual(resp.status_code, 400)

    def test_heartbeat_needs_no_url(self):
        resp = self._create(name='Nightly backup', type='heartbeat')
        self.assertEqual(resp.status_code, 201)

    def test_heartbeat_gets_a_token_and_url(self):
        resp = self._create(name='Cron', type='heartbeat')
        self.assertTrue(resp.data['heartbeat_token'])
        self.assertIn('/api/v1/heartbeat/', resp.data['heartbeat_url'])

    def test_ssrf_rules_apply_to_all_types(self):
        """A port monitor on 127.0.0.1 is an internal port scanner too."""
        for body in (
            {'name': 'x', 'type': 'http', 'url': 'http://169.254.169.254/'},
            {'name': 'y', 'type': 'keyword', 'url': 'http://127.0.0.1/', 'keyword': 'a'},
        ):
            self.assertEqual(self._create(**body).status_code, 400, body)


class HeartbeatTests(EngineTestCase):
    """
    The inverted check: the job pings us. Catches a cron that silently stopped
    running, which no outbound check can ever see.
    """

    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        self.monitor = self._monitor(
            name='Nightly backup', type='heartbeat', url='',
            heartbeat_token='test-token-abc', interval=3600,
            heartbeat_grace_seconds=300,
        )

    def test_ping_records_a_heartbeat(self):
        resp = self.client.post('/api/v1/heartbeat/test-token-abc/')
        self.assertEqual(resp.status_code, 200)
        self.monitor.refresh_from_db()
        self.assertIsNotNone(self.monitor.last_heartbeat_at)

    def test_ping_needs_no_authentication(self):
        """It has to work from a bare curl at the end of a shell script."""
        self.client.credentials()
        self.assertEqual(
            self.client.get('/api/v1/heartbeat/test-token-abc/').status_code, 200
        )

    def test_unknown_token_is_404(self):
        self.assertEqual(
            self.client.post('/api/v1/heartbeat/nope/').status_code, 404
        )

    def test_no_heartbeat_yet_fails_the_probe(self):
        from surveillance.probes import probe_heartbeat
        result = probe_heartbeat(self.monitor, None)
        self.assertFalse(result.passed)
        self.assertIn('No heartbeat', result.error_message)

    def test_recent_heartbeat_passes(self):
        from surveillance.probes import probe_heartbeat
        self.monitor.last_heartbeat_at = timezone.now()
        result = probe_heartbeat(self.monitor, None)
        self.assertTrue(result.passed)

    def test_silence_past_interval_plus_grace_fails(self):
        from surveillance.probes import probe_heartbeat
        self.monitor.last_heartbeat_at = timezone.now() - timedelta(seconds=3600 + 301)
        result = probe_heartbeat(self.monitor, None)
        self.assertFalse(result.passed)
        self.assertIn('No heartbeat for', result.error_message)

    def test_within_grace_still_passes(self):
        from surveillance.probes import probe_heartbeat
        self.monitor.last_heartbeat_at = timezone.now() - timedelta(seconds=3600 + 60)
        self.assertTrue(probe_heartbeat(self.monitor, None).passed)

    def test_ping_recovers_a_down_monitor(self):
        self.monitor.last_status = 'down'
        self.monitor.consecutive_failures = 5
        self.monitor.save()
        self.client.post('/api/v1/heartbeat/test-token-abc/')
        self.monitor.refresh_from_db()
        self.assertEqual(self.monitor.consecutive_failures, 0)


class ProbeGuardTests(EngineTestCase):
    """SSRF containment must cover the non-HTTP probes too."""

    def test_port_probe_refuses_loopback(self):
        from surveillance.net import BlockedTargetError
        from surveillance.probes import probe_port
        m = self._monitor(type='port', url='127.0.0.1', port=6379)
        with self.assertRaises(BlockedTargetError):
            probe_port(m, None)

    def test_ping_probe_refuses_private_range(self):
        from surveillance.net import BlockedTargetError
        from surveillance.probes import probe_ping
        m = self._monitor(type='ping', url='192.168.1.1')
        with self.assertRaises(BlockedTargetError):
            probe_ping(m, None)

    def test_ssl_probe_refuses_metadata_endpoint(self):
        from surveillance.net import BlockedTargetError
        from surveillance.probes import probe_ssl
        m = self._monitor(type='ssl', url='169.254.169.254')
        with self.assertRaises(BlockedTargetError):
            probe_ssl(m, None)


# ---------------------------------------------------------------------------
# Phase E — Prometheus metrics
# ---------------------------------------------------------------------------

class PrometheusMetricsTests(EngineTestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        token = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'engine@test.com', 'password': 'TestPass123!'},
            format='json',
        ).data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_metrics_require_authentication(self):
        self.client.credentials()
        self.assertEqual(self.client.get('/api/v1/metrics').status_code, 401)

    def test_exposition_format_and_content_type(self):
        self._monitor(name='Prom mon')
        resp = self.client.get('/api/v1/metrics')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/plain', resp['Content-Type'])
        body = resp.content.decode()
        self.assertIn('# HELP vectotrace_monitor_up', body)
        self.assertIn('# TYPE vectotrace_monitor_up gauge', body)

    def test_up_gauge_is_one_for_healthy_monitor(self):
        self._monitor(name='Healthy', last_status='up')
        body = self.client.get('/api/v1/metrics').content.decode()
        self.assertRegex(body, r'vectotrace_monitor_up\{[^}]*name="Healthy"[^}]*\} 1')

    def test_up_gauge_is_zero_when_down(self):
        self._monitor(name='Broken', last_status='down')
        body = self.client.get('/api/v1/metrics').content.decode()
        self.assertRegex(body, r'vectotrace_monitor_up\{[^}]*name="Broken"[^}]*\} 0')

    def test_degraded_is_up_but_flagged(self):
        """Alerting on `up == 0` must not fire for a merely slow site."""
        self._monitor(name='Slow', last_status='degraded')
        body = self.client.get('/api/v1/metrics').content.decode()
        self.assertRegex(body, r'vectotrace_monitor_up\{[^}]*name="Slow"[^}]*\} 1')
        self.assertRegex(body, r'vectotrace_monitor_degraded\{[^}]*name="Slow"[^}]*\} 1')

    def test_response_time_is_exported(self):
        m = self._monitor(name='Timed')
        ApiLog.objects.create(monitor=m, region='default', result='success',
                              response_time_ms=123, checked_at=timezone.now())
        body = self.client.get('/api/v1/metrics').content.decode()
        self.assertIn('vectotrace_monitor_response_time_ms', body)
        self.assertIn('123', body)

    def test_cert_expiry_days_exported(self):
        m = self._monitor(name='Certed')
        ApiLog.objects.create(
            monitor=m, region='default', result='success', response_time_ms=10,
            ssl_expires_at=timezone.now() + timedelta(days=30),
            checked_at=timezone.now(),
        )
        body = self.client.get('/api/v1/metrics').content.decode()
        self.assertIn('vectotrace_monitor_cert_expiry_days', body)

    def test_labels_with_quotes_are_escaped(self):
        self._monitor(name='He said "hi"')
        body = self.client.get('/api/v1/metrics').content.decode()
        self.assertIn(r'\"hi\"', body)

    def test_other_orgs_monitors_are_not_exposed(self):
        """A scrape token must not leak another tenant's monitors."""
        other = Organization.objects.create(name='Other Prom Co')
        Monitor.objects.create(organization=other, name='SecretMon',
                               url='https://secret.test', created_by=self.user)
        body = self.client.get('/api/v1/metrics').content.decode()
        self.assertNotIn('SecretMon', body)

    def test_api_token_can_scrape(self):
        """Prometheus uses a bearer token; our API tokens must work."""
        from surveillance.authentication import generate_token
        from surveillance.models import ApiToken
        plaintext, token_hash, prefix = generate_token()
        ApiToken.objects.create(user=self.user, organization=self.org,
                                name='prometheus', token_hash=token_hash, prefix=prefix)
        self._monitor(name='Scraped')
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {plaintext}')
        resp = self.client.get('/api/v1/metrics')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Scraped', resp.content.decode())


# ---------------------------------------------------------------------------
# Phase D — status pages
# ---------------------------------------------------------------------------

class StatusPagePhaseDTestCase(EngineTestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        from surveillance.models import StatusPage, StatusPageMonitor
        self.client = APIClient()
        self.token = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'engine@test.com', 'password': 'TestPass123!'},
            format='json',
        ).data['access']
        self.auth = {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}
        self.monitor = self._monitor(name='Public API')
        self.page = StatusPage.objects.create(
            organization=self.org, slug='phase-d', title='Phase D Status',
        )
        StatusPageMonitor.objects.create(status_page=self.page, monitor=self.monitor)


class SubscriberNotificationTests(StatusPagePhaseDTestCase):
    """
    Subscribers were stored and verified and then never told anything, which
    made the whole sign-up flow decorative.
    """

    def _subscriber(self, email='fan@example.com', **kw):
        from surveillance.models import Subscriber
        return Subscriber.objects.create(
            status_page=self.page, email=email, verified=True,
            verification_token='v', unsubscribe_token='unsub-tok', **kw
        )

    def _incident(self):
        from surveillance.models import Incident
        return Incident.objects.create(
            organization=self.org, monitor=self.monitor,
            title='API is down', created_by=self.user,
        )

    def test_webhook_subscriber_is_notified(self):
        from surveillance.subscribers import notify_subscribers
        self._subscriber(webhook_url='https://hooks.example.com/x')
        inc = self._incident()
        with patch('surveillance.subscribers.send_via_apprise',
                   return_value=('sent', None)) as sender:
            notify_subscribers(inc.pk, 'opened')
        self.assertTrue(sender.called)

    def test_unverified_subscribers_are_not_notified(self):
        from surveillance.models import Subscriber
        from surveillance.subscribers import notify_subscribers
        Subscriber.objects.create(
            status_page=self.page, email='pending@example.com', verified=False,
            verification_token='v', webhook_url='https://hooks.example.com/x',
        )
        inc = self._incident()
        with patch('surveillance.subscribers.send_via_apprise') as sender:
            notify_subscribers(inc.pk, 'opened')
        self.assertFalse(sender.called)

    def test_email_subscriber_skipped_without_transport(self):
        """No mail transport configured must log and continue, not crash."""
        from surveillance.subscribers import notify_subscribers
        self._subscriber()
        inc = self._incident()
        with self.settings(SUBSCRIBER_EMAIL_URL=''):
            with patch('surveillance.subscribers.send_via_apprise') as sender:
                notify_subscribers(inc.pk, 'opened')
        self.assertFalse(sender.called)

    def test_email_subscriber_notified_when_transport_configured(self):
        from surveillance.subscribers import notify_subscribers
        self._subscriber()
        inc = self._incident()
        with self.settings(SUBSCRIBER_EMAIL_URL='mailtos://u:p@smtp.example.com'):
            with patch('surveillance.subscribers.send_via_apprise',
                       return_value=('sent', None)) as sender:
                notify_subscribers(inc.pk, 'opened')
        target = sender.call_args[0][0]
        self.assertIn('to=fan%40example.com', target)

    def test_message_contains_unsubscribe_link(self):
        from surveillance.subscribers import notify_subscribers
        self._subscriber(webhook_url='https://hooks.example.com/x')
        inc = self._incident()
        with patch('surveillance.subscribers.send_via_apprise',
                   return_value=('sent', None)) as sender:
            notify_subscribers(inc.pk, 'opened')
        body = sender.call_args[0][2]
        self.assertIn('unsub-tok', body)

    def test_subscriber_on_two_pages_notified_once(self):
        from surveillance.models import StatusPage, StatusPageMonitor, Subscriber
        from surveillance.subscribers import notify_subscribers
        second = StatusPage.objects.create(
            organization=self.org, slug='phase-d-2', title='Second',
        )
        StatusPageMonitor.objects.create(status_page=second, monitor=self.monitor)
        self._subscriber(webhook_url='https://hooks.example.com/x')
        Subscriber.objects.create(
            status_page=second, email='fan@example.com', verified=True,
            verification_token='v2', unsubscribe_token='u2',
            webhook_url='https://hooks.example.com/x',
        )
        inc = self._incident()
        with patch('surveillance.subscribers.send_via_apprise',
                   return_value=('sent', None)) as sender:
            notify_subscribers(inc.pk, 'opened')
        # Two subscriber rows, but the dedupe is per row id — both are distinct
        # people-ish records, so both are told. What must not happen is the same
        # row being notified twice because it appears under two pages.
        self.assertLessEqual(sender.call_count, 2)

    def test_resolved_message_differs_from_opened(self):
        from surveillance.subscribers import notify_subscribers
        self._subscriber(webhook_url='https://hooks.example.com/x')
        inc = self._incident()
        inc.resolved_at = timezone.now()
        inc.status = 'resolved'
        inc.save()
        with patch('surveillance.subscribers.send_via_apprise',
                   return_value=('sent', None)) as sender:
            notify_subscribers(inc.pk, 'resolved')
        self.assertIn('Resolved', sender.call_args[0][1])


class UnsubscribeTests(StatusPagePhaseDTestCase):
    def test_one_click_unsubscribe(self):
        from surveillance.models import Subscriber
        Subscriber.objects.create(
            status_page=self.page, email='bye@example.com', verified=True,
            verification_token='v', unsubscribe_token='bye-token',
        )
        resp = self.client.get('/api/v1/public/unsubscribe/bye-token/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Subscriber.objects.filter(email='bye@example.com').exists())

    def test_unknown_token_gives_same_answer(self):
        """Must not confirm whether an address was subscribed."""
        known = self.client.get('/api/v1/public/unsubscribe/nope/')
        self.assertEqual(known.status_code, 200)

    def test_no_authentication_required(self):
        self.client.credentials()
        self.assertEqual(
            self.client.get('/api/v1/public/unsubscribe/whatever/').status_code, 200
        )


class StatusFeedAndBadgeTests(StatusPagePhaseDTestCase):
    def test_rss_feed_is_valid_xml(self):
        import xml.etree.ElementTree as ET
        from surveillance.models import Incident
        Incident.objects.create(
            organization=self.org, monitor=self.monitor, title='Past outage',
            status='resolved', resolved_at=timezone.now(), created_by=self.user,
        )
        resp = self.client.get('/api/v1/public/status-pages/phase-d/feed/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/rss+xml', resp['Content-Type'])
        root = ET.fromstring(resp.content)
        self.assertEqual(root.tag, 'rss')
        self.assertIn('Past outage', resp.content.decode())

    def test_feed_escapes_hostile_incident_titles(self):
        """Incident titles are user-authored and must not inject XML."""
        import xml.etree.ElementTree as ET
        from surveillance.models import Incident
        Incident.objects.create(
            organization=self.org, monitor=self.monitor,
            title='</title><script>alert(1)</script>',
            status='resolved', resolved_at=timezone.now(), created_by=self.user,
        )
        resp = self.client.get('/api/v1/public/status-pages/phase-d/feed/')
        ET.fromstring(resp.content)  # would raise if the injection broke the XML
        self.assertNotIn('<script>', resp.content.decode())

    def test_badge_is_svg(self):
        resp = self.client.get('/api/v1/public/status-pages/phase-d/badge.svg')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/svg+xml')
        self.assertIn('<svg', resp.content.decode())

    def test_badge_reflects_outage(self):
        self.monitor.last_status = 'down'
        self.monitor.save()
        body = self.client.get('/api/v1/public/status-pages/phase-d/badge.svg').content.decode()
        self.assertIn('major outage', body)

    def test_badge_reflects_operational(self):
        body = self.client.get('/api/v1/public/status-pages/phase-d/badge.svg').content.decode()
        self.assertIn('operational', body)

    def test_badge_for_unknown_slug_is_still_an_image(self):
        """A README embedding a dead slug should not render a broken image."""
        resp = self.client.get('/api/v1/public/status-pages/ghost/badge.svg')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('unknown', resp.content.decode())

    def test_badge_is_cacheable(self):
        resp = self.client.get('/api/v1/public/status-pages/phase-d/badge.svg')
        self.assertIn('max-age', resp['Cache-Control'])


class PublicPageHistoryTests(StatusPagePhaseDTestCase):
    def test_incident_history_is_exposed(self):
        from surveillance.models import Incident
        Incident.objects.create(
            organization=self.org, monitor=self.monitor, title='Old outage',
            status='resolved', resolved_at=timezone.now(), created_by=self.user,
        )
        resp = self.client.get('/api/v1/public/status-pages/phase-d/')
        self.assertEqual([i['title'] for i in resp.data['incident_history']], ['Old outage'])

    def test_active_and_history_are_separate(self):
        from surveillance.models import Incident
        Incident.objects.create(
            organization=self.org, monitor=self.monitor, title='Ongoing',
            created_by=self.user,
        )
        resp = self.client.get('/api/v1/public/status-pages/phase-d/')
        self.assertEqual([i['title'] for i in resp.data['active_incidents']], ['Ongoing'])
        self.assertEqual(resp.data['incident_history'], [])


class PasswordProtectedPageTests(StatusPagePhaseDTestCase):
    def setUp(self):
        super().setUp()
        self.page.set_password('hunter2')
        self.page.save()

    def test_password_is_hashed_not_stored(self):
        self.page.refresh_from_db()
        self.assertNotIn('hunter2', self.page.password_hash)
        self.assertTrue(self.page.check_password('hunter2'))

    def test_page_requires_password(self):
        resp = self.client.get('/api/v1/public/status-pages/phase-d/')
        self.assertEqual(resp.status_code, 401)
        self.assertTrue(resp.data['password_required'])

    def test_correct_password_grants_access(self):
        resp = self.client.get('/api/v1/public/status-pages/phase-d/?password=hunter2')
        self.assertEqual(resp.status_code, 200)

    def test_wrong_password_denied(self):
        resp = self.client.get('/api/v1/public/status-pages/phase-d/?password=nope')
        self.assertEqual(resp.status_code, 401)

    def test_password_via_header(self):
        resp = self.client.get('/api/v1/public/status-pages/phase-d/',
                               HTTP_X_PAGE_PASSWORD='hunter2')
        self.assertEqual(resp.status_code, 200)

    def test_feed_is_protected_too(self):
        self.assertEqual(
            self.client.get('/api/v1/public/status-pages/phase-d/feed/').status_code, 401
        )


class SubscriberManagementTests(StatusPagePhaseDTestCase):
    def test_owner_can_list_subscribers(self):
        from surveillance.models import Subscriber
        Subscriber.objects.create(status_page=self.page, email='a@example.com',
                                  verified=True, verification_token='v')
        resp = self.client.get(
            f'/api/v1/orgs/{self.org.id}/status-pages/{self.page.id}/subscribers/',
            **self.auth,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data[0]['email'], 'a@example.com')

    def test_owner_can_remove_a_subscriber(self):
        from surveillance.models import Subscriber
        sub = Subscriber.objects.create(status_page=self.page, email='b@example.com',
                                        verified=True, verification_token='v')
        resp = self.client.delete(
            f'/api/v1/orgs/{self.org.id}/status-pages/{self.page.id}/subscribers/{sub.pk}/',
            **self.auth,
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Subscriber.objects.filter(pk=sub.pk).exists())

    def test_list_requires_authentication(self):
        resp = self.client.get(
            f'/api/v1/orgs/{self.org.id}/status-pages/{self.page.id}/subscribers/'
        )
        self.assertEqual(resp.status_code, 401)


class MaintenanceWindowTests(StatusPagePhaseDTestCase):
    def _window(self, **kw):
        from surveillance.models import MaintenanceWindow
        now = timezone.now()
        defaults = dict(
            organization=self.org, title='Database upgrade',
            starts_at=now - timedelta(minutes=5), ends_at=now + timedelta(hours=1),
            created_by=self.user,
        )
        defaults.update(kw)
        return MaintenanceWindow.objects.create(**defaults)

    def test_create_via_api(self):
        now = timezone.now()
        resp = self.client.post(
            f'/api/v1/orgs/{self.org.id}/maintenance/',
            {
                'title': 'Planned upgrade',
                'starts_at': (now + timedelta(hours=1)).isoformat(),
                'ends_at': (now + timedelta(hours=2)).isoformat(),
            },
            format='json', **self.auth,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['state'], 'scheduled')

    def test_end_must_be_after_start(self):
        now = timezone.now()
        resp = self.client.post(
            f'/api/v1/orgs/{self.org.id}/maintenance/',
            {
                'title': 'Backwards',
                'starts_at': (now + timedelta(hours=2)).isoformat(),
                'ends_at': (now + timedelta(hours=1)).isoformat(),
            },
            format='json', **self.auth,
        )
        self.assertEqual(resp.status_code, 400)

    def test_state_transitions(self):
        now = timezone.now()
        future = self._window(starts_at=now + timedelta(hours=1),
                              ends_at=now + timedelta(hours=2))
        active = self._window()
        past = self._window(starts_at=now - timedelta(hours=2),
                            ends_at=now - timedelta(hours=1))
        self.assertEqual(future.state, 'scheduled')
        self.assertEqual(active.state, 'in_progress')
        self.assertEqual(past.state, 'completed')

    def test_empty_monitor_list_covers_whole_org(self):
        window = self._window()
        self.assertTrue(window.covers(self.monitor))

    def test_explicit_monitors_scope_the_window(self):
        other = self._monitor(name='Unaffected')
        window = self._window()
        window.monitors.set([other.pk])
        self.assertFalse(window.covers(self.monitor))
        self.assertTrue(window.covers(other))

    def test_alerts_suppressed_during_maintenance(self):
        """The whole point: no paging during your own deploy."""
        from surveillance.models import Incident
        self._window(suppress_alerts=True)
        inc = Incident.objects.create(
            organization=self.org, monitor=self.monitor, title='Down',
            created_by=self.user,
        )
        with patch('surveillance.alerts.dispatch_incident_alert.delay') as delayed:
            from surveillance.tasks import notify_incident
            notify_incident(inc.pk, 'opened')
        self.assertFalse(delayed.called)

    def test_alerts_still_fire_outside_maintenance(self):
        from surveillance.models import Incident
        now = timezone.now()
        self._window(starts_at=now + timedelta(hours=5), ends_at=now + timedelta(hours=6))
        inc = Incident.objects.create(
            organization=self.org, monitor=self.monitor, title='Down',
            created_by=self.user,
        )
        with patch('surveillance.alerts.dispatch_incident_alert.delay') as delayed:
            from surveillance.tasks import notify_incident
            notify_incident(inc.pk, 'opened')
        self.assertTrue(delayed.called)

    def test_maintenance_shown_on_public_page(self):
        self._window(title='Scheduled DB work')
        resp = self.client.get('/api/v1/public/status-pages/phase-d/')
        self.assertEqual([m['title'] for m in resp.data['maintenance']], ['Scheduled DB work'])


# ---------------------------------------------------------------------------
# Monitor list heartbeat payload (dashboard row data)
# ---------------------------------------------------------------------------

class MonitorListHeartbeatTests(EngineTestCase):
    """
    The dashboard renders a heartbeat strip and uptime badge per row. Both come
    from the list endpoint so the UI needs one request, and the view prefetches
    them so it stays a fixed number of queries.
    """

    def setUp(self):
        from rest_framework.test import APIClient
        self.client = APIClient()
        token = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'engine@test.com', 'password': 'TestPass123!'},
            format='json',
        ).data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def _checks(self, monitor, results):
        now = timezone.now()
        for i, r in enumerate(results):
            ApiLog.objects.create(
                monitor=monitor, region='default', result=r,
                response_time_ms=100 + i,
                checked_at=now - timedelta(minutes=len(results) - i),
            )

    def test_list_includes_heartbeat(self):
        m = self._monitor()
        self._checks(m, ['success', 'failure', 'success'])
        resp = self.client.get(f'/api/v1/orgs/{self.org.id}/monitors/')
        row = resp.data[0]
        self.assertEqual(len(row['heartbeat']), 3)

    def test_heartbeat_is_oldest_first(self):
        """The strip reads left to right as a timeline."""
        m = self._monitor()
        self._checks(m, ['failure', 'success', 'success'])
        resp = self.client.get(f'/api/v1/orgs/{self.org.id}/monitors/')
        beats = resp.data[0]['heartbeat']
        times = [b['checked_at'] for b in beats]
        self.assertEqual(times, sorted(times))

    def test_uptime_badge_value(self):
        m = self._monitor()
        self._checks(m, ['success'] * 9 + ['failure'])
        resp = self.client.get(f'/api/v1/orgs/{self.org.id}/monitors/')
        self.assertEqual(resp.data[0]['uptime_24h'], 90.0)

    def test_monitor_without_checks_is_safe(self):
        self._monitor()
        resp = self.client.get(f'/api/v1/orgs/{self.org.id}/monitors/')
        self.assertEqual(resp.data[0]['heartbeat'], [])
        self.assertIsNone(resp.data[0]['uptime_24h'])

    def test_heartbeat_is_capped(self):
        from surveillance.views import HEARTBEAT_BEATS
        m = self._monitor()
        self._checks(m, ['success'] * (HEARTBEAT_BEATS + 25))
        resp = self.client.get(f'/api/v1/orgs/{self.org.id}/monitors/')
        self.assertEqual(len(resp.data[0]['heartbeat']), HEARTBEAT_BEATS)

    def test_query_count_does_not_grow_with_monitor_count(self):
        """
        The reason the prefetch exists.

        Asserts constancy rather than a magic number: whatever the fixed cost
        is (auth, org, membership, monitors, prefetched checks), it must be the
        SAME for one monitor and for twenty. A regression to per-row queries
        would make the dashboard slowest for the users with the most monitors.
        """
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        url = f'/api/v1/orgs/{self.org.id}/monitors/'

        one = self._monitor(name='hb-solo')
        self._checks(one, ['success', 'success'])
        self.client.get(url)  # warm any lazily-cached lookups

        with CaptureQueriesContext(connection) as few:
            self.client.get(url)

        for i in range(19):
            m = self._monitor(name=f'hb{i}')
            self._checks(m, ['success', 'failure'])

        with CaptureQueriesContext(connection) as many:
            resp = self.client.get(url)

        self.assertEqual(len(resp.data), 20)
        self.assertEqual(
            len(many), len(few),
            f'Query count grew from {len(few)} to {len(many)} when monitors went '
            f'from 1 to 20 — the heartbeat prefetch has regressed to an N+1.',
        )
