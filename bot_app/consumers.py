# consumers.py
import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.exceptions import StopConsumer

class ChatConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.keep_alive_task = None
        self.conversation_id = None
        
    async def connect(self):
        print(f"🔗 WebSocket connect attempt for: {self.scope['path']}")
        
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.room_group_name = f'chat_{self.conversation_id}'
        
        # Accept connection FIRST
        await self.accept()
        print(f"✅ WebSocket ACCEPTED for conversation: {self.conversation_id}")
        
        # Then join group
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
        
        # Start keep-alive
        self.keep_alive_task = asyncio.create_task(self.send_keep_alive())
        
    async def send_keep_alive(self):
        """Send keep-alive messages every 20 seconds"""
        while True:
            await asyncio.sleep(20)
            try:
                await self.send(text_data=json.dumps({
                    'type': 'keep_alive',
                    'message': 'ping'
                }))
                print(f"💓 Keep-alive sent for {self.conversation_id}")
            except Exception as e:
                print(f"❌ Keep-alive failed: {e}")
                break
    
    async def disconnect(self, close_code):
        print(f"🔌 WebSocket disconnecting: {close_code} for {self.conversation_id}")
        
        # Cancel keep-alive task
        if self.keep_alive_task:
            self.keep_alive_task.cancel()
            
        # Leave group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        
        raise StopConsumer()
    
    async def receive(self, text_data):
        """Handle incoming client messages"""
        try:
            data = json.loads(text_data)
            print(f"📨 Received from client: {data}")
            
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'message': 'pong'
                }))
                
        except json.JSONDecodeError:
            pass
    
    async def send_webhook_message(self, event):
        """Forward webhook events to WebSocket"""
        try:
            message = event['message']
            print(f"📤 Forwarding webhook to WebSocket: {self.conversation_id}")
            
            await self.send(text_data=json.dumps({
                'type': 'webhook_event',
                'payload': message,
                'conversation_id': self.conversation_id
            }))
            
        except Exception as e:
            print(f"❌ Error sending webhook: {e}")