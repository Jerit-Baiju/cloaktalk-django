from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """
    Custom User model for CloakTalk application.
    Extends Django's AbstractUser to include additional fields for profile management.
    """

    email = models.EmailField(unique=True, db_index=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    bio = models.TextField(max_length=500, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Make email the unique identifier for authentication
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        db_table = "users"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return self.email

    @property
    def display_name(self):
        """Return name if available, otherwise username"""
        return self.name if self.name else self.username

    def get_full_name(self):
        """Return the full name for the user."""
        return self.name if self.name else self.username

    def get_short_name(self):
        """Return the short name for the user."""
        return self.name if self.name else self.username


class GoogleToken(models.Model):
    """
    Model to store Google OAuth tokens for users.
    This allows the application to make API calls to Google services on behalf of the user.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="google_token")
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True, null=True)
    token_type = models.CharField(max_length=50, default="Bearer")
    expires_in = models.IntegerField(null=True, blank=True)
    scope = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "google_tokens"
        verbose_name = "Google Token"
        verbose_name_plural = "Google Tokens"

    def __str__(self):
        return f"Google Token for {self.user.email}"

    @property
    def is_expired(self):
        """Check if the access token is expired (basic check)"""
        if not self.expires_in:
            return False
        expiry_time = self.updated_at + timedelta(seconds=self.expires_in)
        return timezone.now() > expiry_time
