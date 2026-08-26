from django.db import models
from users.models import User


class Organization(models.Model):
    name = models.TextField()
    status = models.BooleanField(default=True)
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        return self.name


class OrganizationRole(models.Model):
    name = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def __str__(self):
        return self.name


class OrganizationMember(models.Model):
    users = models.ForeignKey(
        to=User,
        on_delete=models.CASCADE,
        related_name='user_member',
        unique=False,
    )
    organizations = models.ForeignKey(
        to=Organization,
        related_name='members',
        on_delete=models.CASCADE,
    )
    role = models.ForeignKey(
        to=OrganizationRole,
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        unique_together = ('users', 'organizations')

    def __str__(self):
        return f"{self.users.email} @ {self.organizations.name} ({self.role.name})"