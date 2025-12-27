# bot_app/urls.py
from django.urls import path
from .views import (
    index, 
    webhook_message, 
    init_conversation, 
    send_message_to_sunshine, 
    escalate_to_agent, 
    get_conversation_messages, 
    send_to_zendesk, 
    zendesk_webhook,
    debug_websocket,
    debug_zendesk_format,
    debug_send_agent_join,
    debug_check_mappings,            # NEW: For checking conversation-ticket mappings
    debug_send_test_agent_message    # NEW: For testing agent messages
)

urlpatterns = [
    # Main application routes
    path('', index, name='index'),
    
    # Sunshine webhooks
    path('hooks/sunshine/message', webhook_message, name='sunshine_webhook'),
    
    # Chat API endpoints
    path('api/chat/init', init_conversation, name='init_conversation'),
    path('api/chat/send', send_message_to_sunshine, name='send_message_to_sunshine'),
    path('api/chat/escalate', escalate_to_agent, name='escalate_to_agent'),
    path('api/chat/messages', get_conversation_messages, name='get_conversation_messages'),
    
    # File upload to Zendesk via Sunshine
    path('api/send-to-zendesk', send_to_zendesk, name='send_to_zendesk'),
    
    # Zendesk webhook - CRITICAL FOR AGENT MESSAGES
    path('zendesk/webhook', zendesk_webhook, name='zendesk_webhook'),
    
    # WebSocket debug endpoints
    path('api/debug-websocket', debug_websocket, name='debug_websocket'),
    
    # Debug endpoints for troubleshooting
    path('api/debug/zendesk-format', debug_zendesk_format, name='debug_zendesk_format'),
    path('api/debug/check-mappings', debug_check_mappings, name='debug_check_mappings'),
    path('api/debug/test-agent-message', debug_send_test_agent_message, name='debug_test_agent_message'),
    path('api/debug/agent-join', debug_send_agent_join, name='debug_agent_join'),
]