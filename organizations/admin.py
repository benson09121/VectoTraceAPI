from organizations.models import OrganizationRole
from organizations.models import OrganizationMember
from django.contrib import admin
from .models import *

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "created_at")

@admin.register(OrganizationMember)
class OrganizationMemberAdmin(admin.ModelAdmin):
    list_display = ("id", "users","roles", "organization")

    def roles(self,obj):
        return obj.role.name

    def organization(self, obj):
        return obj.organizations.name

@admin.register(OrganizationRole)
class OrganizationRoleAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
