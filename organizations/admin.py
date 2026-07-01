from django.contrib import admin
from .models import *

@admin.register(Organization)
class UsersAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "created_at")