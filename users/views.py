from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from .serializers import RegisterSerializer, ProfileSerializer


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """Login, rate-limited per IP so the password field isn't a free oracle."""
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'register'


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def getProfile(request):
    return Response(ProfileSerializer(request.user).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """
    Invalidate the caller's refresh token by blacklisting it.

    Access tokens are short-lived and stateless, so the refresh token is the
    thing that actually has to die — without this, "logout" left a 7-day key
    in the client's hands.
    """
    refresh = request.data.get('refresh')
    if not refresh:
        return Response(
            {'detail': 'A "refresh" token is required to log out.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        RefreshToken(refresh).blacklist()
    except TokenError:
        return Response(
            {'detail': 'Token is invalid or already blacklisted.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response({'detail': 'Logged out.'}, status=status.HTTP_205_RESET_CONTENT)
