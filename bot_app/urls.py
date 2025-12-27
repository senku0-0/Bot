# bot_app/urls.py - SIMPLE VERSION
from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('hooks/sunshine/message', views.webhook_message, name='sunshine_webhook'),
    path('api/chat/init', views.init_conversation, name='init_conversation'),
    path('api/chat/send', views.send_message_to_sunshine, name='send_message_to_sunshine'),
    path('api/chat/escalate', views.escalate_to_agent, name='escalate_to_agent'),
    path('api/chat/messages', views.get_conversation_messages, name='get_conversation_messages'),
    path('api/send-to-zendesk', views.send_to_zendesk, name='send_to_zendesk'),
    path('zendesk/webhook', views.zendesk_webhook, name='zendesk_webhook'),  # CRITICAL!
]