from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status

from users.models import User
from organizations.models import Organization, OrganizationRole, OrganizationMember


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_user(email='user@test.com', password='TestPass123!', **kwargs):
    return User.objects.create_user(email=email, password=password,
                                    first_name='Test', last_name='User', **kwargs)


def create_org(name='Test Org'):
    return Organization.objects.create(name=name)


def get_tokens(client, email, password):
    """Obtain JWT access token."""
    resp = client.post('/api/v1/auth/login/', {'email': email, 'password': password}, format='json')
    return resp.data.get('access')


def auth_client(client, token):
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return client


# ---------------------------------------------------------------------------
# Setup: ensure roles exist before each test class
# ---------------------------------------------------------------------------

class BaseOrgTestCase(TestCase):
    """Base class that seeds OrganizationRole fixtures."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_role, _ = OrganizationRole.objects.get_or_create(name='admin')
        cls.member_role, _ = OrganizationRole.objects.get_or_create(name='member')


# ---------------------------------------------------------------------------
# Health Endpoint Tests
# ---------------------------------------------------------------------------

class HealthEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_liveness_returns_200(self):
        resp = self.client.get('/api/v1/health/live/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'ok')

    def test_readiness_returns_200_or_503(self):
        resp = self.client.get('/api/v1/health/ready/')
        # In test environment DB is available
        self.assertIn(resp.status_code, [status.HTTP_200_OK, status.HTTP_503_SERVICE_UNAVAILABLE])
        self.assertIn(resp.data['status'], ['ok', 'error'])

    def test_liveness_no_auth_required(self):
        """Liveness must be accessible without authentication."""
        resp = self.client.get('/api/v1/health/live/')
        self.assertNotEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# Organization Detail Tests  GET /api/v1/organizations/{orgId}/
# ---------------------------------------------------------------------------

class OrganizationDetailTests(BaseOrgTestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = create_user('admin@test.com', 'TestPass123!')
        self.member = create_user('member@test.com', 'TestPass123!')
        self.outsider = create_user('outside@test.com', 'TestPass123!')
        self.org = create_org('Alpha Corp')

        OrganizationMember.objects.create(
            users=self.admin, organizations=self.org, role=self.admin_role
        )
        OrganizationMember.objects.create(
            users=self.member, organizations=self.org, role=self.member_role
        )

        self.admin_token = get_tokens(self.client, 'admin@test.com', 'TestPass123!')
        self.member_token = get_tokens(self.client, 'member@test.com', 'TestPass123!')
        self.outsider_token = get_tokens(self.client, 'outside@test.com', 'TestPass123!')

    def test_member_can_get_org_details(self):
        auth_client(self.client, self.member_token)
        resp = self.client.get(f'/api/v1/organizations/{self.org.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['name'], 'Alpha Corp')
        self.assertIn('id', resp.data)
        self.assertIn('settings', resp.data)

    def test_admin_can_get_org_details(self):
        auth_client(self.client, self.admin_token)
        resp = self.client.get(f'/api/v1/organizations/{self.org.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_outsider_cannot_get_org_details(self):
        auth_client(self.client, self.outsider_token)
        resp = self.client.get(f'/api/v1/organizations/{self.org.id}/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_get_org_details(self):
        self.client.credentials()
        resp = self.client.get(f'/api/v1/organizations/{self.org.id}/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_nonexistent_org_returns_404(self):
        auth_client(self.client, self.admin_token)
        resp = self.client.get('/api/v1/organizations/99999/')
        self.assertIn(resp.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN])


# ---------------------------------------------------------------------------
# Organization Update Tests  PATCH /api/v1/organizations/{orgId}/
# ---------------------------------------------------------------------------

class OrganizationUpdateTests(BaseOrgTestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = create_user('admin2@test.com', 'TestPass123!')
        self.member = create_user('member2@test.com', 'TestPass123!')
        self.org = create_org('Beta Corp')

        OrganizationMember.objects.create(
            users=self.admin, organizations=self.org, role=self.admin_role
        )
        OrganizationMember.objects.create(
            users=self.member, organizations=self.org, role=self.member_role
        )

        self.admin_token = get_tokens(self.client, 'admin2@test.com', 'TestPass123!')
        self.member_token = get_tokens(self.client, 'member2@test.com', 'TestPass123!')

    def test_admin_can_update_org_name(self):
        auth_client(self.client, self.admin_token)
        resp = self.client.patch(
            f'/api/v1/organizations/{self.org.id}/',
            {'name': 'Beta Corp Renamed'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['name'], 'Beta Corp Renamed')

    def test_admin_can_update_org_settings(self):
        auth_client(self.client, self.admin_token)
        resp = self.client.patch(
            f'/api/v1/organizations/{self.org.id}/',
            {'settings': {'feature_x': True}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['settings']['feature_x'], True)

    def test_member_cannot_update_org(self):
        auth_client(self.client, self.member_token)
        resp = self.client.patch(
            f'/api/v1/organizations/{self.org.id}/',
            {'name': 'Hacked Name'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# Member List Tests  GET /api/v1/organizations/{orgId}/members/
# ---------------------------------------------------------------------------

class OrganizationMemberListTests(BaseOrgTestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = create_user('admin3@test.com', 'TestPass123!')
        self.member = create_user('member3@test.com', 'TestPass123!')
        self.outsider = create_user('outsider3@test.com', 'TestPass123!')
        self.org = create_org('Gamma Corp')

        OrganizationMember.objects.create(
            users=self.admin, organizations=self.org, role=self.admin_role
        )
        OrganizationMember.objects.create(
            users=self.member, organizations=self.org, role=self.member_role
        )

        self.admin_token = get_tokens(self.client, 'admin3@test.com', 'TestPass123!')
        self.member_token = get_tokens(self.client, 'member3@test.com', 'TestPass123!')
        self.outsider_token = get_tokens(self.client, 'outsider3@test.com', 'TestPass123!')

    def test_member_can_list_members(self):
        auth_client(self.client, self.member_token)
        resp = self.client.get(f'/api/v1/organizations/{self.org.id}/members/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('members', resp.data)
        self.assertEqual(len(resp.data['members']), 2)

    def test_admin_can_list_members(self):
        auth_client(self.client, self.admin_token)
        resp = self.client.get(f'/api/v1/organizations/{self.org.id}/members/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_outsider_cannot_list_members(self):
        auth_client(self.client, self.outsider_token)
        resp = self.client.get(f'/api/v1/organizations/{self.org.id}/members/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_list_includes_role(self):
        auth_client(self.client, self.admin_token)
        resp = self.client.get(f'/api/v1/organizations/{self.org.id}/members/')
        roles = [m['role'] for m in resp.data['members']]
        self.assertIn('admin', roles)
        self.assertIn('member', roles)


# ---------------------------------------------------------------------------
# Member Invite Tests  POST /api/v1/organizations/{orgId}/members/invite/
# ---------------------------------------------------------------------------

class OrganizationMemberInviteTests(BaseOrgTestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = create_user('admin4@test.com', 'TestPass123!')
        self.regular = create_user('regular4@test.com', 'TestPass123!')
        self.invitee = create_user('invitee4@test.com', 'TestPass123!')
        self.org = create_org('Delta Corp')

        OrganizationMember.objects.create(
            users=self.admin, organizations=self.org, role=self.admin_role
        )
        OrganizationMember.objects.create(
            users=self.regular, organizations=self.org, role=self.member_role
        )

        self.admin_token = get_tokens(self.client, 'admin4@test.com', 'TestPass123!')
        self.regular_token = get_tokens(self.client, 'regular4@test.com', 'TestPass123!')

    def test_admin_can_invite_user_by_email(self):
        auth_client(self.client, self.admin_token)
        resp = self.client.post(
            f'/api/v1/organizations/{self.org.id}/members/invite/',
            {'email': 'invitee4@test.com', 'role': 'member'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            OrganizationMember.objects.filter(
                users=self.invitee, organizations=self.org
            ).exists()
        )

    def test_member_cannot_invite(self):
        auth_client(self.client, self.regular_token)
        resp = self.client.post(
            f'/api/v1/organizations/{self.org.id}/members/invite/',
            {'email': 'invitee4@test.com', 'role': 'member'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_invite_nonexistent_email_returns_400(self):
        auth_client(self.client, self.admin_token)
        resp = self.client.post(
            f'/api/v1/organizations/{self.org.id}/members/invite/',
            {'email': 'ghost@nowhere.com', 'role': 'member'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invite_already_member_returns_409(self):
        auth_client(self.client, self.admin_token)
        resp = self.client.post(
            f'/api/v1/organizations/{self.org.id}/members/invite/',
            {'email': 'regular4@test.com', 'role': 'member'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_invite_invalid_role_returns_400(self):
        auth_client(self.client, self.admin_token)
        resp = self.client.post(
            f'/api/v1/organizations/{self.org.id}/members/invite/',
            {'email': 'invitee4@test.com', 'role': 'supervillain'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Member Remove Tests  DELETE /api/v1/organizations/{orgId}/members/{userId}/
# ---------------------------------------------------------------------------

class OrganizationMemberRemoveTests(BaseOrgTestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = create_user('admin5@test.com', 'TestPass123!')
        self.member = create_user('member5@test.com', 'TestPass123!')
        self.outsider = create_user('outsider5@test.com', 'TestPass123!')
        self.org = create_org('Epsilon Corp')

        OrganizationMember.objects.create(
            users=self.admin, organizations=self.org, role=self.admin_role
        )
        self.member_record = OrganizationMember.objects.create(
            users=self.member, organizations=self.org, role=self.member_role
        )

        self.admin_token = get_tokens(self.client, 'admin5@test.com', 'TestPass123!')
        self.member_token = get_tokens(self.client, 'member5@test.com', 'TestPass123!')

    def test_admin_can_remove_member(self):
        auth_client(self.client, self.admin_token)
        resp = self.client.delete(
            f'/api/v1/organizations/{self.org.id}/members/{self.member.id}/'
        )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(
            OrganizationMember.objects.filter(
                users=self.member, organizations=self.org
            ).exists()
        )

    def test_member_cannot_remove_other_member(self):
        auth_client(self.client, self.member_token)
        resp = self.client.delete(
            f'/api/v1/organizations/{self.org.id}/members/{self.admin.id}/'
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_remove_last_admin(self):
        auth_client(self.client, self.admin_token)
        resp = self.client.delete(
            f'/api/v1/organizations/{self.org.id}/members/{self.admin.id}/'
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_remove_nonexistent_member_returns_404(self):
        auth_client(self.client, self.admin_token)
        resp = self.client.delete(
            f'/api/v1/organizations/{self.org.id}/members/99999/'
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# Multi-Tenant Middleware Tests
# ---------------------------------------------------------------------------

class OrganizationMiddlewareTests(BaseOrgTestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = create_user('mw@test.com', 'TestPass123!')
        self.org = create_org('Middleware Corp')
        OrganizationMember.objects.create(
            users=self.user, organizations=self.org, role=self.admin_role
        )
        self.token = get_tokens(self.client, 'mw@test.com', 'TestPass123!')

    def test_middleware_returns_404_for_nonexistent_org(self):
        """The middleware should intercept and return 404 before the view runs."""
        auth_client(self.client, self.token)
        resp = self.client.get('/api/v1/organizations/99999/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_middleware_passes_through_valid_org(self):
        auth_client(self.client, self.token)
        resp = self.client.get(f'/api/v1/organizations/{self.org.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# New user onboarding  GET/POST /api/v1/organizations/
# ---------------------------------------------------------------------------

class NewUserOnboardingTests(BaseOrgTestCase):
    """
    A freshly registered user belongs to no organization. They must still be
    able to list (empty) and create their first one — guarding the list with
    IsOrgMember made this impossible and locked new accounts out entirely.
    """

    def setUp(self):
        self.client = APIClient()
        create_user('newbie@test.com', 'TestPass123!')
        self.token = get_tokens(self.client, 'newbie@test.com', 'TestPass123!')
        auth_client(self.client, self.token)

    def test_user_with_no_orgs_can_list_orgs(self):
        resp = self.client.get('/api/v1/organizations/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, [])

    def test_user_with_no_orgs_can_create_first_org(self):
        resp = self.client.post(
            '/api/v1/organizations/', {'name': 'First Org'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['name'], 'First Org')

    def test_creator_becomes_admin(self):
        resp = self.client.post(
            '/api/v1/organizations/', {'name': 'Admin Org'}, format='json'
        )
        member = OrganizationMember.objects.get(organizations_id=resp.data['id'])
        self.assertEqual(member.users.email, 'newbie@test.com')
        self.assertEqual(member.role.name, 'admin')

    def test_created_org_appears_in_list(self):
        self.client.post('/api/v1/organizations/', {'name': 'Listed Org'}, format='json')
        resp = self.client.get('/api/v1/organizations/')
        self.assertEqual([o['name'] for o in resp.data], ['Listed Org'])

    def test_creator_can_immediately_use_the_new_org(self):
        """The whole point: create an org, then work inside it."""
        org_id = self.client.post(
            '/api/v1/organizations/', {'name': 'Usable Org'}, format='json'
        ).data['id']

        self.assertEqual(
            self.client.get(f'/api/v1/orgs/{org_id}/monitors/').status_code,
            status.HTTP_200_OK,
        )
        created = self.client.post(
            f'/api/v1/orgs/{org_id}/monitors/',
            {'name': 'First Monitor', 'url': 'https://example.com'},
            format='json',
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

    def test_list_still_excludes_other_users_orgs(self):
        """Removing the permission must not widen what the list returns."""
        other = create_user('other@test.com', 'TestPass123!')
        foreign = create_org('Someone Elses Org')
        OrganizationMember.objects.create(
            users=other, organizations=foreign, role=self.admin_role
        )

        resp = self.client.get('/api/v1/organizations/')
        self.assertEqual(resp.data, [])

    def test_unauthenticated_still_rejected(self):
        self.client.credentials()
        self.assertEqual(
            self.client.get('/api/v1/organizations/').status_code,
            status.HTTP_401_UNAUTHORIZED,
        )


# ---------------------------------------------------------------------------
# Member list payload shape
# ---------------------------------------------------------------------------

class MemberPayloadShapeTests(BaseOrgTestCase):
    """
    The member list nests the profile under `users` and must also carry
    `user_id`. The remove endpoint is keyed on the user, not the membership
    row, so a payload without `user_id` makes the UI's remove action
    impossible to build correctly.
    """

    def setUp(self):
        self.client = APIClient()
        self.admin = create_user('shape-admin@test.com', 'TestPass123!')
        self.member = create_user('shape-member@test.com', 'TestPass123!')
        self.org = create_org('Shape Org')
        OrganizationMember.objects.create(
            users=self.admin, organizations=self.org, role=self.admin_role
        )
        OrganizationMember.objects.create(
            users=self.member, organizations=self.org, role=self.member_role
        )
        auth_client(self.client, get_tokens(self.client, 'shape-admin@test.com', 'TestPass123!'))

    def _members(self):
        return self.client.get(f'/api/v1/organizations/{self.org.id}/members/').data['members']

    def test_each_member_has_a_stable_unique_id(self):
        ids = [m['id'] for m in self._members()]
        self.assertTrue(all(i is not None for i in ids))
        self.assertEqual(len(ids), len(set(ids)))

    def test_each_member_exposes_user_id(self):
        for m in self._members():
            self.assertIsNotNone(m['user_id'])

    def test_user_id_differs_from_membership_id(self):
        """They are separate tables; conflating them would delete the wrong row."""
        entry = next(m for m in self._members() if m['users']['email'] == 'shape-member@test.com')
        self.assertEqual(entry['user_id'], self.member.id)

    def test_profile_is_nested_under_users(self):
        entry = self._members()[0]
        self.assertIn('email', entry['users'])
        self.assertIn('first_name', entry['users'])

    def test_user_id_from_payload_removes_the_right_member(self):
        entry = next(m for m in self._members() if m['users']['email'] == 'shape-member@test.com')
        resp = self.client.delete(
            f'/api/v1/organizations/{self.org.id}/members/{entry["user_id"]}/'
        )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual([m['users']['email'] for m in self._members()],
                         ['shape-admin@test.com'])
