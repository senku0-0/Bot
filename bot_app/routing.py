"""
WebSocket routing configuration for bot_app.
Defines the URL patterns for WebSocket connections.
"""

from django.urls import path
from . import consumers

# ============================================================================
# WEBSOCKET URL PATTERNS
# ============================================================================
websocket_urlpatterns = [
    # WebSocket endpoint for chat conversations
    # Format: /ws/chat/{conversation_id}/
    path('ws/chat/<str:conversation_id>/', consumers.ChatConsumer.as_asgi()),
]