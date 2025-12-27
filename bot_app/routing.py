"""
WebSocket routing configuration for bot_app.
Defines the URL patterns for WebSocket connections.
"""

from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/chat/<str:conversation_id>/', consumers.ChatConsumer.as_asgi()),
]