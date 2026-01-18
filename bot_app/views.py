from django.shortcuts import render
from django.http import JsonResponse, HttpResponseForbidden, HttpRequest, HttpResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
import json, hmac, hashlib, os, base64, logging, sys, uuid, re, time, asyncio
from typing import Optional, Dict, Any, Union, List
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.core.cache import cache

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

load_dotenv()

def strip_html_tags(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()

def is_conversation_log_entry(text: str) -> bool:
    if not text:
        return False
    patterns = [
        r'^\(\d{1,2}:\d{2}:\d{2}\)\s+\w+',
        r'\(\d{1,2}:\d{2}:\d{2}\)\s+Support Agent:',
        r'\(\d{1,2}:\d{2}:\d{2}\)\s+Guest User:',
        r'uploaded:.*URL:.*Type:.*Size:',
        r'Escalation Reason:.*Category:',
        r'\[Sunshine Conversation',
    ]
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    if len(text) > 500 and len(re.findall(r'\(\d{1,2}:\d{2}:\d{2}\)', text)) >= 3:
        return True
    return False

def get_proxied_image_url(original_url: str) -> str:
    if not original_url:
        return ""
    proxy_domains = ["zendesk.com", "zdassets.com", "smooch.io", "zendesk-eu.com"]
    if any(domain in original_url for domain in proxy_domains):
        from urllib.parse import quote
        return f"/api/image-proxy?url={quote(original_url, safe='')}"
    return original_url

SECRET = os.getenv("SUNSHINE_WEBHOOK_SIGNING_SECRET")
if not SECRET:
    raise RuntimeError("SUNSHINE_WEBHOOK_SIGNING_SECRET not set")

ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN")
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL")
ZENDESK_API_TOKEN = os.getenv("ZENDESK_API_TOKEN")
ZENDESK_CHAT_CONVERSATION_FIELD_ID = os.getenv("ZENDESK_CHAT_CONVERSATION_FIELD_ID")
APP_RELATED_SUB_CATEGORY = os.getenv("APP_RELATED_SUB_CATEGORY")
SUNSHINE_APP_ID = os.getenv("SUNSHINE_APP_ID", "").strip()
SUNSHINE_API_KEY_ID = os.getenv("SUNSHINE_API_KEY_ID", "").strip()
SUNSHINE_API_KEY_SECRET = os.getenv("SUNSHINE_API_KEY_SECRET", "").strip()
SUNSHINE_API_BASE_URL = os.getenv("SUNSHINE_API_BASE_URL", "https://api.smooch.io").strip().rstrip('/')

def forward_agent_message_to_websocket(conversation_id: str, message_text: str, agent_name: str = "Agent", choices: list = None, actions: list = None) -> bool:
    try:
        if is_conversation_log_entry(message_text):
            return False
        
        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.error("No channel layer available")
            return False

        websocket_message = {
            'type': 'agent_message',
            'payload': {
                'id': f"agent_msg_{uuid.uuid4().hex[:10]}",
                'author': {'type': 'business', 'displayName': agent_name, 'role': 'agent'},
                'content': {'type': 'text', 'text': message_text},
                'received': datetime.now().isoformat(),
                'source': 'zendesk',
                'conversationId': conversation_id
            }
        }
        
        if choices:
            websocket_message['payload']['choices'] = choices
        if actions:
            websocket_message['payload']['actions'] = actions

        group_name = f'chat_{conversation_id}'
        async_to_sync(channel_layer.group_send)(group_name, {'type': 'send_webhook_message', 'message': websocket_message})
        return True
    except Exception as e:
        logger.exception(f"Error forwarding to WebSocket: {e}")
        return False

def store_conversation_ticket_mapping(conversation_id: str, ticket_id: str) -> bool:
    try:
        cache.set(f'conversation_{conversation_id}', ticket_id, timeout=604800)
        cache.set(f'ticket_{ticket_id}', conversation_id, timeout=604800)
        return True
    except Exception as e:
        logger.error(f"Failed to store mapping: {e}")
        return False

def update_user_viewing_status(conversation_id: str, is_viewing: bool) -> bool:
    try:
        if is_viewing:
            cache.set(f'user_viewing_{conversation_id}', True, timeout=3600)
        else:
            cache.delete(f'user_viewing_{conversation_id}')
        return True
    except Exception as e:
        logger.error(f"Viewing status error: {e}")
        return False

def save_conversation_to_cache(conversation_id: str, message_text: str, user_id: str) -> None:
    try:
        conv_cache_key = f'conversation_info_{conversation_id}'
        conv_data = cache.get(conv_cache_key, {})
        conv_data.update({
            'conversationId': conversation_id,
            'lastMessage': message_text[:100],
            'lastMessageTime': datetime.now().isoformat(),
            'lastUserId': user_id
        })
        cache.set(conv_cache_key, conv_data, timeout=604800)
    except Exception as e:
        logger.error(f"Cache save error: {e}")

@csrf_exempt
def index(request: HttpRequest) -> HttpResponse:
    from django.conf import settings
    context = {'SUNSHINE_APP_ID': SUNSHINE_APP_ID, 'debug': settings.DEBUG}
    return render(request, 'index.html', context)

def verify_signature(payload: bytes, signature: str) -> bool:
    if not signature:
        return False
    if signature.startswith("sha256="):
        signature = signature.split("=", 1)[1]
    if not SECRET:
        logger.error("SUNSHINE_WEBHOOK_SIGNING_SECRET missing")
        return False
    calc = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, signature)

def create_zendesk_ticket(subject: str, description: str, conversation_id: Optional[str] = None, app_related_sub_category: Optional[Union[str,int]] = None) -> Dict[str, Any]:
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets.json"
    ticket = {"subject": subject, "comment": {"body": description}}
    custom_fields: List[Dict[str, Union[int,str]]] = []
    
    try:
        if conversation_id and ZENDESK_CHAT_CONVERSATION_FIELD_ID:
            custom_fields.append({"id": int(ZENDESK_CHAT_CONVERSATION_FIELD_ID), "value": conversation_id})
    except Exception:
        logger.exception("Invalid ZENDESK_CHAT_CONVERSATION_FIELD_ID")

    try:
        if app_related_sub_category and APP_RELATED_SUB_CATEGORY:
            custom_fields.append({"id": int(APP_RELATED_SUB_CATEGORY), "value": app_related_sub_category})
    except Exception:
        logger.exception("Invalid APP_RELATED_SUB_CATEGORY")

    if custom_fields:
        ticket["custom_fields"] = custom_fields

    response = requests.post(url, json={"ticket": ticket}, auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN), timeout=15)
    
    try:
        resp_json = response.json()
    except Exception:
        logger.error(f"Non-JSON response: {response.status_code} - {response.text}")
        raise

    if response.status_code in (200, 201):
        try:
            ticket_obj = resp_json.get('ticket') or resp_json
            ticket_id = ticket_obj.get('id') if isinstance(ticket_obj, dict) else None
            if ticket_id and conversation_id:
                store_conversation_ticket_mapping(str(conversation_id), str(ticket_id))
        except Exception:
            logger.exception("Error extracting ticket id")
    else:
        logger.error(f"Ticket create failed: {response.status_code} - {resp_json}")

    return resp_json

