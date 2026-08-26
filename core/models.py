from django.db import models
from django.core.exceptions import ValidationError

class SystemSettings(models.Model):
    """
    Singleton model for global system configuration.
    Only one row is allowed to exist in this table.
    """
    # Core Toggles
    is_showcase_mode = models.BooleanField(
        default=False, 
        help_text="Enables frictionless signup (no email verification) and auto-seeds demo data. Demo accounts are reset every 24 hours."
    )
    is_maintenance_mode = models.BooleanField(
        default=False, 
        help_text="When enabled, all non-admin API requests return a 503 Service Unavailable."
    )
    allow_registrations = models.BooleanField(
        default=True, 
        help_text="If disabled, new users cannot register."
    )

    # Apprise Fallback Settings
    default_from_email = models.EmailField(
        blank=True, null=True, 
        help_text="Default 'From' email address for Apprise email notifications."
    )
    smtp_host = models.CharField(max_length=255, blank=True, null=True)
    smtp_port = models.IntegerField(blank=True, null=True)
    smtp_user = models.CharField(max_length=255, blank=True, null=True)
    smtp_pass = models.CharField(max_length=255, blank=True, null=True)

    # System Limits
    max_monitors_per_org = models.IntegerField(
        default=50, 
        help_text="Global limit for monitors per organization."
    )
    data_retention_days = models.IntegerField(
        default=90, 
        help_text="Days to keep raw check data before it is rolled up into statistics."
    )
    minimum_check_interval = models.IntegerField(
        default=20, 
        help_text="Minimum allowed monitor check interval in seconds."
    )

    class Meta:
        verbose_name_plural = "System Settings"

    def save(self, *args, **kwargs):
        if not self.pk and SystemSettings.objects.exists():
            raise ValidationError('There can only be one SystemSettings instance')
        return super(SystemSettings, self).save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        """Helper to get the singleton instance safely."""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings

    def __str__(self):
        return "Global System Settings"
