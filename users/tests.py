from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.throttling import SimpleRateThrottle
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from users.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_user(email='user@example.com', password='TestPass123!', **kwargs):
    return User.objects.create_user(
        email=email, password=password,
        first_name='Test', last_name='User',
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Registration Tests
# ---------------------------------------------------------------------------

class RegisterTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_with_valid_data(self):
        resp = self.client.post(
            '/api/v1/auth/register/',
            {
                'email': 'newuser@test.com',
                'password': 'StrongPass123!',
                'first_name': 'New',
                'last_name': 'User',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email='newuser@test.com').exists())

    def test_register_duplicate_email_fails(self):
        create_user(email='dup@test.com')
        resp = self.client.post(
            '/api/v1/auth/register/',
            {
                'email': 'dup@test.com',
                'password': 'StrongPass123!',
                'first_name': 'Dup',
                'last_name': 'User',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_missing_email_fails(self):
        resp = self.client.post(
            '/api/v1/auth/register/',
            {'password': 'StrongPass123!', 'first_name': 'No', 'last_name': 'Email'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_missing_password_fails(self):
        resp = self.client.post(
            '/api/v1/auth/register/',
            {'email': 'nopass@test.com', 'first_name': 'No', 'last_name': 'Pass'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Auth (Login / Token) Tests
# ---------------------------------------------------------------------------

class AuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(email='auth@test.com', password='TestPass123!')

    def test_login_with_valid_credentials(self):
        resp = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'auth@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)

    def test_login_with_wrong_password_fails(self):
        resp = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'auth@test.com', 'password': 'WrongPassword!'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_with_unknown_email_fails(self):
        resp = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'ghost@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_refresh(self):
        login = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'auth@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        refresh_token = login.data['refresh']
        resp = self.client.post(
            '/api/v1/auth/refresh/',
            {'refresh': refresh_token},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)


# ---------------------------------------------------------------------------
# Profile Tests  GET /api/v1/auth/me/
# ---------------------------------------------------------------------------

class ProfileTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user(email='profile@test.com', password='TestPass123!')

    def _get_token(self):
        resp = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'profile@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        return resp.data['access']

    def test_authenticated_user_can_get_profile(self):
        token = self._get_token()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        resp = self.client.get('/api/v1/auth/me/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['email'], 'profile@test.com')
        self.assertIn('first_name', resp.data)
        self.assertIn('last_name', resp.data)

    def test_unauthenticated_user_cannot_get_profile(self):
        resp = self.client.get('/api/v1/auth/me/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_expired_token_cannot_get_profile(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer invalid.token.here')
        resp = self.client.get('/api/v1/auth/me/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Logout Tests  POST /api/v1/auth/logout/
# ---------------------------------------------------------------------------

class LogoutTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user('logout@test.com', 'TestPass123!')
        resp = self.client.post(
            '/api/v1/auth/login/',
            {'email': 'logout@test.com', 'password': 'TestPass123!'},
            format='json',
        )
        self.access = resp.data['access']
        self.refresh = resp.data['refresh']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access}')

    def test_logout_blacklists_refresh_token(self):
        resp = self.client.post(
            '/api/v1/auth/logout/', {'refresh': self.refresh}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_205_RESET_CONTENT)

        # The blacklisted refresh token must no longer mint access tokens.
        refresh_resp = self.client.post(
            '/api/v1/auth/refresh/', {'refresh': self.refresh}, format='json'
        )
        self.assertEqual(refresh_resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_without_refresh_returns_400(self):
        resp = self.client.post('/api/v1/auth/logout/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_with_garbage_refresh_returns_400(self):
        resp = self.client.post(
            '/api/v1/auth/logout/', {'refresh': 'not-a-token'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_double_logout_returns_400(self):
        self.client.post('/api/v1/auth/logout/', {'refresh': self.refresh}, format='json')
        resp = self.client.post(
            '/api/v1/auth/logout/', {'refresh': self.refresh}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_cannot_logout(self):
        self.client.credentials()
        resp = self.client.post(
            '/api/v1/auth/logout/', {'refresh': self.refresh}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Throttling Tests
# ---------------------------------------------------------------------------

class LoginThrottleTests(TestCase):
    """
    The suite runs with throttling disabled (see settings.TESTING); this class
    turns it back on. DRF binds THROTTLE_RATES onto the throttle class at
    import time, so override_settings cannot reach it — patch the attribute.
    """

    def setUp(self):
        self.client = APIClient()
        create_user('throttle@test.com', 'TestPass123!')
        cache.clear()
        patcher = mock.patch.object(
            SimpleRateThrottle, 'THROTTLE_RATES',
            {'login': '5/min', 'register': '10/hour', 'subscribe': '10/hour'},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(cache.clear)

    def test_sixth_login_attempt_is_throttled(self):
        payload = {'email': 'throttle@test.com', 'password': 'WrongPassword!'}
        codes = [
            self.client.post('/api/v1/auth/login/', payload, format='json').status_code
            for _ in range(6)
        ]
        self.assertEqual(codes[:5], [status.HTTP_401_UNAUTHORIZED] * 5)
        self.assertEqual(codes[5], status.HTTP_429_TOO_MANY_REQUESTS)

    def test_throttle_applies_to_successful_logins_too(self):
        payload = {'email': 'throttle@test.com', 'password': 'TestPass123!'}
        for _ in range(5):
            self.client.post('/api/v1/auth/login/', payload, format='json')
        resp = self.client.post('/api/v1/auth/login/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
