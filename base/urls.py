from django.urls import path

from base import views

urlpatterns = [
    path("college/access/", views.CollegeAccessView.as_view(), name="college_access"),
    path("college/status/", views.CollegeStatusView.as_view(), name="college_status"),
    path("college/activity/", views.college_activity, name="college_activity"),
    # Queue management endpoints
    path("queue/status/", views.queue_status, name="queue_status"),
    path("queue/join/", views.join_queue, name="join_queue"),
    path("queue/leave/", views.leave_queue, name="leave_queue"),
    # Chat endpoints
    path("chat/active/", views.get_active_chat, name="get_active_chat"),
    path("chat/<uuid:chat_id>/", views.get_chat, name="get_chat"),
    path("chat/<uuid:chat_id>/end/", views.end_chat, name="end_chat"),
]
