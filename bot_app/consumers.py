import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
import asyncio

logger = logging.getLogger(__name__)

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        """WebSocket connection handler"""
        try:
            # Get conversation ID from URL
            self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
            self.room_group_name = f'chat_{self.conversation_id}'
            
            logger.info(f"🔗 WebSocket connecting: {self.conversation_id}")
            
            # CRITICAL: Accept connection FIRST
            await self.accept()
            logger.info(f"✅ WebSocket ACCEPTED: {self.conversation_id}")
            
            # Join room group
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            
            # Send welcome message
            await self.send(text_data=json.dumps({
                'type': 'connection_established',
                'message': f'Connected to conversation {self.conversation_id}',
                'conversation_id': self.conversation_id
            }))
            
            # Start keepalive
            self.keepalive_task = asyncio.create_task(self.send_keepalive())
            
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            # Still accept to prevent 1001 error
            await self.accept()
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))
    
    async def send_keepalive(self):
        """Keep connection alive"""
        try:
            while True:
                await asyncio.sleep(25)  # Every 25 seconds
                if hasattr(self, 'connected'):
                    await self.send(text_data=json.dumps({
                        'type': 'keepalive',
                        'timestamp': asyncio.get_event_loop().time()
                    }))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Keepalive error: {e}")
    
    async def disconnect(self, close_code):
        """Handle disconnect"""
        logger.info(f"🔌 WebSocket disconnected: {self.conversation_id}, code: {close_code}")
        
        # Cancel keepalive
        if hasattr(self, 'keepalive_task'):
            self.keepalive_task.cancel()
        
        # Leave room
        try:
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
        except:
            pass
    
    async def receive(self, text_data):
        """Handle incoming messages"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'unknown')
            
            if message_type == 'ping':
                # Respond to ping
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': data.get('timestamp')
                }))
            elif message_type == 'echo':
                # Echo back
                await self.send(text_data=json.dumps({
                    'type': 'echo_response',
                    'message': data.get('message', ''),
                    'received_at': asyncio.get_event_loop().time()
                }))
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON")
    
    # ============================================
    # CRITICAL: Handler for agent messages
    # ============================================
    async def send_webhook_message(self, event):
        """Receive agent messages from Django views"""
        try:
            message = event['message']
            logger.info(f"📤 Sending agent message to WebSocket")
            
            # Send to WebSocket
            await self.send(text_data=json.dumps(message))
            
        except Exception as e:
            logger.error(f"❌ Error sending agent message: {e}")