from rest_framework import serializers
from .models import Organization, OrganizationRole, OrganizationMember
from users.models import User
from users.serializers import ProfileSerializer


# ---------------------------------------------------------------------------
# Organization Serializers
# ---------------------------------------------------------------------------

class OrganizationSerializer(serializers.ModelSerializer):
    """Full read-only org representation."""

    class Meta:
        model = Organization
        fields = ['id', 'name', 'status', 'settings', 'created_at', 'updated_at']
        read_only_fields = ['id', 'status', 'created_at', 'updated_at']


class OrganizationCreateSerializer(serializers.ModelSerializer):
    """Used when creating a new organization (POST /organizations)."""

    class Meta:
        model = Organization
        fields = ['name']

    def create(self, validated_data):
        organization = Organization.objects.create(**validated_data)
        # Roles are seeded by migration 0003, but get_or_create keeps this from
        # 500-ing on a database where that seed was rolled back or truncated.
        admin_role, _ = OrganizationRole.objects.get_or_create(name='admin')
        OrganizationMember.objects.create(
            organizations=organization,
            users=self.context['request'].user,
            role=admin_role,
        )
        return organization


class OrganizationUpdateSerializer(serializers.ModelSerializer):
    """Used when updating an organization (PATCH /organizations/{orgId})."""

    class Meta:
        model = Organization
        fields = ['name', 'settings']

    def update(self, instance, validated_data):
        instance.name = validated_data.get('name', instance.name)
        instance.settings = validated_data.get('settings', instance.settings)
        instance.save()
        return instance


# ---------------------------------------------------------------------------
# Role Serializer
# ---------------------------------------------------------------------------

class OrganizationRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationRole
        fields = ['id', 'name', 'created_at', 'updated_at']


# ---------------------------------------------------------------------------
# Member Serializers
# ---------------------------------------------------------------------------

class OrganizationMemberSerializer(serializers.ModelSerializer):
    """Flat serializer for OrganizationMember records."""

    class Meta:
        model = OrganizationMember
        fields = '__all__'


class OrganizationMemberDetailSerializer(serializers.ModelSerializer):
    """Member record with nested user profile and role name."""
    users = ProfileSerializer(read_only=True)
    role = serializers.ReadOnlyField(source='role.name')
    # `id` is the membership row's pk, but the remove endpoint is keyed on the
    # user (/members/{userId}/), so that id has to be in the payload too.
    user_id = serializers.ReadOnlyField(source='users.id')

    class Meta:
        model = OrganizationMember
        fields = ['id', 'user_id', 'users', 'role', 'created_at']


class OrganizationMemberListSerializer(serializers.ModelSerializer):
    """Organization with its members list."""
    members = OrganizationMemberDetailSerializer(many=True, read_only=True)

    class Meta:
        model = Organization
        fields = ['id', 'name', 'members']


class MemberInviteSerializer(serializers.Serializer):
    """Validates the invite-by-email payload."""
    email = serializers.EmailField()
    role = serializers.CharField(default='member')

    def validate_role(self, value):
        if not OrganizationRole.objects.filter(name=value).exists():
            raise serializers.ValidationError(
                f"Role '{value}' does not exist."
            )
        return value

    def validate_email(self, value):
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                'No user with this email address was found.'
            )
        return value