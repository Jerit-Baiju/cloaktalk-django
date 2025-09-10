from django.urls import re_path
from base import consumers

websocket_urlpatterns = [
    re_path(r'ws/queue/$', consumers.QueueConsumer.as_asgi()),
    re_path(r'ws/chat/(?P<chat_id>[0-9a-f-]+)/$', consumers.ChatConsumer.as_asgi()),
]
