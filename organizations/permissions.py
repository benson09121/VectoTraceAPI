from rest_framework.permissions import BasePermission
from .models import OrganizationMember


class IsOrgMember(BasePermission):
    """
    Grants access if the authenticated user is a member of the organization
    identified by `orgId` in the URL kwargs.
    """
    message = 'You are not a member of this organization.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        org_id = view.kwargs.get('orgId')
        if org_id is None:
            # Fallback: check membership in any org (for list-all org endpoints)
            return OrganizationMember.objects.filter(users=user).exists()
        return OrganizationMember.objects.filter(
            users=user,
            organizations_id=org_id,
        ).exists()


class IsOrgAdmin(BasePermission):
    """
    Grants access if the authenticated user has the 'admin' role in the
    organization identified by `orgId` in the URL kwargs.
    """
    message = 'You must be an organization admin to perform this action.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        org_id = view.kwargs.get('orgId')
        if org_id is None:
            return False
        return OrganizationMember.objects.filter(
            users=user,
            organizations_id=org_id,
            role__name='admin',
        ).exists()