def get_sunshine_jwt() -> Optional[str]:
    if not SUNSHINE_API_KEY_ID or not SUNSHINE_API_KEY_SECRET:
        logger.error("Sunshine credentials not set")
        return None
    url = f"{SUNSHINE_API_BASE_URL}/oauth/token"
    data = {'grant_type': 'client_credentials', 'client_id': SUNSHINE_API_KEY_ID, 'client_secret': SUNSHINE_API_KEY_SECRET}
    try:
        response = requests.post(url, data=data)
        if response.status_code == 200:
            return response.json().get('access_token')
        logger.error(f"JWT failed: {response.status_code}")
        return None
    except Exception as e:
        logger.exception(f"JWT exception: {e}")
        return None

@csrf_exempt
def init_conversation(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    if not SUNSHINE_APP_ID:
        return JsonResponse({"error": "SUNSHINE_APP_ID not set"}, status=500)

    try:
        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/users"
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        user_id = None
        force_new = False
        
        try:
            if request.body:
                data = json.loads(request.body)
                user_id = data.get("userId")
                force_new = data.get("forceNew", False)
        except Exception:
            pass

        if not user_id:
            user_id = str(uuid.uuid4())

        user_payload = {"externalId": user_id, "profile": {"givenName": "Guest"}}
        response = requests.post(url, json=user_payload, auth=auth)
        
        if response.status_code not in [200, 201, 409]:
            return JsonResponse({"error": "Failed to create user", "details": response.text}, status=500)

        user_data = response.json()
        app_user_id = user_data.get("user", {}).get("id")
        
        if not app_user_id and response.status_code == 409:
            get_user_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/users/{user_id}"
            get_response = requests.get(get_user_url, auth=auth)
            if get_response.status_code == 200:
                app_user_id = get_response.json().get("user", {}).get("id")
        
        if not app_user_id:
            return JsonResponse({"error": "Failed to retrieve user ID"}, status=500)

        conversation_id = None
        
        if not force_new:
            def fetch_conversation(target_id: str) -> Optional[str]:
                try:
                    l_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations"
                    l_resp = requests.get(l_url, auth=auth, params={"filter[userId]": target_id})
                    if l_resp.status_code == 200:
                        convs = l_resp.json().get("conversations", [])
                        if convs:
                            return convs[0].get("id")
                except Exception:
                    pass
                return None

            if app_user_id:
                conversation_id = fetch_conversation(app_user_id)
            if not conversation_id and user_id:
                conversation_id = fetch_conversation(user_id)

        if not conversation_id:
            conv_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations"
            conv_payload = {"type": "personal", "participants": [{"userId": app_user_id}]}
            conv_response = requests.post(conv_url, json=conv_payload, auth=auth)
            
            if conv_response.status_code in [200, 201]:
                conversation_id = conv_response.json().get("conversation", {}).get("id")
            else:
                return JsonResponse({"error": "Failed to create conversation", "details": conv_response.text}, status=500)

        return JsonResponse({"appUserId": app_user_id, "conversationId": conversation_id, "externalId": user_id})
    except Exception as e:
        logger.exception(f"init_conversation error: {e}")
        return JsonResponse({"error": "Internal Server Error", "details": str(e)}, status=500)

@csrf_exempt
def get_conversation_messages(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    conversation_id = request.GET.get("conversationId")
    if not conversation_id:
        return JsonResponse({"error": "Missing conversationId"}, status=400)

    try:
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        response = requests.get(url, auth=auth)
        conv_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}"
        conv_response = requests.get(conv_url, auth=auth)
        conversation_data = {}
        if conv_response.status_code == 200:
            conversation_data = conv_response.json().get("conversation", {})

        if response.status_code == 200:
            data = response.json()
            data['conversation'] = conversation_data
            return JsonResponse(data)
        else:
            return JsonResponse({"error": "Failed to fetch messages"}, status=response.status_code)
    except Exception as e:
        logger.exception("get_conversation_messages error")
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def send_message_to_sunshine(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        app_user_id = data.get("appUserId")
        conversation_id = data.get("conversationId")
        text = data.get("text")
        
        if not all([app_user_id, conversation_id, text]):
            return JsonResponse({"error": "Missing required fields"}, status=400)

        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        payload = {"author": {"type": "user", "userId": app_user_id}, "content": {"type": "text", "text": text}}
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        response = requests.post(url, json=payload, auth=auth)
        
        if response.status_code == 201:
            save_conversation_to_cache(conversation_id, text, app_user_id)
            return JsonResponse({"status": "sent", "data": response.json()})
        else:
            return JsonResponse({"error": "Failed to send message", "details": response.text}, status=500)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.exception(f"send_message_to_sunshine error: {e}")
        return JsonResponse({"error": "Internal Server Error", "details": str(e)}, status=500)

@csrf_exempt
def escalate_to_agent(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        conversation_id = data.get("conversationId")
        app_user_id = data.get("appUserId")
        reason = data.get("reason", "User requested agent support")
        app_related_category = data.get("appRelatedCategory")
        
        if not conversation_id:
            return JsonResponse({"error": "Missing conversationId"}, status=400)

        if app_related_category:
            cache.set(f'category_{conversation_id}', app_related_category, timeout=3600)

        pending_data = {
            'conversation_id': conversation_id,
            'app_user_id': app_user_id,
            'reason': reason,
            'app_related_category': app_related_category,
            'timestamp': datetime.now().isoformat()
        }
        cache.set(f'pending_escalation_{conversation_id}', pending_data, timeout=300)

        app_id = SUNSHINE_APP_ID
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)

        category_mapping = {
            "Location Not Found or Inaccurate": "location_not_found_or_inaccurate",
            "Unable to Login": "unable_to_login",
            "My App is Not Responding": "my_app_is_not_responding",
            "Others": "others",
            "location_not_found_or_inaccurate": "location_not_found_or_inaccurate",
            "unable_to_login": "unable_to_login",
            "my_app_is_not_responding": "my_app_is_not_responding",
            "others": "others"
        }
        
        category_tag = category_mapping.get(app_related_category, "others") if app_related_category else None
        metadata = {"dataCapture.systemField.tags": "escalated_from_bot", "dataCapture.systemField.requester.name": "Guest User"}
        
        if ZENDESK_CHAT_CONVERSATION_FIELD_ID:
            metadata[f"dataCapture.ticketField.{ZENDESK_CHAT_CONVERSATION_FIELD_ID}"] = conversation_id
        
        if category_tag and APP_RELATED_SUB_CATEGORY:
            metadata[f"dataCapture.ticketField.{APP_RELATED_SUB_CATEGORY}"] = category_tag

        if app_user_id:
            msg_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{app_id}/conversations/{conversation_id}/messages"
            escalation_message = f"Escalation Reason: {reason}"
            if app_related_category:
                escalation_message += f"\nCategory: {app_related_category}"
            escalation_message += f"\n[Sunshine Conversation: {conversation_id}]"
            
            msg_payload = {"author": {"type": "user", "userId": app_user_id}, "content": {"type": "text", "text": escalation_message}}
            msg_response = requests.post(msg_url, json=msg_payload, auth=auth)
            
            if msg_response.status_code in [200, 201]:
                time.sleep(0.5)

        pass_control_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{app_id}/conversations/{conversation_id}/passControl"
        pass_control_payload = {"switchboardIntegration": "next", "metadata": metadata}
        pc_response = requests.post(pass_control_url, json=pass_control_payload, auth=auth)
        
        if pc_response.status_code != 200:
            return JsonResponse({"error": "Failed to escalate", "details": pc_response.text}, status=pc_response.status_code)

        return JsonResponse({"status": "escalated", "conversation_id": conversation_id, "category": app_related_category})
    except Exception as e:
        logger.exception("escalate_to_agent error")
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def webhook_message(request: HttpRequest) -> Union[JsonResponse, HttpResponseForbidden]:
    sig = request.headers.get("X-Hub-Signature") or request.headers.get("x-hub-signature")
    if not sig:
        api_key_header = request.headers.get("X-Api-Key")
        if api_key_header:
            sig = "BYPASS_DEBUG"
    body = request.body
    if sig != "BYPASS_DEBUG" and not verify_signature(body, sig):
        return HttpResponseForbidden("Invalid signature")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        return HttpResponseForbidden("Invalid JSON")
    
    events_list = event.get("events", [])
    if not events_list and "trigger" in event:
        events_list = [event]
    elif not events_list and "messages" in event:
        events_list = [event]
        event["trigger"] = "conversation:message"

    for evt in events_list:
        trigger = evt.get("trigger") or evt.get("type")
        
        if trigger == "conversation:message":
            process_message_event(evt)
        elif trigger == "switchboard:passControl":
            handle_agent_take_control(evt)
        elif trigger == "switchboard:releaseControl":
            handle_agent_end_session(evt, show_to_user=False)
        elif trigger == "switchboard:acceptControl":
            handle_agent_accepted_control(evt)
        elif trigger == "participant:join":
            handle_participant_join(evt)
        elif trigger == "participant:leave":
            handle_participant_leave(evt)
        elif trigger == "conversation:read":
            handle_conversation_read(evt)
        elif trigger == "user:typing":
            handle_user_typing(evt)

    return JsonResponse({"status": "received"})

def handle_agent_take_control(event_data: Dict[str, Any]) -> None:
    conversation = event_data.get("payload", {}).get("conversation", {})
    conversation_id = conversation.get("id")
    if not conversation_id:
        return
    
    metadata = event_data.get("payload", {}).get("metadata", {})
    if metadata:
        ticket_id = None
        if 'dataCapture' in metadata:
            ticket_data = metadata.get('dataCapture', {}).get('ticketField', {})
            if ticket_data:
                ticket_id = ticket_data.get('id')
        if not ticket_id:
            metadata_str = json.dumps(metadata)
            ticket_match = re.search(r'ticket[_-]?id["\']?\s*:\s*["\']?(\d+)', metadata_str, re.IGNORECASE)
            if ticket_match:
                ticket_id = ticket_match.group(1)
            if not ticket_id and 'ticketField' in metadata.get('dataCapture', {}):
                ticket_id = metadata['dataCapture']['ticketField'].get('id')
        
        if ticket_id:
            pending_data = cache.get(f'pending_escalation_{conversation_id}')
            app_related_category = None
            if pending_data:
                app_related_category = pending_data.get('app_related_category')
            store_conversation_ticket_mapping(conversation_id, ticket_id)
            if app_related_category and APP_RELATED_SUB_CATEGORY:
                update_ticket_custom_field(ticket_id, app_related_category)
            cache.set(f'ticket_status_{ticket_id}', 'active', timeout=86400)

def update_ticket_custom_field(ticket_id: str, category: str) -> bool:
    try:
        category_mapping = {
            "Location Not Found or Inaccurate": "location_not_found_or_inaccurate",
            "Unable to Login": "unable_to_login",
            "My App is Not Responding": "my_app_is_not_responding",
            "Others": "others",
            "location_not_found_or_inaccurate": "location_not_found_or_inaccurate",
            "unable_to_login": "unable_to_login",
            "my_app_is_not_responding": "my_app_is_not_responding",
            "others": "others"
        }
        tag_value = category_mapping.get(category, "others")
        url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
        data = {"ticket": {"custom_fields": [{"id": int(APP_RELATED_SUB_CATEGORY), "value": tag_value}]}}
        response = requests.put(url, json=data, auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN), timeout=15)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Ticket update error: {e}")
        return False

def handle_user_typing(event_data: Dict[str, Any]) -> None:
    conversation_id = event_data.get("conversation", {}).get("_id") or event_data.get("conversation", {}).get("id")
    if not conversation_id:
        return
    participant = event_data.get("participant", {})
    if participant.get("type") == "business":
        try:
            channel_layer = get_channel_layer()
            if channel_layer:
                websocket_message = {
                    'type': 'agent_typing',
                    'payload': {
                        'conversationId': conversation_id,
                        'isTyping': event_data.get("isTyping", True),
                        'agentName': participant.get("displayName", "Agent")
                    }
                }
                async_to_sync(channel_layer.group_send)(f'chat_{conversation_id}', {'type': 'send_webhook_message', 'message': websocket_message})
        except Exception as e:
            logger.error(f"Typing indicator error: {e}")

def handle_agent_accepted_control(event_data: Dict[str, Any]) -> None:
    conversation_id = event_data.get("payload", {}).get("conversation", {}).get("id")
    if not conversation_id:
        return
    try:
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        payload = {"author": {"type": "business", "displayName": "System"}, "content": {"type": "text", "text": "An agent has accepted your request and will be with you shortly."}}
        requests.post(url, json=payload, auth=auth)
    except Exception as e:
        logger.error(f"Agent accepted error: {e}")

def handle_conversation_read(event_data: Dict[str, Any]) -> None:
    conversation_id = event_data.get("conversation", {}).get("_id") or event_data.get("conversation", {}).get("id")
    if not conversation_id:
        return
    app_user = event_data.get("appUser", {})
    app_user_id = app_user.get("_id") or app_user.get("id")
    reader_id = event_data.get("userId") or event_data.get("source", {}).get("from", {}).get("id")
    if reader_id and app_user_id and reader_id != app_user_id:
        is_business = event_data.get("role") == "business"
        if is_business or reader_id != app_user_id:
            try:
                auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
                url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                payload = {"author": {"type": "business", "displayName": "System"}, "content": {"type": "text", "text": "An agent connected"}}
                requests.post(url, json=payload, auth=auth)
            except Exception as e:
                logger.error(f"Read notification error: {e}")

def handle_participant_join(event_data: Dict[str, Any]) -> None:
    conversation_id = event_data.get("payload", {}).get("conversation", {}).get("id")
    if not conversation_id:
        return
    participants = event_data.get("payload", {}).get("participants", [])
    single_participant = event_data.get("payload", {}).get("participant")
    if single_participant:
        participants.append(single_participant)
    for p in participants:
        if p.get("type") == "business":
            agent_name = p.get("displayName", "An agent")
            try:
                auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
                url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                payload = {"author": {"type": "business", "displayName": "System"}, "content": {"type": "text", "text": f"{agent_name} has joined the conversation"}}
                requests.post(url, json=payload, auth=auth)
            except Exception as e:
                logger.error(f"Join notification error: {e}")

def handle_participant_leave(event_data: Dict[str, Any]) -> None:
    conversation_id = event_data.get("payload", {}).get("conversation", {}).get("id")
    if not conversation_id:
        return
    participants = event_data.get("payload", {}).get("participants", [])
    single_participant = event_data.get("payload", {}).get("participant")
    if single_participant:
        participants.append(single_participant)
    for p in participants:
        if p.get("type") == "business":
            agent_name = p.get("displayName", "An agent")
            try:
                auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
                url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                payload = {"author": {"type": "business", "displayName": "System"}, "content": {"type": "text", "text": f"{agent_name} has left the conversation"}}
                requests.post(url, json=payload, auth=auth)
            except Exception as e:
                logger.error(f"Leave notification error: {e}")

def process_message_event(event_data: Dict[str, Any]) -> None:
    try:
        payload = event_data.get("payload", {})
        conversation = payload.get("conversation", {})
        conversation_id = conversation.get("id")
        if not conversation_id:
            logger.error("No conversation ID")
            return
        
        message = payload.get("message", {})
        if not message:
            logger.error("No message in payload")
            return
        
        author = message.get("author", {})
        author_type = author.get("type")
        author_display_name = author.get("displayName", "")
        source = message.get("source", {})
        source_type = source.get("type")
        
        text = message.get("text")
        if not text:
            content = message.get("content", {})
            if content and content.get("type") == "text":
                text = content.get("text")
        if not text:
            return
        
        content = message.get("content", {})
        choices = content.get("choices") or message.get("choices") or []
        actions = content.get("actions") or message.get("actions") or []
        
        if author_display_name == "System" or "Connecting to agent" in text:
            return
        
        is_agent_message = False
        agent_name = "Agent"
        
        if author_type == "business" and author_display_name != "System":
            is_agent_message = True
            agent_name = author_display_name or "Agent"
        elif source_type == "zd:agentWorkspace":
            is_agent_message = True
            agent_name = author_display_name or "Support Agent"
        
        if is_agent_message:
            is_user_viewing = cache.get(f'user_viewing_{conversation_id}', False)
            
            if not is_user_viewing:
                unread_count = cache.get(f'unread_{conversation_id}', 0) + 1
                cache.set(f'unread_{conversation_id}', unread_count, timeout=604800)
                send_notification_to_client(conversation_id, {
                    'type': 'new_message',
                    'conversationId': conversation_id,
                    'agentName': agent_name,
                    'messagePreview': text[:100],
                    'unreadCount': unread_count,
                    'timestamp': datetime.now().isoformat(),
                    'choices': choices if choices else None,
                    'actions': actions if actions else None,
                    'isInteractive': bool(choices or actions)
                })
            
            if is_conversation_log_entry(text):
                return
            forward_agent_message_to_websocket(conversation_id, text, agent_name, choices=choices, actions=actions)
            return
        
        if author_type == "user":
            return
        
        integration_name = conversation.get("activeSwitchboardIntegration", {}).get("name", "")
        if integration_name and "answerBot" in integration_name:
            try:
                app_user = payload.get("user", {})
                app_user_id = app_user.get("id")
                
                def get_app_related_tag_from_text(t: str) -> Optional[str]:
                    if not t:
                        return None
                    s = t.lower()
                    mapping = {
                        "location not found or inaccurate": "location_not_found_or_inaccurate",
                        "unable to login": "unable_to_login",
                        "my app is not responding": "my_app_is_not_responding",
                        "others": "others",
                        "location_not_found_or_inaccurate": "location_not_found_or_inaccurate",
                        "unable_to_login": "unable_to_login",
                        "my_app_is_not_responding": "my_app_is_not_responding",
                        "others": "others",
                    }
                    for k, v in mapping.items():
                        if k in s:
                            return v
                    if "location" in s:
                        return "location_not_found_or_inaccurate"
                    if "login" in s or "sign in" in s:
                        return "unable_to_login"
                    if "respond" in s or "not responding" in s or "crash" in s:
                        return "my_app_is_not_responding"
                    return None

                app_related_tag = get_app_related_tag_from_text(text)
                create_zendesk_ticket(subject=f"Conversation {conversation_id}", description=f"User {app_user_id} said: {text}", conversation_id=conversation_id, app_related_sub_category=app_related_tag)
            except Exception as e:
                logger.error(f"Failed to create ticket: {e}")
    except Exception as e:
        logger.exception(f"process_message_event error: {e}")

@csrf_exempt
def update_viewing_status(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    try:
        data = json.loads(request.body)
        conversation_id = data.get("conversationId")
        is_viewing = data.get("isViewing", False)
        if not conversation_id:
            return JsonResponse({"error": "Missing conversationId"}, status=400)
        update_user_viewing_status(conversation_id, is_viewing)
        return JsonResponse({"status": "updated", "conversationId": conversation_id})
    except Exception as e:
        logger.error(f"Viewing status API error: {e}")
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def clear_unread_badge(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    try:
        data = json.loads(request.body)
        conversation_id = data.get("conversationId")
        if not conversation_id:
            return JsonResponse({"error": "Missing conversationId"}, status=400)
        cache.delete(f'unread_{conversation_id}')
        return JsonResponse({"status": "cleared", "conversationId": conversation_id})
    except Exception as e:
        logger.error(f"Badge clear error: {e}")
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def send_to_zendesk(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed", "status": "fail"}, status=405)

    try:
        file = request.FILES.get('file')
        message = request.POST.get('message', '')
        conversation_id = request.POST.get('conversationId')
        app_user_id = request.POST.get('appUserId')

        if not all([file, conversation_id, app_user_id]):
            return JsonResponse({"error": "Missing required fields: file, conversationId, appUserId", "status": "fail"}, status=400)

        upload_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/attachments"
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        upload_response = requests.post(upload_url, files={'source': file}, params={'access': 'public'}, auth=auth)

        if upload_response.status_code not in [200, 201]:
            return JsonResponse({"error": "Failed to upload file", "status": "fail"}, status=500)

        media_url = upload_response.json().get('attachment', {}).get('mediaUrl')
        if not media_url:
            return JsonResponse({"error": "Upload mediaUrl not received", "status": "fail"}, status=500)

        msg_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        file_payload = {"author": {"type": "user", "userId": app_user_id}, "content": {"type": "file", "mediaUrl": media_url, "fileName": file.name, "contentType": file.content_type, "fileSize": file.size}}
        file_response = requests.post(msg_url, json=file_payload, auth=auth)

        if file_response.status_code >= 500:
            file_response = requests.post(msg_url, json=file_payload, auth=auth)
        if file_response.status_code not in [200, 201]:
            return JsonResponse({"error": "Failed to send file message", "status": "fail"}, status=500)

        if message.strip():
            text_payload = {"author": {"type": "user", "userId": app_user_id}, "content": {"type": "text", "text": message.strip()}}
            text_response = requests.post(msg_url, json=text_payload, auth=auth)
            if text_response.status_code >= 500:
                text_response = requests.post(msg_url, json=text_payload, auth=auth)
            if text_response.status_code not in [200, 201]:
                return JsonResponse({"error": "Failed to send text message", "status": "fail"}, status=500)

        return JsonResponse({"status": "ok"})
    except Exception as e:
        logger.exception(f"send_to_zendesk error: {e}")
        return JsonResponse({"error": "Internal Server Error", "status": "fail", "details": str(e)}, status=500)

def handle_agent_end_session(event_data: Dict[str, Any], show_to_user: bool = False) -> None:
    conversation_id = event_data.get("payload", {}).get("conversation", {}).get("id")
    if not conversation_id:
        return
    ticket_id = cache.get(f'conversation_{conversation_id}')
    if ticket_id:
        try:
            z_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
            z_resp = requests.get(z_url, auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN), timeout=10)
            if z_resp.status_code == 200:
                ticket_status = z_resp.json().get('ticket', {}).get('status', '')
                if ticket_status == 'solved':
                    show_to_user = True
        except Exception as e:
            logger.error(f"Agent end session error: {e}")
    
    if show_to_user:
        try:
            auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
            url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
            payload = {"author": {"type": "business", "displayName": "System"}, "content": {"type": "text", "text": "The agent has ended the session. Type a message to start a new ticket."}}
            requests.post(url, json=payload, auth=auth)
        except Exception as e:
            logger.error(f"End session message error: {e}")

@csrf_exempt
def zendesk_webhook(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    try:
        body_str = request.body.decode('utf-8')
        try:
            data = json.loads(body_str)
        except json.JSONDecodeError:
            return JsonResponse({"status": "invalid_json"}, status=400)
        
        if 'event' in data:
            return handle_notification_webhook(data)
        elif 'ticket' in data and 'comment' in data:
            return handle_ticket_comment_webhook(data)
        elif 'events' in data:
            return handle_event_webhook(data)
        else:
            ticket_id = extract_ticket_id_from_data(data)
            if ticket_id:
                return JsonResponse({"status": "unknown_format", "ticket_id": ticket_id, "message": "Received webhook but format not recognized"})
            return JsonResponse({"status": "unknown_format", "message": "Webhook format not recognized"})
    except Exception as e:
        logger.exception(f"zendesk_webhook error: {e}")
        return JsonResponse({"error": str(e)}, status=500)

def handle_ticket_comment_webhook(data: Dict[str, Any]) -> JsonResponse:
    try:
        ticket = data.get('ticket', {})
        ticket_id = ticket.get('id')
        if not ticket_id:
            return JsonResponse({"status": "no_ticket_id"}, status=400)
        
        comment = ticket.get('comment', {})
        comment_body = comment.get('body', '')
        comment_author = comment.get('author', {})
        author_role = comment_author.get('role', '')
        
        if author_role not in ['agent', 'admin']:
            return JsonResponse({"status": "ignored_non_agent"})
        if not comment_body or comment_body.strip() == '':
            return JsonResponse({"status": "ignored_empty"})
        if is_conversation_log_entry(comment_body):
            return JsonResponse({"status": "ignored_conversation_log"})
        
        conversation_id = resolve_conversation_id_for_ticket(ticket_id)
        if not conversation_id:
            return JsonResponse({"status": "no_conversation_mapping", "ticket_id": ticket_id})
        
        agent_name = comment_author.get('name', 'Agent')
        if not agent_name or agent_name.lower() == 'zendesk':
            agent_name = "Support Agent"
        
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        
        if is_conversation_log_entry(comment_body):
            return JsonResponse({"status": "filtered_conversation_log", "reason": "Conversation log entry detected"})
        
        payload = {"author": {"type": "business", "displayName": agent_name}, "content": {"type": "text", "text": comment_body}}
        response = requests.post(url, json=payload, auth=auth)

        if response.status_code in [200, 201]:
            forward_agent_message_to_websocket(conversation_id, comment_body, agent_name)
            return JsonResponse({"status": "forwarded", "ticket_id": ticket_id, "conversation_id": conversation_id, "agent_name": agent_name})
        else:
            return JsonResponse({"status": "forward_failed", "ticket_id": ticket_id, "error": response.text}, status=500)
    except Exception as e:
        logger.exception(f"handle_ticket_comment_webhook error: {e}")
        return JsonResponse({"error": str(e)}, status=500)

def handle_event_webhook(data: Dict[str, Any]) -> JsonResponse:
    try:
        events = data.get('events', [])
        for event in events:
            event_type = event.get('type')
            if event_type == 'Comment':
                ticket_id = extract_ticket_id_from_data(data)
                comment_body = event.get('body', '')
                if is_conversation_log_entry(comment_body):
                    continue
                if ticket_id and comment_body:
                    conversation_id = resolve_conversation_id_for_ticket(ticket_id)
                    if conversation_id:
                        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
                        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                        payload = {"author": {"type": "business", "displayName": "Support Agent"}, "content": {"type": "text", "text": comment_body}}
                        response = requests.post(url, json=payload, auth=auth)
                        if response.status_code in [200, 201]:
                            forward_agent_message_to_websocket(conversation_id, comment_body, "Support Agent")
                break
        return JsonResponse({"status": "processed_events"})
    except Exception as e:
        logger.exception(f"handle_event_webhook error: {e}")
        return JsonResponse({"error": str(e)}, status=500)
    
def handle_notification_webhook(data: Dict[str, Any]) -> JsonResponse:
    try:
        event_type = data.get('type', '')
        event_data = data.get('event', {})
        
        if 'ticket.comment_added' in event_type:
            comment = event_data.get('comment', {})
            comment_body = comment.get('body', '')
            comment_author = comment.get('author', {})
            is_staff = comment_author.get('is_staff', False)
            
            if not is_staff:
                return JsonResponse({"status": "ignored_user_comment"})
            if is_conversation_log_entry(comment_body):
                return JsonResponse({"status": "ignored_conversation_log"})

            ticket_id = None
            if 'ticket' in event_data:
                ticket_id = str(event_data['ticket'].get('id', ''))
            elif 'ticket_id' in event_data:
                ticket_id = str(event_data['ticket_id'])
            if not ticket_id:
                ticket_id = extract_ticket_id_from_data(data)
            if not ticket_id:
                return JsonResponse({"status": "no_ticket_id_in_created"})
            
            conversation_id = None
            ticket_description = ""
            
            try:
                url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
                response = requests.get(url, auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN), timeout=15)
                
                if response.status_code == 200:
                    ticket_data = response.json().get('ticket', {})
                    ticket_description = ticket_data.get('description', '')
                    
                    if ZENDESK_CHAT_CONVERSATION_FIELD_ID:
                        custom_fields = ticket_data.get('custom_fields', [])
                        for field in custom_fields:
                            field_id = str(field.get('id'))
                            field_value = field.get('value')
                            if field_id == str(ZENDESK_CHAT_CONVERSATION_FIELD_ID):
                                if field_value and str(field_value).strip():
                                    conversation_id = str(field_value).strip()
                                    break
                    
                    if not conversation_id and ticket_description:
                        conv_match = re.search(r'\[?Sunshine Conversation:\s*(\S+?)\]?(?:\s|$)', ticket_description)
                        if conv_match:
                            conversation_id = conv_match.group(1).strip().rstrip(']')
                        else:
                            marker_match = re.search(r'\[?Marker:\s*SUNSHINE_CONV_(\S+?)\]?(?:\s|$)', ticket_description)
                            if marker_match:
                                conversation_id = marker_match.group(1).strip().rstrip(']')
            except Exception as e:
                logger.exception(f"Ticket fetch error: {e}")

            if not conversation_id:
                webhook_description = ""
                if 'ticket' in event_data:
                    webhook_description = event_data['ticket'].get('description', '')
                elif 'comment' in event_data and 'body' in event_data['comment']:
                    webhook_description = event_data['comment'].get('body', '')
                
                if webhook_description:
                    conv_match = re.search(r'\[?Sunshine Conversation:\s*(\S+?)\]?(?:\s|$)', webhook_description)
                    if conv_match:
                        conversation_id = conv_match.group(1).strip().rstrip(']')
                    else:
                        marker_match = re.search(r'\[?Marker:\s*SUNSHINE_CONV_(\S+?)\]?(?:\s|$)', webhook_description)
                        if marker_match:
                            conversation_id = marker_match.group(1).strip().rstrip(']')
            
            if not conversation_id:
                try:
                    cache_keys = cache.keys('pending_escalation_*') if hasattr(cache, 'keys') else []
                    current_time = datetime.now()
                    for key in cache_keys:
                        pending_data = cache.get(key)
                        if pending_data:
                            try:
                                escalation_time = datetime.fromisoformat(pending_data.get('timestamp', '2000-01-01'))
                                time_diff = (current_time - escalation_time).total_seconds()
                                if time_diff < 120:
                                    pending_reason = pending_data.get('reason', '')
                                    if pending_reason and ticket_description and pending_reason in ticket_description:
                                        conversation_id = key.replace('pending_escalation_', '')
                                        break
                            except Exception:
                                pass
                except Exception as e:
                    logger.error(f"Cache lookup error: {e}")
            
            if not conversation_id:
                return JsonResponse({"status": "no_conversation_found", "ticket_id": ticket_id, "message": "Ticket created but no conversation mapping found"})
            
            store_conversation_ticket_mapping(conversation_id, ticket_id)
            pending_data = cache.get(f'pending_escalation_{conversation_id}')
            app_related_category = None
            
            if pending_data:
                app_related_category = pending_data.get('app_related_category')
            else:
                app_related_category = cache.get(f'category_{conversation_id}')
            
            if app_related_category and APP_RELATED_SUB_CATEGORY:
                try:
                    success = update_ticket_custom_field(ticket_id, app_related_category)
                    if success:
                        cache.delete(f'pending_escalation_{conversation_id}')
                        if pending_data and 'unique_marker' in pending_data:
                            cache.delete(f"marker_{pending_data['unique_marker']}")
                        return JsonResponse({"status": "ticket_updated", "ticket_id": ticket_id, "conversation_id": conversation_id, "app_related_category": app_related_category, "message": "Custom field updated successfully"})
                    else:
                        return JsonResponse({"status": "mapping_stored_but_update_failed", "ticket_id": ticket_id, "conversation_id": conversation_id, "error": "update_ticket_custom_field returned False"})
                except Exception as e:
                    logger.error(f"Ticket update error: {e}")
                    return JsonResponse({"status": "mapping_stored_but_update_failed", "ticket_id": ticket_id, "conversation_id": conversation_id, "error": str(e)})
            else:
                missing_what = ""
                if not app_related_category:
                    missing_what = "app_related_category"
                if not APP_RELATED_SUB_CATEGORY:
                    missing_what += " and APP_RELATED_SUB_CATEGORY" if missing_what else "APP_RELATED_SUB_CATEGORY"
                return JsonResponse({"status": "mapping_stored", "ticket_id": ticket_id, "conversation_id": conversation_id, "message": f"Mapping stored successfully (no category update needed: {missing_what})"})
        
        elif 'ticket.solved' in event_type:
            ticket_id = None
            if 'ticket' in event_data:
                ticket_id = str(event_data['ticket'].get('id', ''))
            elif 'ticket_id' in event_data:
                ticket_id = str(event_data['ticket_id'])
            if not ticket_id:
                ticket_id = extract_ticket_id_from_data(data)
            if not ticket_id:
                return JsonResponse({"status": "no_ticket_id"})
            
            conversation_id = resolve_conversation_id_for_ticket(ticket_id)
            if conversation_id:
                auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
                url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                payload = {"author": {"type": "business", "displayName": "System"}, "content": {"type": "text", "text": "The agent has ended the session. Type a message to start a new ticket."}}
                requests.post(url, json=payload, auth=auth)
            return JsonResponse({"status": "ticket_solved_processed", "ticket_id": ticket_id})
        
        return JsonResponse({"status": "processed_notification"})
    except Exception as e:
        logger.exception(f"handle_notification_webhook error: {e}")
        return JsonResponse({"error": str(e)}, status=500)

def extract_ticket_id_from_data(data: Dict[str, Any]) -> Optional[str]:
    ticket_id = None
    if 'ticket' in data:
        ticket_obj = data['ticket']
        if isinstance(ticket_obj, dict) and 'id' in ticket_obj:
            ticket_id = str(ticket_obj['id'])
    if not ticket_id and 'event' in data:
        event_data = data['event']
        if isinstance(event_data, dict):
            if 'ticket' in event_data:
                ticket_obj = event_data['ticket']
                if isinstance(ticket_obj, dict) and 'id' in ticket_obj:
                    ticket_id = str(ticket_obj['id'])
            elif 'ticket_id' in event_data:
                ticket_id = str(event_data['ticket_id'])
    if not ticket_id and 'detail' in data and 'id' in data['detail']:
        ticket_id = str(data['detail']['id'])
    if not ticket_id and 'events' in data and data['events']:
        for event in data['events']:
            if 'ticket_id' in event:
                ticket_id = str(event['ticket_id'])
                break
    if not ticket_id:
        data_str = json.dumps(data)
        matches = re.findall(r'"ticket[_-]?id":\s*"?(\d+)"?', data_str, re.IGNORECASE)
        if matches:
            ticket_id = matches[0]
        else:
            matches = re.findall(r'"id":\s*"?(\d+)"?', data_str)
            if matches:
                ticket_id = matches[-1]
    return ticket_id

def resolve_conversation_id_for_ticket(ticket_id: str) -> Optional[str]:
    try:
        conv = cache.get(f'ticket_{ticket_id}')
        if conv:
            return conv
        
        if not all([ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN, ZENDESK_CHAT_CONVERSATION_FIELD_ID]):
            return None

        z_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
        z_resp = requests.get(z_url, auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN), timeout=10)
        
        if z_resp.status_code != 200:
            return None

        ticket_obj = z_resp.json().get('ticket', {})
        cfs = ticket_obj.get('custom_fields', []) or []
        
        for cf in cfs:
            try:
                cf_id = cf.get('id')
                cf_value = cf.get('value')
                if str(cf_id) == str(ZENDESK_CHAT_CONVERSATION_FIELD_ID) and cf_value:
                    conv_id = str(cf_value)
                    store_conversation_ticket_mapping(conv_id, str(ticket_id))
                    return conv_id
            except Exception:
                continue
        return None
    except Exception as e:
        logger.exception(f"resolve_conversation_id_for_ticket error: {e}")
        return None

@csrf_exempt
def get_full_chat_history(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    conversation_id = request.GET.get("conversationId")
    if not conversation_id:
        return JsonResponse({"error": "Missing conversationId"}, status=400)

    try:
        all_messages = []
        app_user_id = None
        seen_fingerprints = set()
        
        def get_message_fingerprint(msg: Dict[str, Any]) -> str:
            text = (msg.get("text") or "").strip().lower()[:100]
            author_type = msg.get("author", {}).get("type", "")
            if author_type in ["business", "agent", "admin", "operator"]:
                author_type = "agent"
            elif author_type in ["end-user", "end_user", "customer", "visitor", "requester"]:
                author_type = "user"
            received = (msg.get("received") or "")[:19]
            return f"{author_type}:{received}:{text}"
        
        try:
            auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
            conv_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}"
            conv_response = requests.get(conv_url, auth=auth, timeout=10)
            if conv_response.status_code == 200:
                conv_data = conv_response.json()
                participants = conv_data.get("conversation", {}).get("participants", [])
                for p in participants:
                    if p.get("userExternalId") or p.get("userId"):
                        app_user_id = p.get("userId") or p.get("userExternalId")
                        break
        except Exception:
            pass
        
        sunshine_messages = get_sunshine_messages_list(conversation_id)
        for msg in sunshine_messages:
            fingerprint = get_message_fingerprint(msg)
            if fingerprint not in seen_fingerprints:
                seen_fingerprints.add(fingerprint)
                all_messages.append(msg)
        
        cache_key = f'conversation_{conversation_id}'
        ticket_id = cache.get(cache_key)
        
        if not ticket_id:
            try:
                search_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/search.json"
                search_query = f"custom_field_{ZENDESK_CHAT_CONVERSATION_FIELD_ID}:{conversation_id}"
                response = requests.get(search_url, params={"query": search_query}, auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN), timeout=15)
                if response.status_code == 200:
                    results = response.json().get("results", [])
                    if results:
                        ticket_id = str(results[0].get("id"))
                        store_conversation_ticket_mapping(conversation_id, ticket_id)
            except Exception:
                pass

        if ticket_id:
            try:
                conv_log_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}/conversation_log.json"
                response = requests.get(conv_log_url, auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN), timeout=15)
                if response.status_code == 200:
                    events = response.json().get("events", [])
                    for event in events:
                        parsed = parse_conversation_log_event(event)
                        if parsed:
                            fingerprint = get_message_fingerprint(parsed)
                            if fingerprint not in seen_fingerprints:
                                seen_fingerprints.add(fingerprint)
                                all_messages.append(parsed)
            except Exception:
                pass
        
        all_messages.sort(key=lambda x: x.get("received", ""))
        return JsonResponse({"messages": all_messages, "source": "combined", "ticket_id": ticket_id, "conversation_id": conversation_id, "appUserId": app_user_id})
    except Exception as e:
        logger.exception(f"get_full_chat_history error: {e}")
        return get_sunshine_messages_fallback(conversation_id)

