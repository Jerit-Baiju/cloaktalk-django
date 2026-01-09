from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenRefreshSerializer as BaseTokenRefreshSerializer
from rest_framework_simplejwt.exceptions import InvalidToken
from django.contrib.auth import get_user_model


class TokenRefreshSerializer(BaseTokenRefreshSerializer):
    """
    Custom token refresh serializer that handles cases where the user
    associated with a refresh token no longer exists in the database.
    
    This prevents 500 errors when deleted users attempt to refresh their tokens,
    returning a proper 401 error instead.
    """
    
    def validate(self, attrs):
        try:
            return super().validate(attrs)
        except get_user_model().DoesNotExist:
            # If the user associated with the token doesn't exist anymore,
            # treat it as an invalid token
            raise InvalidToken("User associated with this token no longer exists")
