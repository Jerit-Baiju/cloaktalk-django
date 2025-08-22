import os

import jwt
import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError
from rest_framework import status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import GoogleToken, User


class GoogleLoginUrl(APIView):
    def get(self, request):
        request_url = requests.Request(
            "GET",
            "https://accounts.google.com/o/oauth2/v2/auth",
            params={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "redirect_uri": f"{os.environ['CLIENT_HOST']}/api/auth/callback/google",
                "scope": "https://www.googleapis.com/auth/userinfo.email "
                "https://www.googleapis.com/auth/userinfo.profile",
                "access_type": "offline",
                "response_type": "code",
                "prompt": "consent",
                "include_granted_scopes": "true",
            },
        )
        url = request_url.prepare().url
        return Response({"url": url})


def get_auth_tokens(code, redirect_uri):
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        params={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    return response.json()


def refresh_access(refresh_token):
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        params={
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    return response.json()


class GoogleLogin(APIView):
    def post(self, request):
        code = request.data.get("code")

        if not code:
            return Response(
                {"error": "Authorization code is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token_data = get_auth_tokens(code, f"{os.environ['CLIENT_HOST']}/api/auth/callback/google")

        # Check if id_token exists in the response
        if "id_token" not in token_data:
            # Log the full error response for debugging
            error_description = token_data.get("error_description", "Unknown error")
            error_type = token_data.get("error", "invalid_grant")

            print(f"Google OAuth Error: {error_type} - {error_description}")
            print(f"Full token_data response: {token_data}")

            return Response(
                {
                    "error": "Authentication failed. Invalid response from Google.",
                    "details": f"{error_type}: {error_description}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            data = jwt.decode(token_data["id_token"], options={"verify_signature": False})
            email = data["email"]
            name = data["name"]
            given_name = data.get("given_name", "")
            family_name = data.get("family_name", "")
            picture_url = data.get("picture", "")
            google_access_token = token_data["access_token"]
            google_refresh_token = token_data.get("refresh_token", "")  # Handle case when refresh token is not provided

            # Generate username based on email if not provided
            username = email.split("@")[0]

            try:
                user, created = User.objects.get_or_create(email=email)
                if created:
                    user.username = username
                    user.first_name = given_name
                    user.last_name = family_name
                    user.save()

                    # Attempt to download the user's avatar if available
                    if picture_url:
                        try:
                            response = requests.get(picture_url, timeout=10)
                            if response.status_code == 200:
                                user.avatar.save(f"{email}.png", ContentFile(response.content), save=True)
                        except requests.exceptions.RequestException as e:
                            print(f"Error downloading avatar: {e}")

            except IntegrityError:
                user = User.objects.get(email=email)

            # Update GoogleToken with access and refresh tokens
            google_token, _ = GoogleToken.objects.get_or_create(user=user)
            google_token.access_token = google_access_token
            google_token.refresh_token = google_refresh_token
            google_token.save()

            # Create JWT tokens for the user
            refresh = RefreshToken.for_user(user)
            access_token = str(refresh.access_token)
            refresh_token = str(refresh)

            # Format user data to match frontend expectations
            user_data = {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "profile_picture": user.avatar.url if user.avatar else None,
                "is_active": user.is_active,
                "date_joined": user.date_joined.isoformat(),
            }

            return Response(
                {
                    "access": access_token,
                    "refresh": refresh_token,
                    "user": user_data,
                },
                status=status.HTTP_200_OK,
            )
        except jwt.DecodeError:
            return Response(
                {"error": "Authentication failed. Invalid id_token."},
                status=status.HTTP_400_BAD_REQUEST,
            )


class UserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Get current user data for token validation and user info retrieval
        """
        user = request.user
        
        # Format user data to match frontend expectations
        user_data = {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "profile_picture": user.avatar.url if user.avatar else None,
            "is_active": user.is_active,
            "date_joined": user.date_joined.isoformat(),
        }
        
        return Response(user_data, status=status.HTTP_200_OK)
