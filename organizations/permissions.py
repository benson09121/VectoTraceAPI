from rest_framework.permissions import BasePermission
from .models import *

class IsOrgMember(BasePermission):
    message = 'You are not part of any organization.'
    def has_permission(self, request, view):
            user = request.user
            return OrganizationMember.objects.filter(users=user).exists()            