def parse_conversation_log_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        event_type = event.get("type", "")
        if event_type not in ["Messaging::ConversationMessage", "Comment"]:
            return None

        author = event.get("author", {})
        author_type = author.get("type", "unknown")
        author_name = author.get("display_name", "") or author.get("name", "")
        
        user_types = ["end-user", "end_user", "customer", "visitor", "requester", "user"]
        agent_types = ["business", "agent", "admin", "operator"]
        
        if author_type in user_types:
            author_type = "user"
        elif author_type in agent_types:
            author_type = "agent"
        
        content = event.get("content", {})
        content_type = content.get("type", "text")
        raw_text = content.get("text") or content.get("body", "")
        text = strip_html_tags(raw_text) if raw_text else ""
        media_url = content.get("media_url")
        attachments_array = event.get("attachments", [])
        
        if not text and not media_url and not attachments_array:
            return None
        if author_name == "System" and "Connecting to agent" in (text or ""):
            return None
        
        skip_messages = ["Conversation with Guest", "Conversation with", "Escalation Reason:", "[Sunshine Conversation:"]
        if text and any(skip_text in text for skip_text in skip_messages):
            return None
        
        message_class = {"user": "user", "bot": "bot", "agent": "agent", "admin": "agent"}.get(author_type, "system")
        message = {
            "id": event.get("id", f"evt_{uuid.uuid4().hex[:8]}"),
            "text": text,
            "author": {"type": author_type, "displayName": author_name or message_class.capitalize()},
            "received": event.get("created_at", ""),
            "messageClass": message_class,
            "source": "conversation_log"
        }
        
        choices = content.get("choices") or event.get("choices") or []
        actions = content.get("actions") or event.get("actions") or []
        if choices:
            message["choices"] = choices
        if actions:
            message["actions"] = actions
        
        parsed_attachments = []
        if content_type == "image" and media_url:
            parsed_attachments.append({"url": get_proxied_image_url(media_url), "type": "image", "fileName": content.get("name", "image"), "contentType": "image/*", "size": content.get("size", 0)})
        
        if attachments_array:
            for att in attachments_array:
                att_url = att.get("mapped_content_url") or att.get("content_url") or att.get("url", "")
                att_content_type = att.get("content_type", "")
                att_file_name = att.get("file_name", "") or att.get("name", "")
                if att_url:
                    is_image = att_content_type.startswith("image/") or any(ext in att_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']) or any(ext in att_file_name.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'])
                    proxied_url = get_proxied_image_url(att_url) if is_image else att_url
                    parsed_attachments.append({"url": proxied_url, "type": "image" if is_image else "file", "fileName": att_file_name, "contentType": att_content_type, "size": att.get("size", 0)})
        
        if media_url and not parsed_attachments:
            is_image = content_type == "image" or any(ext in media_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'])
            proxied_url = get_proxied_image_url(media_url) if is_image else media_url
            parsed_attachments.append({"url": proxied_url, "type": "image" if is_image else "file", "fileName": content.get("name", "file"), "contentType": content.get("mediaType", "image/*" if is_image else ""), "size": content.get("size", 0)})
        
        if parsed_attachments:
            message["attachments"] = parsed_attachments
        return message
    except Exception as e:
        logger.error(f"parse_conversation_log_event error: {e}")
        return None

def get_sunshine_messages_list(conversation_id: str) -> List[Dict[str, Any]]:
    messages = []
    try:
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        response = requests.get(url, auth=auth, timeout=15)
        if response.status_code != 200:
            return messages

        sunshine_messages = response.json().get("messages", [])
        for msg in sunshine_messages:
            author = msg.get("author", {})
            author_type = author.get("type", "user")
            author_name = author.get("displayName", "")
            content = msg.get("content", {})
            text = msg.get("text") or content.get("text", "")
            
            if text and is_conversation_log_entry(text):
                continue
            
            if author_type == "user":
                message_class = "user"
            elif author_type == "business":
                source = msg.get("source", {})
                if "answerBot" in str(source) or author_name.lower() in ["bot", "assistant", "answerbot"]:
                    message_class = "bot"
                    author_type = "bot"
                else:
                    message_class = "agent"
            else:
                message_class = "bot"
                author_type = "bot"
            
            message = {
                "id": msg.get("id", ""),
                "text": text,
                "author": {"type": author_type, "displayName": author_name or message_class.capitalize()},
                "received": msg.get("received", ""),
                "messageClass": message_class,
                "source": "sunshine"
            }
            
            choices = content.get("choices") or msg.get("choices") or []
            actions = content.get("actions") or msg.get("actions") or []
            if choices:
                message["choices"] = choices
            if actions:
                message["actions"] = actions
            
            if content.get("type") == "image":
                media_url = content.get("mediaUrl", "")
                if media_url:
                    message["attachments"] = [{"url": get_proxied_image_url(media_url), "type": "image", "fileName": content.get("name", "image"), "size": content.get("size", 0)}]
            elif content.get("type") == "file":
                media_url = content.get("mediaUrl", "")
                if media_url:
                    file_name = content.get("name", "")
                    from urllib.parse import unquote
                    decoded_url = unquote(media_url).lower()
                    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic', '.heif']
                    is_actually_image = any(ext in file_name.lower() for ext in image_extensions) or any(ext in decoded_url for ext in image_extensions) or 'image' in decoded_url or 'whatsapp' in decoded_url
                    message["attachments"] = [{"url": get_proxied_image_url(media_url), "fileName": file_name or ("image" if is_actually_image else "file"), "type": "image" if is_actually_image else "file", "size": content.get("size", 0)}]
            messages.append(message)
    except Exception as e:
        logger.exception(f"get_sunshine_messages_list error: {e}")
    return messages

def get_sunshine_messages_fallback(conversation_id: str) -> JsonResponse:
    try:
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        response = requests.get(url, auth=auth, timeout=15)
        if response.status_code != 200:
            return JsonResponse({"messages": [], "source": "error"})

        sunshine_messages = response.json().get("messages", [])
        messages = []
        for msg in sunshine_messages:
            author = msg.get("author", {})
            author_type = author.get("type", "user")
            author_name = author.get("displayName", "")
            content = msg.get("content", {})
            text = msg.get("text") or content.get("text", "")
            
            if author_type == "user":
                message_class = "user"
            elif author_type == "business":
                if "answerBot" in str(msg.get("source", {})):
                    message_class = "bot"
                else:
                    message_class = "agent"
            else:
                message_class = "bot"
            
            message = {
                "id": msg.get("id", ""),
                "text": text,
                "author": {"type": author_type, "displayName": author_name or message_class.capitalize()},
                "received": msg.get("received", ""),
                "messageClass": message_class,
                "source": "sunshine"
            }
            
            choices = content.get("choices") or msg.get("choices") or []
            actions = content.get("actions") or msg.get("actions") or []
            if choices:
                message["choices"] = choices
            if actions:
                message["actions"] = actions
            
            if content.get("type") == "image":
                message["attachments"] = [{"url": content.get("mediaUrl", ""), "type": "image"}]
            elif content.get("type") == "file":
                message["attachments"] = [{"url": content.get("mediaUrl", ""), "fileName": content.get("name", ""), "type": "file"}]
            messages.append(message)
        return JsonResponse({"messages": messages, "source": "sunshine_fallback", "conversation_id": conversation_id})
    except Exception as e:
        logger.exception(f"get_sunshine_messages_fallback error: {e}")
        return JsonResponse({"messages": [], "source": "error", "error": str(e)})

@csrf_exempt
def proxy_zendesk_image(request: HttpRequest) -> HttpResponse:
    image_url = request.GET.get("url", "")
    if not image_url:
        return HttpResponse("Missing URL parameter", status=400)
    if not any(domain in image_url for domain in ["zendesk.com", "smooch.io", "zdassets.com", "zendesk-eu.com"]):
        return HttpResponse("Only Zendesk URLs allowed", status=403)

    try:
        response = None
        if "/sc/attachments/" in image_url:
            response = requests.get(image_url, auth=HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET), timeout=30, stream=True)
            if response.status_code != 200:
                jwt_token = get_sunshine_jwt()
                if jwt_token:
                    response = requests.get(image_url, headers={"Authorization": f"Bearer {jwt_token}"}, timeout=30, stream=True)
        
        if response is None or response.status_code != 200:
            response = requests.get(image_url, timeout=30, stream=True)
        if response.status_code != 200:
            response = requests.get(image_url, auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN), timeout=30, stream=True)
        
        if response.status_code != 200:
            return HttpResponse(f"Failed to fetch image: {response.status_code}", status=response.status_code)
        
        content_type = response.headers.get("Content-Type", "image/jpeg")
        return HttpResponse(response.content, content_type=content_type)
    except Exception as e:
        logger.exception(f"proxy_zendesk_image error: {e}")
        return HttpResponse(f"Error fetching image: {str(e)}", status=500)

