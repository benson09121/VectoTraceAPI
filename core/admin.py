from django.contrib import admin
from .models import SystemSettings

@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    # Make sure they cannot add multiple rows
    def has_add_permission(self, request):
        if self.model.objects.exists():
            return False
        return super().has_add_permission(request)

    # Make sure they cannot delete the only row
    def has_delete_permission(self, request, obj=None):
        return False
