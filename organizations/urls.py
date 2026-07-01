from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

app_name = "organizations"

urlpatterns = [
    path("organizations/", OrganizationAPIView.as_view(), name='organization_v1'),
    path("organizations/roles", OrganizationRoleAPIView.as_view(), name='organization-role_v1'),
    # path("organizations/<int:org_id>/")
]