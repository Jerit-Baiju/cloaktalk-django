from django.urls import path

from control import views

app_name = "control"

urlpatterns = [
    # Dashboard landing
    path("", views.analytics_dashboard, name="dashboard"),
    path("daily/", views.daily_analytics, name="daily_analytics"),
    path("daily/reader/", views.daily_chat_reader, name="daily_chat_reader"),

    # Chats exploration
    path("chats/", views.chats_list, name="chats_list"),
    path("chats/reader/", views.chat_reader, name="chat_reader"),
    path("chats/<uuid:chat_id>/", views.chat_detail, name="chat_detail"),

    # User focused views
    path("users/", views.users_list, name="users_list"),
    path("users/<int:user_id>/", views.user_detail, name="user_detail"),
    path("users/<int:user_id>/chats/", views.user_chats, name="user_chats"),

    # College focused views
    path("colleges/", views.colleges_list, name="colleges_list"),
    path("colleges/<int:college_id>/", views.college_detail, name="college_detail"),
]
