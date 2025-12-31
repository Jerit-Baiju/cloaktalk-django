from django.urls import re_path
from base import consumers

websocket_urlpatterns = [
    # Single unified WebSocket endpoint for all authenticated users
    re_path(r'ws/main/$', consumers.MainConsumer.as_asgi()),
]
