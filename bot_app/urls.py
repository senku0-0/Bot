from django.urls import path
from .views import index, webhook_message, init_conversation, send_message_to_sunshine, escalate_to_agent, get_conversation_messages, send_to_zendesk, zendesk_webhook
from .views import debug_websocket,debug_zendesk_format

urlpatterns = [
    path('', index, name='index'),
    path('hooks/sunshine/message', webhook_message, name='sunshine_webhook'),
    path('api/chat/init', init_conversation, name='init_conversation'),
    path('api/chat/send', send_message_to_sunshine, name='send_message_to_sunshine'),
    path('api/chat/escalate', escalate_to_agent, name='escalate_to_agent'),
    path('api/chat/messages', get_conversation_messages, name='get_conversation_messages'),
    path('api/send-to-zendesk', send_to_zendesk, name='send_to_zendesk'),
    path('api/debug-websocket', debug_websocket, name='debug_websocket'),
    path('zendesk/webhook', zendesk_webhook, name='zendesk_webhook'),
    path('debug-zendesk', debug_zendesk_format, name='debug_zendesk'),
]