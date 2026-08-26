from django.urls import path
from .views import (
    OrganizationAPIView,
    OrganizationDetailView,
    OrganizationRoleAPIView,
    OrganizationMemberListView,
    OrganizationMemberInviteView,
    OrganizationMemberRemoveView,
    OrganizationExportView,
)


urlpatterns = [
    # Organization list + create
    path(
        'organizations/',
        OrganizationAPIView.as_view(),
        name='organization-list',
    ),
    # Organization detail + update
    path(
        'organizations/<int:orgId>/',
        OrganizationDetailView.as_view(),
        name='organization-detail',
    ),
    # Role management
    path(
        'organizations/roles/',
        OrganizationRoleAPIView.as_view(),
        name='organization-roles',
    ),
    # Member list
    path(
        'organizations/<int:orgId>/members/',
        OrganizationMemberListView.as_view(),
        name='organization-member-list',
    ),
    # Member invite
    path(
        'organizations/<int:orgId>/members/invite/',
        OrganizationMemberInviteView.as_view(),
        name='organization-member-invite',
    ),
    # Member remove
    path(
        'organizations/<int:orgId>/members/<int:userId>/',
        OrganizationMemberRemoveView.as_view(),
        name='organization-member-remove',
    ),
    # Data export
    path(
        'organizations/<int:orgId>/export/',
        OrganizationExportView.as_view(),
        name='organization-export',
    ),
]