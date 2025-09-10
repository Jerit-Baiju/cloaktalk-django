import os

import jwt
import requests
from datetime import datetime
from django.conf import settings
from django.core.files.base import ContentFile
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import GoogleToken, User
from accounts.utils import get_domain_from_email
from base.models import College


class GoogleLoginUrl(APIView):
    def get(self, _request):
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


def _format_time_field(t):
    """Return a HH:MM:SS string for a time-like object or pass through a string.

    This guards against database rows or in-memory instances where the field
    might be a plain string instead of a datetime.time.
    """
    if isinstance(t, str):
        return t
    try:
        return t.strftime('%H:%M:%S')
    except Exception:
        return str(t)


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
    def _generate_unique_username(self, email: str) -> str:
        """Generate a unique username based on the email.

        Try using the email as-is first (allowed by Django's default validators).
        If taken, fall back to the local-part plus a numeric suffix.
        """
        base = email.strip()
        if not User.objects.filter(username=base).exists():
            return base[:150]

        local = (email.split("@", 1)[0] or "user").strip(" .@+")
        # Keep it reasonably short to allow room for a suffix
        local = local[:30] if len(local) > 30 else local
        if not local:
            local = "user"
        suffix = 1
        while True:
            candidate = f"{local}{suffix}"
            if len(candidate) > 150:
                candidate = candidate[:150]
            if not User.objects.filter(username=candidate).exists():
                return candidate
            suffix += 1

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
            given_name = data.get("given_name", "")
            family_name = data.get("family_name", "")
            picture_url = data.get("picture", "")
            google_access_token = token_data["access_token"]
            google_refresh_token = token_data.get("refresh_token", "")  # Handle case when refresh token is not provided

            # For personal Gmail addresses, create the user but mark them inactive,
            # persist Google tokens and avatar (if available), then return the same error
            # response the frontend expects.
            domain = get_domain_from_email(email)
            if domain.lower() in {"gmail.com", "googlemail.com"}:
                # Lookup college without forcing creation (to avoid missing required fields)
                college = College.objects.filter(domain=domain).first()
                
                # If no college exists for gmail domain, create one with is_active=False
                if not college:
                    college = College.objects.create(
                        name="Gmail Users",
                        domain=domain,
                        window_start=datetime.strptime('20:00:00', '%H:%M:%S').time(),  # Default 8 PM
                        window_end=datetime.strptime('21:00:00', '%H:%M:%S').time(),    # Default 9 PM
                        is_active=False           # Gmail colleges start inactive
                    )

                # Find or create the user explicitly to avoid IntegrityErrors
                user = User.objects.filter(email=email).first()
                if not user:
                    username = self._generate_unique_username(email)
                    user = User.objects.create(
                        email=email,
                        username=username,
                        first_name=given_name,
                        last_name=family_name,
                        is_active=False,  # personal gmail users inactive by default
                        college=college,
                    )

                    # Attempt to download the user's avatar if available
                    if picture_url:
                        try:
                            response = requests.get(picture_url, timeout=10)
                            if response.status_code == 200:
                                user.avatar.save(f"{email}.png", ContentFile(response.content), save=True)
                        except requests.exceptions.RequestException as e:
                            print(f"Error downloading avatar: {e}")

                # Update GoogleToken with access and refresh tokens even for inactive users
                google_token, _ = GoogleToken.objects.get_or_create(user=user)
                google_token.access_token = google_access_token
                google_token.refresh_token = google_refresh_token
                google_token.save()

                return Response(
                    {
                        "error": "only_organization_email_allowed",
                        "detail": "Only organization email IDs are allowed. Please sign in with your college or company email.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Organization or non-gmail domain: ensure active user creation
            college = College.objects.filter(domain=domain).first()
            
            # If no college exists for this domain, create one with is_active=False
            if not college:
                # Extract a readable college name from domain
                college_name = domain.replace('.', ' ').title()
                if college_name.endswith(' Edu'):
                    college_name = college_name[:-4] + ' University'
                elif college_name.endswith(' Ac In'):
                    college_name = college_name[:-6] + ' College'
                
                college = College.objects.create(
                    name=college_name,
                    domain=domain,
                    window_start=datetime.strptime('20:00:00', '%H:%M:%S').time(),  # Default 8 PM
                    window_end=datetime.strptime('21:00:00', '%H:%M:%S').time(),    # Default 9 PM
                    is_active=False           # New colleges start inactive
                )

            user = User.objects.filter(email=email).first()
            if not user:
                username = self._generate_unique_username(email)
                user = User.objects.create(
                    email=email,
                    username=username,
                    first_name=given_name,
                    last_name=family_name,
                    college=college,
                )

                # Attempt to download the user's avatar if available
                if picture_url:
                    try:
                        response = requests.get(picture_url, timeout=10)
                        if response.status_code == 200:
                            user.avatar.save(f"{email}.png", ContentFile(response.content), save=True)
                    except requests.exceptions.RequestException as e:
                        print(f"Error downloading avatar: {e}")

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
                "college": {
                    "id": user.college.id,
                    "name": user.college.name,
                    "domain": user.college.domain,
                    "is_active": user.college.is_active,
                    "window_start": _format_time_field(user.college.window_start),
                    "window_end": _format_time_field(user.college.window_end),
                } if user.college else None
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
        
        # Ensure user has a college - fix for legacy users who might not have one
        if not user.college:
            domain = get_domain_from_email(user.email)
            college = College.objects.filter(domain=domain).first()
            
            if not college:
                # Extract a readable college name from domain
                college_name = domain.replace('.', ' ').title()
                if college_name.endswith(' Edu'):
                    college_name = college_name[:-4] + ' University'
                elif college_name.endswith(' Ac In'):
                    college_name = college_name[:-6] + ' College'
                elif domain.lower() in {"gmail.com", "googlemail.com"}:
                    college_name = "Gmail Users"
                
                college = College.objects.create(
                    name=college_name,
                    domain=domain,
                    window_start=datetime.strptime('20:00:00', '%H:%M:%S').time(),  # Default 8 PM
                    window_end=datetime.strptime('21:00:00', '%H:%M:%S').time(),    # Default 9 PM
                    is_active=False           # New colleges start inactive
                )
            
            # Assign college to user
            user.college = college
            user.save()

        # Format user data to match frontend expectations
        user_data = {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "profile_picture": user.avatar.url if user.avatar else None,
            "is_active": user.is_active,
            "date_joined": user.date_joined.isoformat(),
            "college": {
                "id": user.college.id,
                "name": user.college.name,
                "domain": user.college.domain,
                "is_active": user.college.is_active,
                "window_start": _format_time_field(user.college.window_start),
                "window_end": _format_time_field(user.college.window_end),
            } if user.college else None
        }

        return Response(user_data, status=status.HTTP_200_OK)
