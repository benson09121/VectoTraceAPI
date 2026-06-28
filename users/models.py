from django.db import models
from django.contrib.auth.models import AbstractUser



class User(AbstractUser):
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ()
    username = None
    first_name = models.TextField()
    last_name =  models.TextField()
    email = models.EmailField(("email address"), unique=True)
    is_superuser = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(null=True)
    deleted_at = models.DateTimeField(null=True)

