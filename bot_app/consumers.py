
import json
from channels.generic.websocket import AsyncWebsocketConsumer
import logging
import sys
import httpx
from bot_app.views import (
    get_sunshine_headers,
    send_message_to_sunshine as send_sunshine_message_http,
    init_conversation as init_conversation_http,
    get_conversation_messages as get_conversation_messages_http,
    escalate_to_agent as escalate_to_agent_http,
    csat_submit as csat_submit_http,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.conversation_group_name = f'chat_{self.conversation_id}'

        # Join room group
        await self.channel_layer.group_add(
            self.conversation_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.conversation_group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message_type = text_data_json.get('type')
        data = text_data_json.get('data', {})

        if message_type == 'init_chat':
            # This is just an example, the client will likely still call the HTTP endpoint for init
            pass
        elif message_type == 'send_message':
            await self.handle_send_message(data)
        elif message_type == 'send_attachment':
            await self.handle_send_attachment(data)
        elif message_type == 'fetch_messages':
            # This is now handled by the client requesting messages via the websocket
            # and the server pushing them.
            # We can also use this to trigger a refresh from the client.
            await self.handle_fetch_messages(data)

    async def handle_send_attachment(self, data):
        app_user_id = data.get("appUserId")
        conversation_id = data.get("conversationId")
        media_url = data.get("mediaUrl")
        text = data.get("text") # Optional text to go with the file

        from bot_app.views import SUNSHINE_API_BASE_URL, SUNSHINE_APP_ID
        

        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        
        # Determine content type (image or file)
        content_type = "file"
        if media_url.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
            content_type = "image"

        payload = {
            "author": {
                "type": "user",
                "userId": app_user_id
            },
            "content": {
                "type": content_type,
                "mediaUrl": media_url,
                "text": text
            }
        }

        headers = get_sunshine_headers()
        if not headers:
            logger.error("Server configuration error")
            return

        logger.info(f"Sending attachment to Sunshine: {url}")
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 201:
            logger.info("Attachment sent successfully")
        else:
            logger.error(f"Sunshine API Error (Send Attachment): {response.status_code} - {response.text}")


    async def handle_send_message(self, data):
        # Here you would call the function that sends the message to Sunshine
        # For simplicity, we are reusing the view logic, but in a real app
        # you might want to refactor this into a separate service layer.
        app_user_id = data.get("appUserId")
        conversation_id = data.get("conversationId")
        text = data.get("text")

        # This is a simplified example. You might need to make this async
        # or run it in a thread to avoid blocking.
        # For now, we'll just call it directly.
        # Note: The original view returns a JsonResponse. We'll need to adapt.
        
        # We can't directly call the view function as it expects an HttpRequest.
        # We will extract the core logic.
        from bot_app.views import SUNSHINE_API_BASE_URL, SUNSHINE_APP_ID
        

        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        payload = {
            "author": {
                "type": "user",
                "userId": app_user_id 
            },
            "content": {
                "type": "text",
                "text": text
            }
        }
        
        headers = get_sunshine_headers()
        if not headers:
            logger.error("Server configuration error")
            return

        logger.info(f"Sending message to Sunshine: {url}")
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)
        
        if response.status_code == 201:
            logger.info("Message sent successfully")
            # The webhook will receive the message and broadcast it to the group.
            # We don't need to do anything here.
        else:
            logger.error(f"Sunshine API Error (Send Message): {response.status_code} - {response.text}")


    async def handle_fetch_messages(self, data):
        conversation_id = data.get("conversationId")
        # Again, we can't call the view directly.
        from bot_app.views import SUNSHINE_API_BASE_URL, SUNSHINE_APP_ID
        

        headers = get_sunshine_headers()
        if not headers:
            return

        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)

            conv_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}"
            conv_response = await client.get(conv_url, headers=headers)
        
        conversation_data = {}
        if conv_response.status_code == 200:
            conversation_data = conv_response.json().get("conversation", {})

        if response.status_code == 200:
            messages_data = response.json()
            messages_data['conversation'] = conversation_data
            
            # Send message to the client that requested it
            await self.send(text_data=json.dumps({
                'type': 'messages',
                'messages': messages_data
            }))


    # Receive message from room group
    async def chat_message(self, event):
        message = event['message']

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'message': message
        }))