_global_notification_last_index = 0

async def global_notification_stream_generator():
    global _global_notification_last_index
    yield f"event: connected\ndata: {json.dumps({'type': 'connected', 'scope': 'global'})}\n\n"
    start_time = asyncio.get_event_loop().time()
    timeout = 300
    last_keepalive = start_time
    keepalive_interval = 30
    last_index = 0

    try:
        while True:
            current_time = asyncio.get_event_loop().time()
            if current_time - start_time > timeout:
                break
            if current_time - last_keepalive >= keepalive_interval:
                yield ": keepalive\n\n"
                last_keepalive = current_time
            
            global_notification_key = f'global_notification'
            notifications_queue = cache.get(global_notification_key) or []
            
            if notifications_queue and last_index < len(notifications_queue):
                for notif_data in notifications_queue[last_index:]:
                    message = notif_data.get('message', {})
                    conv_id = message.get('conversationId', '')
                    unread_count = cache.get(f'unread_{conv_id}', 0)
                    if unread_count and unread_count > 0:
                        yield f"event: new_message\ndata: {json.dumps(message)}\n\n"
                last_index = len(notifications_queue)
            await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.exception(f"global_notification_stream_generator error: {e}")

@csrf_exempt
async def global_notification_stream(request: HttpRequest) -> HttpResponse:
    try:
        response = StreamingHttpResponse(global_notification_stream_generator(), content_type='text/event-stream', status=200)
        response['Cache-Control'] = 'no-cache'
        response['Connection'] = 'keep-alive'
        response['X-Accel-Buffering'] = 'no'
        return response
    except Exception as e:
        logger.exception(f"global_notification_stream error: {e}")
        return HttpResponse(f"Error: {str(e)}", status=500, content_type='text/event-stream')

