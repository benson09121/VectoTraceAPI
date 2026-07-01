from django.contrib import admin
from .models import *

@admin.register(User)
class UsersAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "email")

# Register your models here.
