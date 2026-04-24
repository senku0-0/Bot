# bot_app/urls.py - SIMPLE VERSION
from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('api/chat/runtime-log', views.runtime_log, name='runtime_log'),
    path('hooks/sunshine/message', views.webhook_message, name='sunshine_webhook'),
    path('api/chat/init', views.init_conversation, name='init_conversation'),
    path('api/chat/send', views.send_message_to_sunshine, name='send_message_to_sunshine'),
    path('api/chat/cancellation-charges/waive-off', views.cancellation_charges_waive_off, name='cancellation_charges_waive_off'),
    path('api/chat/escalate', views.escalate_to_agent, name='escalate_to_agent'),
    path('api/chat/create-ticket', views.create_conversation_ticket, name='create_conversation_ticket'),
    path('api/chat/messages', views.get_conversation_messages, name='get_conversation_messages'),
    path('api/chat/full-history', views.get_full_chat_history, name='get_full_chat_history'),  # NEW!
    path('api/chat/viewing-status', views.update_viewing_status, name='update_viewing_status'),  # COMBINED APPROACH
    path('api/chat/clear-badge', views.clear_unread_badge, name='clear_unread_badge'),  # ⭐ NEW: Clear badge on open
    path('api/image-proxy', views.proxy_zendesk_image, name='proxy_zendesk_image'),  # Image proxy
    path('api/send-to-zendesk', views.send_to_zendesk, name='send_to_zendesk'),
    path('zendesk/webhook', views.zendesk_webhook, name='zendesk_webhook'),  # CRITICAL!
    path('api/notifications/stream/global', views.global_notification_stream, name='global_notification_stream'),  # ⭐ NEW: Global SSE
    path('api/notifications/stream/<conversation_id>', views.notification_stream, name='notification_stream'),  # SSE per-conversation
]
