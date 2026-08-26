"""
Regression tests for the security review findings.

Each test here corresponds to something that was exploitable. They are the
reason these fixes can't silently rot: the SSRF bypasses in particular are easy
to reintroduce by "simplifying" the validator back to a string comparison.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework import serializers as drf_serializers
from rest_framework.test import APIClient
from rest_framework import status as http_status

from organizations.models import Organization, OrganizationMember, OrganizationRole
from surveillance.models import AlertChannel, Monitor
from surveillance.net import (
    BlockedTargetError,
    is_blocked_ip,
    validate_outbound_url,
)
import surveillance.tasks as tasks_module
from surveillance.serializers import validate_monitor_url
from users.models import User
from users.serializers import RegisterSerializer


# ---------------------------------------------------------------------------
# VULN-001 — SSRF containment
# ---------------------------------------------------------------------------

class BlockedAddressTests(TestCase):
    """The IP-range floor, independent of DNS."""

    def test_loopback_blocked(self):
        for ip in ('127.0.0.1', '127.0.0.2', '127.255.255.254'):
            self.assertTrue(is_blocked_ip(ip), ip)

    def test_cloud_metadata_blocked(self):
        self.assertTrue(is_blocked_ip('169.254.169.254'))

    def test_private_ranges_blocked(self):
        for ip in ('10.0.0.1', '172.16.0.1', '172.31.255.255', '192.168.1.1'):
            self.assertTrue(is_blocked_ip(ip), ip)

    def test_cgnat_blocked(self):
        self.assertTrue(is_blocked_ip('100.64.0.1'))

    def test_ipv6_loopback_and_private_blocked(self):
        for ip in ('::1', 'fc00::1', 'fe80::1'):
            self.assertTrue(is_blocked_ip(ip), ip)

    def test_ipv4_mapped_ipv6_blocked(self):
        """::ffff:127.0.0.1 must be judged as the IPv4 address it wraps."""
        self.assertTrue(is_blocked_ip('::ffff:127.0.0.1'))
        self.assertTrue(is_blocked_ip('::ffff:169.254.169.254'))

    def test_unparseable_input_blocked(self):
        self.assertTrue(is_blocked_ip('not-an-ip'))

    def test_public_addresses_allowed(self):
        for ip in ('1.1.1.1', '93.184.216.34', '2606:4700:4700::1111'):
            self.assertFalse(is_blocked_ip(ip), ip)


class SSRFUrlValidationTests(TestCase):
    """
    Every one of these was ACCEPTED before the fix. The old check compared the
    hostname string against three literals, so any alternate encoding walked
    straight past it.
    """

    def _assert_blocked(self, url):
        with self.assertRaises(BlockedTargetError, msg=f'{url} was not blocked'):
            validate_outbound_url(url)

    def test_metadata_endpoint_blocked(self):
        self._assert_blocked('http://169.254.169.254/latest/meta-data/')

    def test_localhost_blocked(self):
        self._assert_blocked('http://localhost:8000/admin/')

    def test_loopback_variants_blocked(self):
        self._assert_blocked('http://127.0.0.1:6380/')
        self._assert_blocked('http://127.0.0.2:8000/')

    def test_decimal_encoded_loopback_blocked(self):
        """2130706433 == 127.0.0.1. getaddrinfo resolves it; the range check catches it."""
        self._assert_blocked('http://2130706433:8000/')

    def test_ipv6_loopback_blocked(self):
        self._assert_blocked('http://[::1]:8000/')

    def test_ipv4_mapped_ipv6_blocked(self):
        self._assert_blocked('http://[::ffff:127.0.0.1]/')

    def test_private_ranges_blocked(self):
        self._assert_blocked('http://10.0.0.1/')
        self._assert_blocked('http://192.168.1.1:22/')

    def test_gcp_metadata_hostname_blocked(self):
        self._assert_blocked('https://metadata.google.internal/')

    def test_non_http_scheme_blocked(self):
        self._assert_blocked('file:///etc/passwd')
        self._assert_blocked('gopher://127.0.0.1:6379/')

    def test_credentials_in_url_blocked(self):
        self._assert_blocked('https://user:pass@example.com/')

    def test_unresolvable_host_blocked(self):
        self._assert_blocked('https://this-host-does-not-exist.invalid/')

    def test_public_url_allowed(self):
        self.assertEqual(
            validate_outbound_url('https://example.com/health'),
            'https://example.com/health',
        )

    @override_settings(MONITOR_ALLOW_INTERNAL_TARGETS=True)
    def test_operator_can_opt_in_to_internal_targets(self):
        """Self-hosters monitoring their own LAN need this; it is off by default."""
        self.assertEqual(
            validate_outbound_url('http://192.168.1.10/health'),
            'http://192.168.1.10/health',
        )

    def test_serializer_surfaces_block_as_validation_error(self):
        with self.assertRaises(drf_serializers.ValidationError):
            validate_monitor_url('http://169.254.169.254/')


class RedirectRevalidationTests(TestCase):
    """
    A 30x to an internal address must not be followed. Validating only the
    first URL is the classic way an SSRF filter gets bypassed.
    """

    def setUp(self):
        self.role, _ = OrganizationRole.objects.get_or_create(name='admin')
        self.user = User.objects.create_user(
            email='redirect@test.com', password='TestPass123!',
            first_name='R', last_name='D',
        )
        self.org = Organization.objects.create(name='Redirect Org')
        OrganizationMember.objects.create(
            users=self.user, organizations=self.org, role=self.role
        )
        self.monitor = Monitor.objects.create(
            organization=self.org, name='Redirector',
            url='https://example.com/start', created_by=self.user,
        )

    def _response(self, status_code, location=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.is_redirect = location is not None
        resp.headers = {'Location': location} if location else {}
        resp.elapsed.total_seconds.return_value = 0.01
        return resp

    def test_redirect_into_metadata_endpoint_is_blocked(self):
        from surveillance.tasks import _request_with_guarded_redirects

        with patch.object(tasks_module._session, 'request') as req:
            req.return_value = self._response(302, 'http://169.254.169.254/latest/meta-data/')
            with self.assertRaises(BlockedTargetError):
                _request_with_guarded_redirects(
                    method='GET', url='https://example.com/start', headers={},
                    json_body=None, timeout_s=5, follow_redirects=True,
                )

    def test_redirect_not_followed_when_monitor_disables_it(self):
        from surveillance.tasks import _request_with_guarded_redirects

        with patch.object(tasks_module._session, 'request') as req:
            req.return_value = self._response(302, 'http://127.0.0.1:8000/')
            resp = _request_with_guarded_redirects(
                method='GET', url='https://example.com/start', headers={},
                json_body=None, timeout_s=5, follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(req.call_count, 1)

    def test_requests_own_redirect_handling_is_disabled(self):
        """If allow_redirects were True, per-hop validation would be bypassed."""
        from surveillance.tasks import _request_with_guarded_redirects

        with patch.object(tasks_module._session, 'request') as req:
            req.return_value = self._response(200)
            _request_with_guarded_redirects(
                method='GET', url='https://example.com/', headers={},
                json_body=None, timeout_s=5, follow_redirects=True,
            )
        self.assertFalse(req.call_args.kwargs['allow_redirects'])

    def test_blocked_target_is_recorded_as_a_failed_check(self):
        """The check must fail loudly, not crash the worker."""
        from surveillance.models import ApiLog
        from surveillance.tasks import run_check

        Monitor.objects.filter(pk=self.monitor.pk).update(url='http://169.254.169.254/')
        run_check(self.monitor.pk)

        log = ApiLog.objects.get(monitor=self.monitor)
        self.assertEqual(log.result, 'failure')
        self.assertIn('Blocked target', log.error_message)


# ---------------------------------------------------------------------------
# VULN-002 — alert channel SSRF + response reflection
# ---------------------------------------------------------------------------

class AlertChannelSSRFTests(TestCase):

    def setUp(self):
        self.admin_role, _ = OrganizationRole.objects.get_or_create(name='admin')
        self.user = User.objects.create_user(
            email='chan@test.com', password='TestPass123!',
            first_name='C', last_name='H',
        )
        self.org = Organization.objects.create(name='Channel Org')
        OrganizationMember.objects.create(
            users=self.user, organizations=self.org, role=self.admin_role
        )
        self.client = APIClient()
        resp = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'chan@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')

    def test_internal_webhook_url_rejected(self):
        resp = self.client.post(
            f'/api/v1/orgs/{self.org.id}/alert-channels/',
            {'type': 'slack', 'config': {'url': 'https://127.0.0.1/hook'}},
            format='json',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_metadata_webhook_url_rejected(self):
        resp = self.client.post(
            f'/api/v1/orgs/{self.org.id}/alert-channels/',
            {'type': 'slack', 'config': {'url': 'https://169.254.169.254/hook'}},
            format='json',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_response_body_is_not_reflected_to_caller(self):
        """
        The old code returned resp.text[:200], turning the test endpoint into
        an SSRF that could read internal responses.
        """
        channel = AlertChannel.objects.create(
            organization=self.org, type='slack',
            config={'url': 'https://hooks.slack.com/services/TEST'},
        )
        secret = 'INTERNAL_SECRET_TOKEN_abc123'
        response = MagicMock(status_code=403, text=f'{{"error":"{secret}"}}')

        with patch('surveillance.alerts.requests.post', return_value=response):
            resp = self.client.post(
                f'/api/v1/orgs/{self.org.id}/alert-channels/{channel.id}/test/'
            )

        self.assertEqual(resp.status_code, http_status.HTTP_502_BAD_GATEWAY)
        self.assertNotIn(secret, str(resp.data))
        self.assertIn('403', str(resp.data))

    def test_dispatch_does_not_follow_redirects(self):
        channel = AlertChannel.objects.create(
            organization=self.org, type='slack',
            config={'url': 'https://hooks.slack.com/services/TEST'},
        )
        from surveillance.alerts import post_to_channel

        with patch('surveillance.alerts.requests.post') as post:
            post.return_value = MagicMock(status_code=200, text='ok')
            post_to_channel(channel, {'text': 'hi'})
        self.assertFalse(post.call_args.kwargs['allow_redirects'])

    def test_stored_channel_pointing_internal_is_refused_at_send_time(self):
        """DNS can change after the URL was saved, so re-validate on use."""
        channel = AlertChannel.objects.create(
            organization=self.org, type='slack', config={'url': 'https://127.0.0.1/hook'},
        )
        from surveillance.alerts import post_to_channel

        with patch('surveillance.alerts.requests.post') as post:
            result, error = post_to_channel(channel, {'text': 'hi'})
        self.assertEqual(result, 'failed')
        self.assertFalse(post.called)


# ---------------------------------------------------------------------------
# VULN-003 — password policy
# ---------------------------------------------------------------------------

class PasswordPolicyTests(TestCase):
    """AUTH_PASSWORD_VALIDATORS were configured but never invoked by DRF."""

    def setUp(self):
        self.client = APIClient()

    def _register(self, password):
        return self.client.post(
            '/api/v1/auth/register/',
            {'email': f'pw{abs(hash(password)) % 99999}@test.com', 'password': password,
             'first_name': 'P', 'last_name': 'W'},
            format='json',
        )

    def test_single_character_password_rejected(self):
        self.assertEqual(self._register('1').status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_short_password_rejected(self):
        self.assertEqual(self._register('abc').status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_common_password_rejected(self):
        self.assertEqual(self._register('password').status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_numeric_only_password_rejected(self):
        self.assertEqual(self._register('82736451').status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_strong_password_accepted(self):
        self.assertEqual(self._register('Str0ng!Passw0rd').status_code, http_status.HTTP_201_CREATED)

    def test_error_explains_why(self):
        resp = self._register('1')
        self.assertIn('password', resp.data)

    def test_serializer_level_enforcement(self):
        s = RegisterSerializer(data={'email': 'direct@test.com', 'password': '1',
                                     'first_name': 'D', 'last_name': 'X'})
        self.assertFalse(s.is_valid())


# ---------------------------------------------------------------------------
# VULN-004 — deployment configuration
# ---------------------------------------------------------------------------

class DebugConfigurationTests(TestCase):

    def test_debug_is_not_hardcoded_true(self):
        """
        DEBUG must come from the environment. It was hardcoded True, which
        would leak tracebacks on deploy and also disabled SSRF validation,
        because that check used to be gated on `not DEBUG`.
        """
        import inspect
        import config.settings as settings_module

        source = inspect.getsource(settings_module)
        self.assertNotIn('DEBUG = True', source)
        self.assertIn("env.bool('DEBUG'", source)

    def test_ssrf_protection_is_not_tied_to_debug(self):
        """With DEBUG on, containment must still apply."""
        with override_settings(DEBUG=True):
            with self.assertRaises(BlockedTargetError):
                validate_outbound_url('http://169.254.169.254/')

    def test_allowed_hosts_is_populated(self):
        from django.conf import settings
        self.assertTrue(settings.ALLOWED_HOSTS)
