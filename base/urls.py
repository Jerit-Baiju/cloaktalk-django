from django.urls import path

from base import views

urlpatterns = [
    path("college/access/", views.CollegeAccessView.as_view(), name="college_access"),
    path("college/status/", views.CollegeStatusView.as_view(), name="college_status"),
]
