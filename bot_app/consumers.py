import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
import asyncio

logger = logging.getLogger(__name__)

class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time chat messaging."""
    
    async def connect(self):
        """
        Establish WebSocket connection, join group, send welcome message, and start keepalive.
        
        Extracts conversation_id from URL route, joins corresponding group, sends
        connection confirmation to client, and initiates keepalive heartbeat task.
        """
        try:
            self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
            self.room_group_name = f'chat_{self.conversation_id}'
            self.connected = True
            
            await self.accept()
            logger.info(f"WebSocket connected: {self.conversation_id}")
            
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            
            await self.send(text_data=json.dumps({
                'type': 'connection_established',
                'message': f'Connected to conversation {self.conversation_id}',
                'conversation_id': self.conversation_id,
                'group_name': self.room_group_name
            }))
            
            self.keepalive_task = asyncio.create_task(self.send_keepalive())
            
        except Exception as e:
            logger.error(f"Connection error: {e}", exc_info=True)
            try:
                await self.accept()
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': str(e)
                }))
            except Exception:
                pass
    
    async def send_keepalive(self):
        """
        Send keepalive heartbeat every 25 seconds to maintain WebSocket connection.
        
        Prevents connection timeout by sending periodic keepalive messages while
        connection is active. Handles cancellation gracefully on disconnect.
        """
        try:
            while True:
                await asyncio.sleep(25)
                if hasattr(self, 'connected') and self.connected:
                    try:
                        await self.send(text_data=json.dumps({
                            'type': 'keepalive',
                            'timestamp': asyncio.get_event_loop().time()
                        }))
                    except Exception as e:
                        logger.error(f"Keepalive send error: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Keepalive error: {e}", exc_info=True)
    
    async def disconnect(self, close_code):
        """
        Handle WebSocket disconnect, cleanup resources, and leave group.
        
        Marks connection as inactive, cancels keepalive task, and removes
        consumer from channel group on disconnect.
        """
        logger.info(f"WebSocket disconnected: {self.conversation_id} (code={close_code})")
        
        self.connected = False
        
        if hasattr(self, 'keepalive_task'):
            try:
                self.keepalive_task.cancel()
            except Exception as e:
                logger.error(f"Error cancelling keepalive: {e}")
        
        try:
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        except Exception as e:
            logger.error(f"Error leaving group: {e}")
    
    async def receive(self, text_data):
        """
        Handle incoming WebSocket messages from client.
        
        Processes client messages based on type (ping, echo, test_agent_message).
        Responds to pings with pongs, echoes messages back to client, and simulates
        agent messages for testing purposes.
        
        Args:
            text_data (str): JSON-encoded message from client
        """
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'unknown')
            
            if message_type == 'ping':
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': data.get('timestamp'),
                    'conversation_id': self.conversation_id
                }))
                
            elif message_type == 'echo':
                await self.send(text_data=json.dumps({
                    'type': 'echo_response',
                    'message': data.get('message', ''),
                    'received_at': asyncio.get_event_loop().time(),
                    'conversation_id': self.conversation_id
                }))
                
            elif message_type == 'test_agent_message':
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
            else:
                logger.warning(f"Unknown message type: {message_type}")
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
    
    async def send_webhook_message(self, event):
        """
        Receive and forward agent messages from Django views to WebSocket client.
        
        Handler method called by channel group for agent messages. Validates message
        structure, ensures connection is active, enriches with conversation ID if needed,
        and sends to connected WebSocket client.
        
        Args:
            event (dict): Event dict containing 'message' key with agent message data
        """
        try:
            message = event.get('message')
            if not message:
                logger.error("No message in event")
                return
            
            if not hasattr(self, 'connected') or not self.connected:
                logger.warning("Not connected, cannot send message")
                return
            
            if not isinstance(message, dict):
                logger.error(f"Invalid message type: {type(message)}")
                return
                
            if 'type' not in message:
                message['type'] = 'agent_message'
            
            if 'payload' not in message:
                message = {
                    'type': 'agent_message',
                    'payload': message
                }
            
            if 'payload' in message and 'conversationId' not in message['payload']:
                message['payload']['conversationId'] = self.conversation_id
            
            await self.send(text_data=json.dumps(message))
            logger.info(f"Agent message sent: {self.conversation_id}")
                        
        except Exception as e:
            logger.error(f"Error sending agent message: {e}", exc_info=True)