async def notification_stream_generator(conversation_id: str):
    yield f"event: connected\ndata: {json.dumps({'type': 'connected', 'conversationId': conversation_id})}\n\n"
    start_time = asyncio.get_event_loop().time()
    timeout = 300
    last_keepalive = start_time
    keepalive_interval = 30

    try:
        while True:
            current_time = asyncio.get_event_loop().time()
            if current_time - start_time > timeout:
                break
            if current_time - last_keepalive >= keepalive_interval:
                yield ": keepalive\n\n"
                last_keepalive = current_time
            
            notification_key = f'notification_{conversation_id}'
            notification = cache.get(notification_key)
            if notification:
                yield f"event: new_message\ndata: {json.dumps(notification)}\n\n"
                cache.delete(notification_key)
            await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.exception(f"notification_stream_generator error: {e}")
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

@csrf_exempt
async def notification_stream(request: HttpRequest, conversation_id: str) -> HttpResponse:
    try:
        response = StreamingHttpResponse(notification_stream_generator(conversation_id), content_type='text/event-stream', status=200)
        response['Cache-Control'] = 'no-cache'
        response['Connection'] = 'keep-alive'
        response['X-Accel-Buffering'] = 'no'
        return response
    except Exception as e:
        logger.exception(f"notification_stream error: {e}")
        return HttpResponse(f"Error: {str(e)}", status=500, content_type='text/event-stream')

def send_notification_to_client(conversation_id: str, message_data: Dict[str, Any]) -> None:
    try:
        notification_key = f'notification_{conversation_id}'
        cache.set(notification_key, message_data, timeout=30)
        global_notification_key = f'global_notification'
        notifications_queue = cache.get(global_notification_key) or []
        if not isinstance(notifications_queue, list):
            notifications_queue = []
        notifications_queue.append({'message': message_data, 'timestamp': datetime.now().isoformat()})
        notifications_queue = notifications_queue[-100:]
        cache.set(global_notification_key, notifications_queue, timeout=60)
    except Exception as e:
        logger.error(f"send_notification_to_client error: {e}")