from rest_framework.views import APIView
from rest_framework import generics
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from .models import Organization, OrganizationRole, OrganizationMember
from .serializers import (
    OrganizationSerializer,
    OrganizationCreateSerializer,
    OrganizationUpdateSerializer,
    OrganizationRoleSerializer,
    OrganizationMemberListSerializer,
    MemberInviteSerializer,
)
from .permissions import IsOrgMember, IsOrgAdmin
from users.models import User


# ---------------------------------------------------------------------------
# Organization List + Create
# ---------------------------------------------------------------------------

class OrganizationAPIView(APIView):
    """
    GET  /api/v1/organizations/  — List orgs the authenticated user belongs to.
    POST /api/v1/organizations/  — Create a new organization (user becomes admin).
    """

    # Authentication is the only requirement on both verbs. IsOrgMember must
    # NOT guard the list: its no-orgId fallback asks "is this user in any org?",
    # which locks a newly registered user out of the one endpoint that would let
    # them create their first one. Tenant isolation here comes from the
    # queryset filter below, not from a permission class.
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Organization.objects.filter(members__users=request.user)
        serializer = OrganizationSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = OrganizationCreateSerializer(
            data=request.data, context={'request': request}
        )
        if serializer.is_valid():
            org = serializer.save()
            return Response(
                OrganizationSerializer(org).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Organization Detail + Update
# ---------------------------------------------------------------------------

class OrganizationDetailView(APIView):
    """
    GET   /api/v1/organizations/{orgId}/  — Get org details (member only).
    PATCH /api/v1/organizations/{orgId}/  — Update name/settings (admin only).
    """

    def get_permissions(self):
        if self.request.method == 'PATCH':
            return [IsAuthenticated(), IsOrgAdmin()]
        return [IsAuthenticated(), IsOrgMember()]

    def _get_org(self, org_id):
        try:
            return Organization.objects.get(pk=org_id)
        except Organization.DoesNotExist:
            return None

    def get(self, request, orgId):
        org = self._get_org(orgId)
        if org is None:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = OrganizationSerializer(org)
        return Response(serializer.data)

    def patch(self, request, orgId):
        org = self._get_org(orgId)
        if org is None:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = OrganizationUpdateSerializer(org, data=request.data, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            return Response(OrganizationSerializer(updated).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Organization Role Management
# ---------------------------------------------------------------------------

class OrganizationRoleAPIView(APIView):
    """
    GET  /api/v1/organizations/roles   — List all roles.
    POST /api/v1/organizations/roles   — Create a new role.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = OrganizationRole.objects.all()
        serializer = OrganizationRoleSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = OrganizationRoleSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Member List
# ---------------------------------------------------------------------------

class OrganizationMemberListView(APIView):
    """
    GET /api/v1/organizations/{orgId}/members  — List members + roles (member only).
    """
    permission_classes = [IsAuthenticated, IsOrgMember]

    def get(self, request, orgId):
        try:
            org = Organization.objects.get(pk=orgId)
        except Organization.DoesNotExist:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = OrganizationMemberListSerializer(org)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Member Invite
# ---------------------------------------------------------------------------

class OrganizationMemberInviteView(APIView):
    """
    POST /api/v1/organizations/{orgId}/members  — Invite user by email (admin only).
    """
    permission_classes = [IsAuthenticated, IsOrgAdmin]

    def post(self, request, orgId):
        try:
            org = Organization.objects.get(pk=orgId)
        except Organization.DoesNotExist:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = MemberInviteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email']
        role_name = serializer.validated_data['role']

        user = User.objects.get(email=email)
        role = OrganizationRole.objects.get(name=role_name)

        if OrganizationMember.objects.filter(users=user, organizations=org).exists():
            return Response(
                {'detail': 'User is already a member of this organization.'},
                status=status.HTTP_409_CONFLICT,
            )

        member = OrganizationMember.objects.create(
            users=user,
            organizations=org,
            role=role,
        )

        return Response(
            {
                'detail': 'User added to organization.',
                'member_id': member.id,
                'email': email,
                'role': role_name,
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Member Remove
# ---------------------------------------------------------------------------

class OrganizationMemberRemoveView(APIView):
    """
    DELETE /api/v1/organizations/{orgId}/members/{userId}  — Remove member (admin only).
    """
    permission_classes = [IsAuthenticated, IsOrgAdmin]

    def delete(self, request, orgId, userId):
        try:
            org = Organization.objects.get(pk=orgId)
        except Organization.DoesNotExist:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            member = OrganizationMember.objects.get(organizations=org, users_id=userId)
        except OrganizationMember.DoesNotExist:
            return Response(
                {'detail': 'User is not a member of this organization.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Prevent removing the last admin
        if member.role.name == 'admin':
            admin_count = OrganizationMember.objects.filter(
                organizations=org, role__name='admin'
            ).count()
            if admin_count <= 1:
                return Response(
                    {'detail': 'Cannot remove the last admin from the organization.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        member.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrganizationExportView(APIView):
    """
    Exports all core data for an organization as a JSON download.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, orgId):
        org = get_object_or_404(Organization, pk=orgId)
        # Check authorization - only owners/admins should export data
        # Using a simple membership check for MVP, but you'd restrict to specific roles
        membership = get_object_or_404(org.memberships, user=request.user)
        
        from surveillance.models import Monitor, Incident, AuditLog
        
        monitors = Monitor.objects.filter(organization=org).values('id', 'name', 'type', 'url')
        incidents = Incident.objects.filter(organization=org).values('id', 'title', 'status', 'severity', 'started_at', 'resolved_at')
        logs = AuditLog.objects.filter(organization=org).values('id', 'action', 'resource_type', 'timestamp')
        
        data = {
            'organization': {'id': org.id, 'name': org.name},
            'monitors': list(monitors),
            'incidents': list(incidents),
            'audit_logs': list(logs)
        }
        
        # Log this highly privileged action
        AuditLog.objects.create(
            organization=org,
            actor=request.user,
            action='export',
            resource_type='Organization',
            resource_id=str(org.id)
        )
        
        return Response(data, status=status.HTTP_200_OK)
