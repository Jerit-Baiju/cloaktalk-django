from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from accounts import views

urlpatterns = [
    path("google/auth_url/", views.GoogleLoginUrl.as_view(), name="google_auth_url"),
    path("google/login/", views.GoogleLogin.as_view(), name="google_login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("user/", views.UserView.as_view(), name="user"),
]
