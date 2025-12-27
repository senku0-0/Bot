"""
WebSocket consumers for real-time chat functionality.
Handles WebSocket connections and message broadcasting.
"""

import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.cache import cache

logger = logging.getLogger(__name__)

class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for handling real-time chat connections.
    Each conversation has its own room group for broadcasting messages.
    """
    
    async def connect(self):
        """
        Called when WebSocket connection is established.
        """
        # Extract conversation_id from URL
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.room_group_name = f'chat_{self.conversation_id}'
        
        # Join the room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        # Accept the WebSocket connection
        await self.accept()
        
        # Store connection in cache (optional, for tracking active connections)
        await self.store_connection()
        
        logger.info(f"✅ WebSocket connected for conversation: {self.conversation_id}")
        
        # Send a welcome message to the client
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'message': 'WebSocket connection established',
            'conversationId': self.conversation_id
        }))

    async def disconnect(self, close_code):
        """
        Called when WebSocket connection is closed.
        """
        # Leave the room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        
        # Remove connection from cache
        await self.remove_connection()
        
        logger.info(f"🔌 WebSocket disconnected for conversation: {self.conversation_id}")

    async def receive(self, text_data):
        """
        Called when a message is received from WebSocket client.
        """
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type', 'unknown')
            
            logger.info(f"📥 Received WebSocket message: {message_type}")
            
            # Handle ping/pong for connection keep-alive
            if message_type == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
            else:
                # Broadcast to everyone in the room group
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'message': text_data_json
                    }
                )
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ Error decoding WebSocket message: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))

    async def chat_message(self, event):
        """
        Handler for 'chat_message' type events.
        Called when a message is broadcast to the room group.
        """
        message = event['message']
        await self.send(text_data=json.dumps(message))

    async def send_webhook_message(self, event):
        """
        CRITICAL: Special handler for webhook forwarding.
        This is called when Django backend forwards Sunshine webhooks to WebSocket.
        This ensures agent messages appear instantly in UI.
        """
        message = event['message']
        await self.send(text_data=json.dumps(message))
        logger.debug(f"📤 Forwarded webhook to WebSocket for conversation: {self.conversation_id}")

    @database_sync_to_async
    def store_connection(self):
        """
        Store active WebSocket connection in cache (optional).
        Useful for tracking active connections or debugging.
        """
        try:
            cache_key = f'ws_connections_{self.conversation_id}'
            connections = cache.get(cache_key, [])
            if self.channel_name not in connections:
                connections.append(self.channel_name)
                cache.set(cache_key, connections, timeout=3600)  # 1 hour timeout
        except Exception as e:
            logger.error(f"Error storing WebSocket connection: {e}")

    @database_sync_to_async
    def remove_connection(self):
        """
        Remove WebSocket connection from cache.
        """
        try:
            cache_key = f'ws_connections_{self.conversation_id}'
            connections = cache.get(cache_key, [])
            if self.channel_name in connections:
                connections.remove(self.channel_name)
                cache.set(cache_key, connections, timeout=3600)
        except Exception as e:
            logger.error(f"Error removing WebSocket connection: {e}")