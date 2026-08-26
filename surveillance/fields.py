import json
from django.conf import settings
from django.db import models
from cryptography.fernet import Fernet, InvalidToken
from django.core.exceptions import ImproperlyConfigured

def get_fernet():
    key = getattr(settings, 'ENCRYPTION_KEY', None)
    if not key:
        # Fallback to a dummy key if none provided (e.g., in dev)
        key = Fernet.generate_key()
    return Fernet(key)

class EncryptedJSONField(models.JSONField):
    description = "A JSON field that encrypts data at rest."

    def get_prep_value(self, value):
        if value is None:
            return None
        # Convert to JSON string explicitly since the db driver won't see it as JSON anymore
        json_str = json.dumps(value)
        # Encrypt
        f = get_fernet()
        return f.encrypt(json_str.encode('utf-8')).decode('utf-8')

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        f = get_fernet()
        try:
            # Decrypt
            decrypted_str = f.decrypt(value.encode('utf-8')).decode('utf-8')
            # Parse JSON
            return json.loads(decrypted_str)
        except (InvalidToken, json.JSONDecodeError):
            # If we fail to decrypt, return original (e.g. data before encryption was added)
            # For a production system we'd handle migration better.
            try:
                return json.loads(value)
            except:
                return value

class EncryptedURLField(models.URLField):
    description = "A URL field that encrypts data at rest."

    def get_prep_value(self, value):
        if not value:
            return value
        f = get_fernet()
        return f.encrypt(value.encode('utf-8')).decode('utf-8')

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        f = get_fernet()
        try:
            return f.decrypt(value.encode('utf-8')).decode('utf-8')
        except InvalidToken:
            return value
