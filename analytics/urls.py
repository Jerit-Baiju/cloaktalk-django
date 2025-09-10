from django.urls import path

from analytics import views

app_name = "analytics"

urlpatterns = [
    # Dashboard landing
    path("", views.analytics_dashboard, name="dashboard"),

    # Chats exploration
    path("chats/", views.chats_list, name="chats_list"),
    path("chats/reader/", views.chat_reader, name="chat_reader"),
    path("chats/<uuid:chat_id>/", views.chat_detail, name="chat_detail"),

    # User focused views
    path("users/", views.users_list, name="users_list"),
    path("users/<int:user_id>/", views.user_detail, name="user_detail"),
    path("users/<int:user_id>/chats/", views.user_chats, name="user_chats"),
]
