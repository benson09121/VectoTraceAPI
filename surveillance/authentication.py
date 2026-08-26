"""
API token authentication.

Lets users drive the API from CI, scripts, or Grafana without a JWT dance:

    Authorization: Token vtk_<plaintext>

Only the sha256 of the token is stored, so the DB never holds anything that
can be replayed. Lookup is by hash, which is also the unique index.
"""

import hashlib
import secrets

from django.utils import timezone
from rest_framework import authentication, exceptions

TOKEN_PREFIX = 'vtk_'
KEYWORD = 'Token'


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def generate_token() -> tuple[str, str, str]:
    """Return (plaintext, token_hash, display_prefix). Plaintext is shown once."""
    plaintext = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return plaintext, hash_token(plaintext), plaintext[:12]


class ApiTokenAuthentication(authentication.BaseAuthentication):
    keyword = KEYWORD

    def authenticate(self, request):
        auth = authentication.get_authorization_header(request).split()
        if not auth or auth[0].lower() != self.keyword.lower().encode():
            return None
        if len(auth) != 2:
            raise exceptions.AuthenticationFailed('Invalid token header.')

        from .models import ApiToken  # local import: app registry may not be ready

        try:
            token = ApiToken.objects.select_related('user', 'organization').get(
                token_hash=hash_token(auth[1].decode())
            )
        except (ApiToken.DoesNotExist, UnicodeError):
            raise exceptions.AuthenticationFailed('Invalid token.')

        if token.is_expired:
            raise exceptions.AuthenticationFailed('Token has expired.')
        if not token.user.is_active:
            raise exceptions.AuthenticationFailed('User is inactive.')

        # Cheap last-seen tracking; not worth a transaction.
        ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())

        request.api_token = token
        return (token.user, token)

    def authenticate_header(self, request):
        return self.keyword
