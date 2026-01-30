import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
import asyncio
from asgiref.sync import sync_to_async
from datetime import datetime

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        """WebSocket connection handler"""
        try:
            # Get conversation ID from URL
            self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
            self.room_group_name = f'chat_{self.conversation_id}'
            
            logger.info(f"🔗 [WEBSOCKET-CONNECT] WebSocket connecting: conversation_id={self.conversation_id}")
            logger.info(f"🔗 [WEBSOCKET-CONNECT] Group name will be: {self.room_group_name}")
            
            # Store connection state
            self.connected = True
            
            # CRITICAL: Accept connection FIRST
            await self.accept()
            logger.info(f"✅ [WEBSOCKET-CONNECT] WebSocket ACCEPTED: {self.conversation_id}")
            
            # Join room group
            try:
                await self.channel_layer.group_add(
                    self.room_group_name,
                    self.channel_name
                )
                logger.info(f"✅ [WEBSOCKET-CONNECT] Joined group: {self.room_group_name}")
            except Exception as group_error:
                logger.error(f"❌ [WEBSOCKET-CONNECT] Failed to join group: {group_error}")
                # Still continue, but log the error
            
            # Send welcome message
            try:
                await self.send(text_data=json.dumps({
                    'type': 'connection_established',
                    'message': f'Connected to conversation {self.conversation_id}',
                    'conversation_id': self.conversation_id,
                    'group_name': self.room_group_name
                }))
                logger.info(f"✅ [WEBSOCKET-CONNECT] Sent welcome message")
            except Exception as send_error:
                logger.error(f"❌ [WEBSOCKET-CONNECT] Failed to send welcome message: {send_error}")
            
            # Start keepalive
            try:
                self.keepalive_task = asyncio.create_task(self.send_keepalive())
                logger.info(f"✅ [WEBSOCKET-CONNECT] Started keepalive task")
            except Exception as keepalive_error:
                logger.error(f"❌ [WEBSOCKET-CONNECT] Failed to start keepalive: {keepalive_error}")
            
            # Log successful connection
            logger.info(f"✅ [WEBSOCKET-CONNECT] Connection fully established for conversation {self.conversation_id}")
            
        except Exception as e:
            logger.exception(f"❌ [WEBSOCKET-CONNECT] Connection error: {e}")
            # Still accept to prevent 1001 error
            try:
                await self.accept()
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': str(e)
                }))
            except:
                pass
    
    async def send_keepalive(self):
        """Keep connection alive"""
        try:
            while True:
                await asyncio.sleep(25)  # Every 25 seconds
                if hasattr(self, 'connected') and self.connected:
                    try:
                        await self.send(text_data=json.dumps({
                            'type': 'keepalive',
                            'timestamp': asyncio.get_event_loop().time()
                        }))
                        logger.debug(f"📡 [WEBSOCKET-KEEPALIVE] Sent keepalive for {self.conversation_id}")
                    except Exception as e:
                        logger.error(f"❌ [WEBSOCKET-KEEPALIVE] Failed to send keepalive: {e}")
        except asyncio.CancelledError:
            logger.info(f"📡 [WEBSOCKET-KEEPALIVE] Keepalive cancelled for {self.conversation_id}")
        except Exception as e:
            logger.exception(f"❌ [WEBSOCKET-KEEPALIVE] Keepalive error: {e}")
    
    async def disconnect(self, close_code):
        """Handle disconnect"""
        logger.info(f"🔌 [WEBSOCKET-DISCONNECT] WebSocket disconnected: conversation_id={self.conversation_id}, code={close_code}")
        
        # Mark as disconnected
        self.connected = False
        
        # Cancel keepalive
        if hasattr(self, 'keepalive_task'):
            try:
                self.keepalive_task.cancel()
                logger.info(f"🔌 [WEBSOCKET-DISCONNECT] Cancelled keepalive task")
            except Exception as e:
                logger.error(f"❌ [WEBSOCKET-DISCONNECT] Error cancelling keepalive: {e}")
        
        # Leave room
        try:
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
            logger.info(f"🔌 [WEBSOCKET-DISCONNECT] Left group: {self.room_group_name}")
        except Exception as e:
            logger.error(f"❌ [WEBSOCKET-DISCONNECT] Error leaving group: {e}")
    
    async def receive(self, text_data):
        """Handle incoming messages from client"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'unknown')
            
            logger.info(f"📥 [WEBSOCKET-RECEIVE] Received message type: {message_type} for conversation {self.conversation_id}")
            
            if message_type == 'ping':
                # Respond to ping
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': data.get('timestamp'),
                    'conversation_id': self.conversation_id
                }))
                logger.info(f"📤 [WEBSOCKET-RECEIVE] Sent pong response")
                
            elif message_type == 'echo':
                # Echo back
                await self.send(text_data=json.dumps({
                    'type': 'echo_response',
                    'message': data.get('message', ''),
                    'received_at': asyncio.get_event_loop().time(),
                    'conversation_id': self.conversation_id
                }))
                logger.info(f"📤 [WEBSOCKET-RECEIVE] Sent echo response")
                
            elif message_type == 'test_agent_message':
                # Test endpoint for agent messages
                test_message = data.get('message', 'Test agent message')
                await self.send_webhook_message({
                    'message': {
                        'type': 'agent_message',
                        'payload': {
                            'id': f"test_{asyncio.get_event_loop().time()}",
                            'author': {
                                'type': 'business',
                                'displayName': 'Test Agent',
                                'role': 'agent'
                            },
                            'content': {
                                'type': 'text',
                                'text': test_message
                            },
                            'received': asyncio.get_event_loop().time(),
                            'source': 'test',
                            'conversationId': self.conversation_id
                        }
                    }
                })
                logger.info(f"📤 [WEBSOCKET-RECEIVE] Sent test agent message")
                
            else:
                logger.warning(f"⚠️ [WEBSOCKET-RECEIVE] Unknown message type: {message_type}")
                
        except json.JSONDecodeError:
            logger.error("❌ [WEBSOCKET-RECEIVE] Invalid JSON received")
        except Exception as e:
            logger.exception(f"❌ [WEBSOCKET-RECEIVE] Error processing message: {e}")
    
    # ============================================
    # CRITICAL: Handler for agent messages from Django views
    # ============================================
    async def send_webhook_message(self, event):
        """Receive agent messages from Django views (via group_send)"""
        try:
            logger.info(f"🎯 [WEBSOCKET-HANDLER] send_webhook_message called for conversation {self.conversation_id}")
            logger.info(f"🎯 [WEBSOCKET-HANDLER] Event keys: {list(event.keys())}")
            
            message = event.get('message')
            if not message:
                logger.error("❌ [WEBSOCKET-HANDLER] No message in event")
                return
                
            logger.info(f"🎯 [WEBSOCKET-HANDLER] Message type: {type(message)}")
            logger.info(f"🎯 [WEBSOCKET-HANDLER] Message keys: {list(message.keys()) if isinstance(message, dict) else 'Not a dict'}")
            
            # Check if we're still connected
            if not hasattr(self, 'connected') or not self.connected:
                logger.warning(f"⚠️ [WEBSOCKET-HANDLER] Not connected, can't send message")
                return
            
            # Validate the message structure
            if not isinstance(message, dict):
                logger.error(f"❌ [WEBSOCKET-HANDLER] Message is not a dict: {type(message)}")
                return
                
            # Ensure it has the expected structure
            if 'type' not in message:
                logger.warning(f"⚠️ [WEBSOCKET-HANDLER] Message missing 'type' field, adding default")
                message['type'] = 'agent_message'
            
            if 'payload' not in message:
                logger.warning(f"⚠️ [WEBSOCKET-HANDLER] Message missing 'payload' field, wrapping content")
                message = {
                    'type': 'agent_message',
                    'payload': message
                }
            
            # Add conversation ID and timestamp if not present
            if 'payload' in message and 'conversationId' not in message['payload']:
                message['payload']['conversationId'] = self.conversation_id
            
            # Add timestamp to payload if not already present
            if 'payload' in message and 'timestamp' not in message['payload']:
                message['payload']['timestamp'] = datetime.now().isoformat()
            
            logger.info(f"📤 [WEBSOCKET-HANDLER] Sending to WebSocket client: conversation={self.conversation_id}, message_type={message.get('type')}")
            logger.info(f"📤 [WEBSOCKET-HANDLER] Message preview: {str(json.dumps(message))[:200]}...")
            
            # Send to WebSocket client
            try:
                await self.send(text_data=json.dumps(message))
                logger.info(f"✅ [WEBSOCKET-HANDLER] Agent message successfully sent to WebSocket client")
                logger.info(f"✅ [WEBSOCKET-HANDLER] Conversation: {self.conversation_id}")
                logger.info(f"✅ [WEBSOCKET-HANDLER] Message type: {message.get('type')}")
                
                # Log the actual content if it's text
                if 'payload' in message and 'content' in message['payload']:
                    content = message['payload']['content']
                    if isinstance(content, dict) and 'text' in content:
                        logger.info(f"✅ [WEBSOCKET-HANDLER] Message text: {content['text'][:100]}...")
                        
            except Exception as send_err:
                logger.exception(f"❌ [WEBSOCKET-HANDLER] Error sending agent message to WebSocket client: {send_err}")
                logger.error(f"❌ [WEBSOCKET-HANDLER] Connection may be dead for conversation {self.conversation_id}")

        except Exception as e:
            logger.exception(f"❌ [WEBSOCKET-HANDLER] Error in send_webhook_message handler: {e}")