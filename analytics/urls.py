from django.urls import path

from analytics import views

app_name = 'analytics'

urlpatterns = [
    path('', views.analytics_dashboard, name='dashboard'),
    path('users/', views.UsersListView.as_view(), name='users_list'),
    path('users/<int:pk>/', views.UserDetailView.as_view(), name='user_detail'),
    path('chats/<uuid:pk>/', views.ChatDetailView.as_view(), name='chat_detail'),
]
