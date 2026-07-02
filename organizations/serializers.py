from rest_framework import serializers
from .models import *
from users.serializers import ProfileSerializer

class OrganizationSerializer(serializers.ModelSerializer):
    organization_role = OrganizationRole.objects.filter(name="admin")
    
    class Meta:
        model = Organization
        fields = ['id', 'name', 'status', 'created_at', 'updated_at']

class OrganizationCreateSerializer(serializers.ModelSerializer):
        

    class Meta:
        model = Organization
        fields = ['name']
    
    def create(self, validated_data):
        organization = Organization.objects.create(**validated_data)
        admin_role = OrganizationRole.objects.get(name="admin")

        OrganizationMember.objects.create(
            organizations=organization,
            users=self.context["request"].user,
            role=admin_role,
        )


class OrganizationRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationRole
        fields = ['id', 'name', 'created_at', 'updated_at']


class OrganizationMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationMember
        fields = "__all__"


class OrganizationMemberwithUserSerializer(serializers.ModelSerializer):
    users = ProfileSerializer()
    role = serializers.ReadOnlyField(source='role.name')

    class Meta:
        model = OrganizationMember
        fields = [
            'users',
            'role'
        ]

class OrganizationMemberGetSerializer(serializers.ModelSerializer):
    members = OrganizationMemberwithUserSerializer(many=True)

    class Meta:
        model = Organization
        fields = '__all__'