import os

import jwt
import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError
from rest_framework import status
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
        token_data = get_auth_tokens(code, f"{os.environ['CLIENT_HOST']}/api/auth/callback/google")

        # Check if id_token exists in the response
        if "id_token" not in token_data:
            return Response(
                {"error": "Authentication failed. Invalid response from Google."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            data = jwt.decode(token_data["id_token"], options={"verify_signature": False})
            email = data["email"]
            name = data["name"]
            google_access_token = token_data["access_token"]
            google_refresh_token = token_data.get("refresh_token", "")  # Handle case when refresh token is not provided

            # Generate username based on email if not provided
            username = email.split("@")[0]

            try:
                user, created = User.objects.get_or_create(email=email)
                if created:
                    user.name = name
                    user.username = username
                    user.save()

                    # Attempt to download the user's avatar if available
                    try:
                        response = requests.get(data["picture"], timeout=10)
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
            return Response(
                {
                    "access": access_token,
                    "refresh": refresh_token,
                },
                status=status.HTTP_200_OK,
            )
        except jwt.DecodeError:
            return Response(
                {"error": "Authentication failed. Invalid id_token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
