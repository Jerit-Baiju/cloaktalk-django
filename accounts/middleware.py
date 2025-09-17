from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from jwt import decode as jwt_decode
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken

User = get_user_model()


@database_sync_to_async
def get_user_by_id(user_id):
    """Get user by ID."""
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """
    Custom JWT authentication middleware for Django Channels WebSocket connections.

    This middleware extracts the JWT token from query parameters and authenticates
    the user for WebSocket connections.
    """

    def __init__(self, inner):
        super().__init__(inner)

    async def __call__(self, scope, receive, send):
        # Only process WebSocket connections
        if scope["type"] != "websocket":
            return await super().__call__(scope, receive, send)

        # Extract token from query parameters
        query_string = scope.get("query_string", b"").decode()
        query_params = parse_qs(query_string)

        token = None
        if "token" in query_params:
            token = query_params["token"][0]

        # Set default user as anonymous
        scope["user"] = AnonymousUser()

        if token:
            try:
                # Validate the token
                UntypedToken(token)

                # Decode the token to get user information
                decoded_data = jwt_decode(token, settings.SECRET_KEY, algorithms=["HS256"])

                # Get the user ID from token
                user_id = decoded_data.get("user_id")

                if user_id:
                    # Get user from database
                    user = await get_user_by_id(user_id)
                    if user and not isinstance(user, AnonymousUser):
                        scope["user"] = user

            except (InvalidToken, TokenError, Exception) as e:
                # Token is invalid or expired
                print(f"JWT authentication failed: {e}")
                pass

        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    """
    Stack JWT authentication middleware.
    """
    return JWTAuthMiddleware(inner)
