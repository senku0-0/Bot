# Bot/asgi.py - MINIMAL VERSION
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Bot.settings')

# Initialize Django FIRST
django_application = get_asgi_application()

# Import channels AFTER Django is set up
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import bot_app.routing

application = ProtocolTypeRouter({
    "http": django_application,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            bot_app.routing.websocket_urlpatterns
        )
    ),
})