from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from .models import User

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        """
        Run AUTH_PASSWORD_VALIDATORS.

        They were configured in settings but never applied: DRF serializers
        don't consult them, only Django's auth forms do. Without this call the
        API accepted a one-character password, and Argon2 hashing does nothing
        for a password that short.
        """
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    class Meta:
        model = User
        fields = [
            "email",
            "password",
            "first_name",
            "last_name",
        ]
    
    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        
        # Check showcase mode
        try:
            from core.models import SystemSettings
            settings = SystemSettings.get_settings()
            if settings.is_showcase_mode:
                user.is_active = True
                user.is_demo_account = True
        except Exception:
            pass # DB not ready or settings not available
            
        user.save()
        return user

class ProfileSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'email',
        ]