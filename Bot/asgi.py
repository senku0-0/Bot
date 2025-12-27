# Bot/asgi.py
import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import bot_app.routing  # This is your bot_app's routing.py

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Bot.settings')  
# Initialize Django ASGI application
django.setup()

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            bot_app.routing.websocket_urlpatterns
        )
    ),
})