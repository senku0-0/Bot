"""
ASGI config for Bot project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

# ============================================================================
# WEBSOCKET ADDED: Import Channels components for WebSocket support
# ============================================================================
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import bot_app.routing  # Import your app's WebSocket routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Bot.settings')

# ============================================================================
# WEBSOCKET ADDED: Configure ASGI application with WebSocket support
# ============================================================================
application = ProtocolTypeRouter({
    # Django's ASGI application to handle traditional HTTP requests
    "http": get_asgi_application(),
    
    # WebSocket handler
    "websocket": AuthMiddlewareStack(
        URLRouter(
            bot_app.routing.websocket_urlpatterns  # Your WebSocket URL patterns
        )
    ),
})