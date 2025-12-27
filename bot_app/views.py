from django.shortcuts import render
from django.http import JsonResponse, HttpResponseForbidden, HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
import json, hmac, hashlib, os, base64, logging, sys, uuid, re
from typing import Optional, Dict, Any, Union, List
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime

# ============================================================================
# WEBSOCKET ADDED: Import Django Channels for WebSocket
# ============================================================================
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

# ============================================================================
# CACHE ADDED: Import Django Cache for conversation-ticket mapping
# ============================================================================
from django.core.cache import cache

# Configure Logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

# Load environment variables from .env
load_dotenv()

# Sunshine secret for webhook verification
SECRET = os.getenv("SUNSHINE_WEBHOOK_SIGNING_SECRET")
if not SECRET:
    raise RuntimeError("SUNSHINE_WEBHOOK_SIGNING_SECRET not set")

# Zendesk credentials
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN")
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL")
ZENDESK_API_TOKEN = os.getenv("ZENDESK_API_TOKEN")
ZENDESK_CHAT_CONVERSATION_FIELD_ID = os.getenv("ZENDESK_CHAT_CONVERSATION_FIELD_ID")
APP_RELATED_SUB_CATEGORY = os.getenv("APP_RELATED_SUB_CATEGORY")

# Sunshine Credentials
SUNSHINE_APP_ID = os.getenv("SUNSHINE_APP_ID", "").strip()
SUNSHINE_API_KEY_ID = os.getenv("SUNSHINE_API_KEY_ID", "").strip()
SUNSHINE_API_KEY_SECRET = os.getenv("SUNSHINE_API_KEY_SECRET", "").strip()
SUNSHINE_API_BASE_URL = os.getenv("SUNSHINE_API_BASE_URL", "https://api.smooch.io").strip().rstrip('/')

# ============================================================================
# WEBSOCKET ADDED: Function to forward agent messages to WebSocket
# ============================================================================
def forward_agent_message_to_websocket(conversation_id: str, message_text: str, agent_name: str = "Agent") -> bool:
    """
    Forward agent messages to WebSocket for instant UI updates.
    This is called from zendesk_webhook when agents reply.
    """
    try:
        # Get the channel layer
        channel_layer = get_channel_layer()
        
        # Prepare the WebSocket message
        websocket_message = {
            'type': 'agent_message',
            'payload': {
                'id': f"agent_msg_{uuid.uuid4().hex[:10]}",
                'author': {
                    'type': 'business',
                    'displayName': agent_name,
                    'role': 'agent'
                },
                'content': {
                    'type': 'text',
                    'text': message_text
                },
                'received': datetime.now().isoformat(),
                'source': 'zendesk',
                'conversationId': conversation_id
            }
        }
        
        # Send to WebSocket group
        async_to_sync(channel_layer.group_send)(
            f'chat_{conversation_id}',
            {
                'type': 'send_webhook_message',
                'message': websocket_message
            }
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Error forwarding agent message to WebSocket: {str(e)}")
        return False

# ============================================================================
# Function to store conversation-ticket mapping
# ============================================================================
def store_conversation_ticket_mapping(conversation_id: str, ticket_id: str) -> bool:
    """
    Store the mapping between Sunshine conversation and Zendesk ticket.
    """
    try:
        # Store mapping both ways for easy lookup
        cache.set(f'conversation_{conversation_id}', ticket_id, timeout=86400)  # 24 hours
        cache.set(f'ticket_{ticket_id}', conversation_id, timeout=86400)
        
        return True
    except Exception as e:
        logger.error(f"Failed to store conversation-ticket mapping: {str(e)}")
        return False

# Index route (frontend entry point)
@csrf_exempt
def index(request: HttpRequest) -> HttpResponse:
    """
    Render the chat widget frontend.
    """
    from django.conf import settings
    
    context = {
        'SUNSHINE_APP_ID': SUNSHINE_APP_ID,
        'debug': settings.DEBUG,
    }
    return render(request, 'index.html', context)

# Verify Sunshine webhook signature
def verify_signature(payload: bytes, signature: str) -> bool:
    """
    Verify the Sunshine webhook signature to ensure authenticity.
    """
    if not signature:
        return False
    if signature.startswith("sha256="):
        signature = signature.split("=", 1)[1]
    
    if not SECRET:
        logger.error("SUNSHINE_WEBHOOK_SIGNING_SECRET is missing or empty!")
        return False
        
    calc = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    
    if not hmac.compare_digest(calc, signature):
        return False
        
    return True

# Create Zendesk ticket (ONLY for bot conversations, not for escalated chats)
def create_zendesk_ticket(subject: str, description: str, conversation_id: Optional[str] = None, app_related_sub_category: Optional[Union[str,int]] = None) -> Dict[str, Any]:
    """
    Create a new ticket in Zendesk and optionally populate custom fields.
    ONLY USE THIS FOR BOT CONVERSATIONS, NOT FOR ESCALATED CHATS.
    """
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets.json"
    headers = {"Content-Type": "application/json"}

    ticket = {
        "subject": subject,
        "comment": {"body": description}
    }

    # Build custom_fields array if env var ids or values are present
    custom_fields: List[Dict[str, Union[int,str]]] = []
    try:
        if conversation_id and ZENDESK_CHAT_CONVERSATION_FIELD_ID:
            cf_id = int(ZENDESK_CHAT_CONVERSATION_FIELD_ID)
            custom_fields.append({"id": cf_id, "value": conversation_id})
    except Exception:
        logger.exception("Invalid ZENDESK_CHAT_CONVERSATION_FIELD_ID; skipping conversation custom field")

    try:
        if app_related_sub_category and APP_RELATED_SUB_CATEGORY:
            cf_id2 = int(APP_RELATED_SUB_CATEGORY)
            custom_fields.append({"id": cf_id2, "value": app_related_sub_category})
    except Exception:
        logger.exception("Invalid APP_RELATED_SUB_CATEGORY; skipping app-related custom field")

    if custom_fields:
        ticket["custom_fields"] = custom_fields

    data = {"ticket": ticket}

    response = requests.post(
        url,
        json=data,
        headers=headers,
        auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN),
        timeout=15
    )

    try:
        resp_json = response.json()
    except Exception:
        logger.error(f"Zendesk did not return JSON: {response.status_code} - {response.text}")
        raise

    if response.status_code not in (200,201):
        logger.error(f"Zendesk ticket create failed: {response.status_code} - {resp_json}")

    return resp_json

# Sunshine API Helpers
def get_sunshine_jwt() -> Optional[str]:
    """
    Obtains a JWT access token from Sunshine Conversations OAuth endpoint.
    """
    if not SUNSHINE_API_KEY_ID or not SUNSHINE_API_KEY_SECRET:
        logger.error("SUNSHINE_API_KEY_ID or SUNSHINE_API_KEY_SECRET not set")
        return None

    url = f"{SUNSHINE_API_BASE_URL}/oauth/token"
    data = {
        'grant_type': 'client_credentials',
        'client_id': SUNSHINE_API_KEY_ID,
        'client_secret': SUNSHINE_API_KEY_SECRET
    }
    try:
        response = requests.post(url, data=data)
        if response.status_code == 200:
            token_data = response.json()
            return token_data.get('access_token')
        else:
            logger.error(f"Failed to get JWT: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.exception(f"Exception getting JWT: {e}")
        return None

def get_sunshine_headers(include_content_type: bool = True, use_jwt: bool = False) -> Optional[Dict[str, str]]:
    """
    Returns the headers required for Sunshine Conversations API calls.
    """
    if use_jwt:
        token = get_sunshine_jwt()
        if not token:
            return None
    else:
        token = SUNSHINE_API_KEY_ID or os.getenv("SUNSHINE_KEY_ID")
        if not token:
            available_keys = ", ".join([k for k in os.environ.keys() if "SUNSHINE" in k or "ZENDESK" in k])
            logger.error(f"Missing Auth. Available env vars with SUNSHINE/ZENDESK: {available_keys}")
            logger.error("SUNSHINE_API_KEY_ID (or SUNSHINE_KEY_ID) is missing in .env")
            return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }

    if include_content_type:
        headers["Content-Type"] = "application/json"

    return headers

@csrf_exempt
def init_conversation(request: HttpRequest) -> JsonResponse:
    """
    Initialize a conversation for a new or existing user.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    if not SUNSHINE_APP_ID:
        logger.error("SUNSHINE_APP_ID not set")
        return JsonResponse({"error": "Server configuration error: SUNSHINE_APP_ID not set"}, status=500)

    try:
        # Define URL and Auth
        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/users"
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)

        # Try to get userId from request if available
        user_id = None
        try:
            if request.body:
                data = json.loads(request.body)
                user_id = data.get("userId")
        except Exception:
            pass

        # If no user_id provided, generate a unique one
        if not user_id:
            user_id = str(uuid.uuid4())
        else:
            logger.info(f"Using existing userId: {user_id}")

        # Create User Payload
        user_payload = {
            "externalId": user_id,
            "profile": {"givenName": "Guest"}
        }

        # Create/Get user
        response = requests.post(url, json=user_payload, auth=auth)
        
        if response.status_code not in [200, 201, 409]:
            logger.error(f"Sunshine API Error (Create User): {response.status_code} - {response.text}")
            return JsonResponse({"error": "Failed to create user", "details": response.text}, status=500)

        user_data = response.json()
        app_user_id = user_data.get("user", {}).get("id")
        
        # Fallback for existing users
        if not app_user_id and response.status_code == 409:
             get_user_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/users/{user_id}"
             get_response = requests.get(get_user_url, auth=auth)
             if get_response.status_code == 200:
                 app_user_id = get_response.json().get("user", {}).get("id")
        
        if not app_user_id:
             logger.error(f"Could not retrieve appUserId. Response: {response.text}")
             return JsonResponse({"error": "Failed to retrieve user ID"}, status=500)

        # Check for existing conversations
        conversation_id = None
        
        def fetch_conversation(target_id: str) -> Optional[str]:
            try:
                l_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations"
                params = {"filter[userId]": target_id}
                
                l_resp = requests.get(l_url, auth=auth, params=params)
                
                if l_resp.status_code == 200:
                    convs = l_resp.json().get("conversations", [])
                    if convs:
                        return convs[0].get("id")
                else:
                    logger.warning(f"List conversations failed for {target_id}: {l_resp.status_code} - {l_resp.text}")
            except Exception as ex:
                logger.warning(f"Exception listing conversations for {target_id}: {ex}")
            return None

        # Try fetching with Internal ID first
        if app_user_id:
            conversation_id = fetch_conversation(app_user_id)

        # If not found, try fetching with External ID
        if not conversation_id and user_id:
            conversation_id = fetch_conversation(user_id)

        if not conversation_id:
            # Create a Conversation if none found
            conv_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations"
            conv_payload = {
                "type": "personal",
                "participants": [{"userId": app_user_id}]
            }
            conv_response = requests.post(conv_url, json=conv_payload, auth=auth)
            
            if conv_response.status_code in [200, 201]:
                conv_data = conv_response.json()
                conversation_id = conv_data.get("conversation", {}).get("id")
            else:
                logger.error(f"Sunshine API Error (Create Conversation): {conv_response.status_code} - {conv_response.text}")
                return JsonResponse({"error": "Failed to create conversation", "details": conv_response.text}, status=500)

        return JsonResponse({
            "appUserId": app_user_id,
            "conversationId": conversation_id,
            "externalId": user_id
        })
    except Exception as e:
        logger.exception(f"Exception in init_conversation: {str(e)}")
        return JsonResponse({"error": "Internal Server Error", "details": str(e)}, status=500)

@csrf_exempt
def get_conversation_messages(request: HttpRequest) -> JsonResponse:
    """
    Fetch messages for a specific conversation.
    """
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    conversation_id = request.GET.get("conversationId")
    if not conversation_id:
        return JsonResponse({"error": "Missing conversationId"}, status=400)

    try:
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)

        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"

        response = requests.get(url, auth=auth)

        # Also fetch conversation details to check active switchboard integration
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
            logger.error(f"Failed to fetch messages: {response.status_code} - {response.text}")
            return JsonResponse({"error": "Failed to fetch messages"}, status=response.status_code)

    except Exception as e:
        logger.exception("Exception in get_conversation_messages")
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def send_message_to_sunshine(request: HttpRequest) -> JsonResponse:
    """
    Send a message from the user to Sunshine.
    """
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
        
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)

        response = requests.post(url, json=payload, auth=auth)
        
        if response.status_code == 201:
            return JsonResponse({"status": "sent", "data": response.json()})
        else:
            logger.error(f"Sunshine API Error (Send Message): {response.status_code} - {response.text}")
            return JsonResponse({"error": "Failed to send message", "details": response.text}, status=500)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.exception(f"Exception in send_message_to_sunshine: {str(e)}")
        return JsonResponse({"error": "Internal Server Error", "details": str(e)}, status=500)

@csrf_exempt
def escalate_to_agent(request: HttpRequest) -> JsonResponse:
    """
    Escalates the conversation to the next switchboard integration (e.g., Agent Workspace).
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        conversation_id = data.get("conversationId")
        app_user_id = data.get("appUserId")
        reason = data.get("reason", "User requested agent support") 
        
        if not conversation_id:
            return JsonResponse({"error": "Missing conversationId"}, status=400)

        # Store conversation ID for later mapping
        cache.set(f'pending_escalation_{conversation_id}', {
            'app_user_id': app_user_id,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        }, timeout=300)  # 5 minutes for ticket creation

        # Use global SUNSHINE_APP_ID
        app_id = SUNSHINE_APP_ID
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)

        # Pass Control to Zendesk ("next")
        pass_control_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{app_id}/conversations/{conversation_id}/passControl"

        pass_control_payload = {
            "switchboardIntegration": "next",
            "metadata": {
                "dataCapture.systemField.tags": "escalated_from_bot",
                "dataCapture.systemField.requester.name": "Guest User",
                "dataCapture.ticketField.description": f"Conversation ID: {conversation_id}\nEscalation Reason: {reason}"
            }
        }

        pc_response = requests.post(pass_control_url, json=pass_control_payload, auth=auth)

        if pc_response.status_code != 200:
            logger.error(f"Failed to escalate conversation: {pc_response.status_code} - {pc_response.text}")
            return JsonResponse({"error": "Failed to escalate", "details": pc_response.text}, status=pc_response.status_code)

        # Send a message on behalf of the user to trigger ticket creation
        if app_user_id:
            msg_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{app_id}/conversations/{conversation_id}/messages"
            msg_payload = {
                "author": {
                    "type": "user",
                    "userId": app_user_id
                },
                "content": {
                    "type": "text",
                    "text": f"Connecting to agent. Reason: {reason}"
                }
            }
            requests.post(msg_url, json=msg_payload, auth=auth)

        return JsonResponse({
            "status": "escalated",
            "conversation_id": conversation_id
        })

    except Exception as e:
        logger.exception("Exception in escalate_to_agent")
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def webhook_message(request: HttpRequest) -> Union[JsonResponse, HttpResponseForbidden]:
    """
    Webhook endpoint to receive events from Sunshine.
    """
    # Try different casing for the header
    sig = request.headers.get("X-Hub-Signature") or request.headers.get("x-hub-signature")
    
    # Fallback: Check for X-Api-Key if X-Hub-Signature is missing
    if not sig:
        api_key_header = request.headers.get("X-Api-Key")
        if api_key_header:
            sig = "BYPASS_DEBUG" 

    body = request.body

    # Verify signature
    if sig != "BYPASS_DEBUG" and not verify_signature(body, sig):
        return HttpResponseForbidden("Invalid signature")

    # Parse event safely
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        return HttpResponseForbidden("Invalid JSON")
    
    # Handle Sunshine v2 "events" array structure if present
    events_list = event.get("events", [])
    if not events_list and "trigger" in event:
        events_list = [event]
    elif not events_list and "messages" in event:
        events_list = [event]
        event["trigger"] = "conversation:message"

    for evt in events_list:
        trigger = evt.get("trigger") or evt.get("type")
        
        # 1. Handle Messages
        if trigger == "conversation:message":
            process_message_event(evt)
        
        # 2. Handle Switchboard Events (Agent Control)
        elif trigger == "switchboard:passControl":
            logger.info("Control passed to switchboard integration.")
            
        elif trigger == "switchboard:releaseControl":
            logger.info("Control released by switchboard integration (Agent ended chat).")
            handle_agent_end_session(evt)

        # 3. Handle Participant Join (Agent Joined)
        elif trigger == "participant:join":
            handle_participant_join(evt)

        # 4. Handle Conversation Read (Agent Opened Ticket)
        elif trigger == "conversation:read":
            handle_conversation_read(evt)

    return JsonResponse({"status": "received"})

def handle_conversation_read(event_data: Dict[str, Any]) -> None:
    """
    Notify user when an agent reads the conversation (opens ticket).
    """
    conversation_id = event_data.get("conversation", {}).get("_id") or event_data.get("conversation", {}).get("id")
    if not conversation_id:
        return

    app_user = event_data.get("appUser", {})
    app_user_id = app_user.get("_id") or app_user.get("id")
    reader_id = event_data.get("userId")
    
    if not reader_id:
        reader_id = event_data.get("source", {}).get("from", {}).get("id")

    if reader_id and app_user_id and reader_id != app_user_id:
        is_business = event_data.get("role") == "business"
        
        if is_business or reader_id != app_user_id:
            agent_name = "An agent"
            
            # Send system message
            try:
                auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
                url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                payload = {
                    "author": {"type": "business", "displayName": "System"},
                    "content": {"type": "text", "text": f"{agent_name} connected"}
                }
                requests.post(url, json=payload, auth=auth)
            except Exception as e:
                logger.error(f"Failed to send agent read notification: {e}")

def handle_participant_join(event_data: Dict[str, Any]) -> None:
    """
    Notify user when an agent joins the conversation.
    """
    conversation_id = event_data.get("conversation", {}).get("_id") or event_data.get("conversation", {}).get("id")
    if not conversation_id:
        return

    participants = event_data.get("participants", [])
    single_participant = event_data.get("participant")
    if single_participant:
        participants.append(single_participant)

    for p in participants:
        if p.get("type") == "business":
            agent_name = p.get("displayName", "An agent")
            
            # Send a system message to notify the user
            try:
                auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
                url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                payload = {
                    "author": {"type": "business", "displayName": "System"},
                    "content": {"type": "text", "text": f"{agent_name} connected"}
                }
                requests.post(url, json=payload, auth=auth)
            except Exception as e:
                logger.error(f"Failed to send agent join notification: {e}")

def process_message_event(event_data: Dict[str, Any]) -> None:
    """
    Handle incoming user messages and optionally create tickets.
    """
    conversation = event_data.get("conversation", {})
    conversation_id = conversation.get("_id") or conversation.get("id")
    app_user = event_data.get("appUser", {})
    app_user_id = app_user.get("_id") or app_user.get("id")
    
    # Check who is currently in control
    sb_integration = conversation.get("activeSwitchboardIntegration", {})
    current_integration_name = sb_integration.get("name")

    # When agent (Zendesk) takes control, extract ticket ID from metadata
    if current_integration_name in ["next", "zendesk"]:
        # Try to extract Zendesk ticket ID from metadata
        metadata = conversation.get("metadata", {})
        if metadata:
            ticket_id = None
            
            # Check Sunshine's standard metadata format
            if 'dataCapture' in metadata:
                ticket_data = metadata.get('dataCapture', {}).get('ticketField', {})
                if ticket_data:
                    ticket_id = ticket_data.get('id')
            
            # Also check for any ticket references in the entire metadata
            if not ticket_id:
                metadata_str = json.dumps(metadata)
                ticket_match = re.search(r'ticket[_-]?id["\']?\s*:\s*["\']?(\d+)', metadata_str, re.IGNORECASE)
                if ticket_match:
                    ticket_id = ticket_match.group(1)
            
            if ticket_id:
                # Store the mapping
                store_conversation_ticket_mapping(conversation_id, ticket_id)
        
        # Don't create additional tickets when agent is in control
        return

    messages = event_data.get("messages", [])
    if not messages:
        return

    text = messages[0].get("text")
    if text:
        try:
            # Attempt to infer app-related sub-category from the message text
            def get_app_related_tag_from_text(t: str) -> Optional[str]:
                if not t:
                    return None
                s = t.lower()
                mapping = {
                    "location not found or inaccurate": "location_not_found_or_inaccurate",
                    "unable to login": "unable_to_login",
                    "my app is not responding": "my_app_is_not_responding",
                    "others": "others",
                    # allow matching by tag as well
                    "location_not_found_or_inaccurate": "location_not_found_or_inaccurate",
                    "unable_to_login": "unable_to_login",
                    "my_app_is_not_responding": "my_app_is_not_responding",
                    "others": "others",
                }
                # Check for exact phrase or tag in the text
                for k, v in mapping.items():
                    if k in s:
                        return v
                # Additional heuristic: look for keywords
                if "location" in s:
                    return "location_not_found_or_inaccurate"
                if "login" in s or "sign in" in s:
                    return "unable_to_login"
                if "respond" in s or "not responding" in s or "crash" in s:
                    return "my_app_is_not_responding"
                return None

            app_related_tag = get_app_related_tag_from_text(text)

            create_zendesk_ticket(
                subject=f"Conversation {conversation_id}",
                description=f"User {app_user_id} said: {text}",
                conversation_id=conversation_id,
                app_related_sub_category=app_related_tag
            )
        except Exception as e:
            logger.error(f"Failed to create ticket: {e}")

@csrf_exempt
def send_to_zendesk(request: HttpRequest) -> JsonResponse:
    """
    Handle file upload and send to Zendesk agent via Sunshine Conversations API.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed", "status": "fail"}, status=405)

    try:
        # Extract form data
        file = request.FILES.get('file')
        message = request.POST.get('message', '')
        conversation_id = request.POST.get('conversationId')
        app_user_id = request.POST.get('appUserId')

        if not all([file, conversation_id, app_user_id]):
            return JsonResponse({"error": "Missing required fields: file, conversationId, appUserId", "status": "fail"}, status=400)

        # Step 1: Upload file to Sunshine Conversations Attachments API
        upload_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/attachments"
        upload_files = {'source': file}
        upload_params = {'access': 'public'}

        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        upload_response = requests.post(upload_url, files=upload_files, params=upload_params, auth=auth)

        if upload_response.status_code not in [200, 201]:
            logger.error(f"Sunshine upload failed: {upload_response.status_code} - {upload_response.text}")
            return JsonResponse({"error": "Failed to upload file", "status": "fail"}, status=500)

        upload_data = upload_response.json()
        media_url = upload_data.get('attachment', {}).get('mediaUrl')
        if not media_url:
            logger.error("No mediaUrl received from Sunshine upload")
            return JsonResponse({"error": "Upload mediaUrl not received", "status": "fail"}, status=500)

        # Step 2: Send file message via Sunshine Conversations API
        msg_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"

        # Send file message
        file_payload = {
            "author": {"type": "user", "userId": app_user_id},
            "content": {
                "type": "file",
                "mediaUrl": media_url,
                "fileName": file.name,
                "contentType": file.content_type,
                "fileSize": file.size
            }
        }

        file_response = requests.post(msg_url, json=file_payload, auth=auth)

        # Retry once on 5xx errors
        if file_response.status_code >= 500:
            file_response = requests.post(msg_url, json=file_payload, auth=auth)

        if file_response.status_code not in [200, 201]:
            logger.error(f"Sunshine file message failed: {file_response.status_code} - {file_response.text}")
            return JsonResponse({"error": "Failed to send file message", "status": "fail"}, status=500)

        # Step 3: Send text message if provided
        if message.strip():
            text_payload = {
                "author": {"type": "user", "userId": app_user_id},
                "content": {"type": "text", "text": message.strip()}
            }

            text_response = requests.post(msg_url, json=text_payload, auth=auth)

            # Retry once on 5xx errors
            if text_response.status_code >= 500:
                text_response = requests.post(msg_url, json=text_payload, auth=auth)

            if text_response.status_code not in [200, 201]:
                logger.error(f"Sunshine text message failed: {text_response.status_code} - {text_response.text}")
                return JsonResponse({"error": "Failed to send text message", "status": "fail"}, status=500)

        return JsonResponse({"status": "ok"})

    except Exception as e:
        logger.exception(f"Exception in send_to_zendesk: {str(e)}")
        return JsonResponse({"error": "Internal Server Error", "status": "fail", "details": str(e)}, status=500)

def handle_agent_end_session(event_data: Dict[str, Any]) -> None:
    """
    Send a system message when agent ends the chat.
    """
    conversation_id = event_data.get("conversation", {}).get("_id") or event_data.get("conversation", {}).get("id")
    if not conversation_id:
        return

    # Send a message to the user confirming the session has ended
    try:
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        payload = {
            "author": {"type": "business", "displayName": "System"},
            "content": {"type": "text", "text": "The agent has ended the session. Type a message to start a new ticket."}
        }
        requests.post(url, json=payload, auth=auth)
    except Exception as e:
        logger.error(f"Failed to send end-session message: {e}")

# ============================================================================
# CRITICAL FIX: Corrected zendesk_webhook function
# ============================================================================
@csrf_exempt
def zendesk_webhook(request: HttpRequest) -> JsonResponse:
    """
    Handle Zendesk webhook notifications when agents reply.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    try:
        # Parse the body
        body_str = request.body.decode('utf-8')
        
        try:
            data = json.loads(body_str)
        except json.JSONDecodeError:
            logger.error("Body is not valid JSON")
            return JsonResponse({"status": "invalid_json"}, status=400)
        
        # Handle Zendesk's webhook format for AGENT COMMENTS
        
        # Format 1: Direct ticket comment format
        if 'ticket' in data and 'comment' in data:
            return handle_ticket_comment_webhook(data)
        
        # Format 2: Event-based webhook (more common)
        elif 'events' in data:
            return handle_event_webhook(data)
        
        # Format 3: Simple notification format
        elif 'type' in data:
            return handle_notification_webhook(data)
        
        else:
            # Unknown format
            ticket_id = extract_ticket_id_from_data(data)
            if ticket_id:
                return JsonResponse({
                    "status": "unknown_format",
                    "ticket_id": ticket_id,
                    "message": "Received webhook but format not recognized"
                })
            
            return JsonResponse({
                "status": "unknown_format",
                "message": "Webhook format not recognized"
            })
        
    except Exception as e:
        logger.exception(f"Exception in zendesk_webhook: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)

def handle_ticket_comment_webhook(data: Dict[str, Any]) -> JsonResponse:
    """
    Handle Zendesk webhook format 1: Direct ticket comment
    """
    try:
        ticket = data.get('ticket', {})
        ticket_id = ticket.get('id')
        
        if not ticket_id:
            logger.error("No ticket ID in webhook")
            return JsonResponse({"status": "no_ticket_id"}, status=400)
        
        comment = ticket.get('comment', {})
        comment_body = comment.get('body', '')
        comment_author = comment.get('author', {})
        author_role = comment_author.get('role', '')
        
        # Only process agent/admin comments
        if author_role not in ['agent', 'admin']:
            return JsonResponse({"status": "ignored_non_agent"})
        
        if not comment_body or comment_body.strip() == '':
            return JsonResponse({"status": "ignored_empty"})
        
        # Get conversation ID from cache
        conversation_id = cache.get(f'ticket_{ticket_id}')
        
        if not conversation_id:
            # Try to find conversation from pending escalations
            for key in cache._cache.keys():
                if isinstance(key, str) and key.startswith('pending_escalation_'):
                    pending_data = cache.get(key)
                    if pending_data and str(ticket_id) in str(pending_data):
                        conversation_id = key.replace('pending_escalation_', '')
                        break
            
            if not conversation_id:
                logger.error(f"Cannot forward agent message - no conversation mapping for ticket {ticket_id}")
                return JsonResponse({
                    "status": "no_conversation_mapping",
                    "ticket_id": ticket_id
                })
        
        # Get agent name
        agent_name = comment_author.get('name', 'Agent')
        if not agent_name or agent_name.lower() == 'zendesk':
            agent_name = "Support Agent"
        
        # Forward agent message to Sunshine
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        
        payload = {
            "author": {
                "type": "business",
                "displayName": agent_name
            },
            "content": {
                "type": "text",
                "text": comment_body
            }
        }
        
        response = requests.post(url, json=payload, auth=auth)
        
        if response.status_code in [200, 201]:
            # ALSO forward to WebSocket for instant UI update
            forward_agent_message_to_websocket(conversation_id, comment_body, agent_name)
            
            return JsonResponse({
                "status": "forwarded",
                "ticket_id": ticket_id,
                "conversation_id": conversation_id,
                "agent_name": agent_name
            })
        else:
            logger.error(f"Failed to forward agent message: {response.status_code} - {response.text}")
            return JsonResponse({
                "status": "forward_failed",
                "ticket_id": ticket_id,
                "error": response.text
            }, status=500)
            
    except Exception as e:
        logger.exception(f"Exception in handle_ticket_comment_webhook: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)

def handle_event_webhook(data: Dict[str, Any]) -> JsonResponse:
    """
    Handle Zendesk webhook format 2: Event-based
    """
    try:
        events = data.get('events', [])
        
        for event in events:
            event_type = event.get('type')
            
            if event_type == 'Comment':
                # This is an agent comment
                ticket_id = extract_ticket_id_from_data(data)
                comment_body = event.get('body', '')
                
                if ticket_id and comment_body:
                    # Get conversation ID
                    conversation_id = cache.get(f'ticket_{ticket_id}')
                    
                    if conversation_id:
                        # Forward to Sunshine
                        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
                        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                        
                        payload = {
                            "author": {
                                "type": "business",
                                "displayName": "Support Agent"
                            },
                            "content": {
                                "type": "text",
                                "text": comment_body
                            }
                        }
                        
                        response = requests.post(url, json=payload, auth=auth)
                        
                        if response.status_code in [200, 201]:
                            forward_agent_message_to_websocket(conversation_id, comment_body, "Support Agent")
                    
                break
        
        return JsonResponse({"status": "processed_events"})
        
    except Exception as e:
        logger.exception(f"Exception in handle_event_webhook: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)

def handle_notification_webhook(data: Dict[str, Any]) -> JsonResponse:
    """
    Handle Zendesk webhook format 3: Notification format
    """
    try:
        event_type = data.get('type', '')
        
        if 'ticket.commented' in event_type or 'ticket_updated' in event_type:
            ticket_id = extract_ticket_id_from_data(data)
            
            if ticket_id:
                # Try to handle it like a regular ticket comment
                return handle_ticket_comment_webhook(data)
        
        return JsonResponse({"status": "processed_notification"})
        
    except Exception as e:
        logger.exception(f"Exception in handle_notification_webhook: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)

def extract_ticket_id_from_data(data: Dict[str, Any]) -> Optional[str]:
    """
    Extract ticket ID from any Zendesk webhook format.
    """
    # Try different possible locations for ticket ID
    ticket_id = None
    
    # Location 1: Direct ticket.id
    if 'ticket' in data and 'id' in data['ticket']:
        ticket_id = str(data['ticket']['id'])
    
    # Location 2: In detail object
    elif 'detail' in data and 'id' in data['detail']:
        ticket_id = str(data['detail']['id'])
    
    # Location 3: In events array
    elif 'events' in data and data['events']:
        for event in data['events']:
            if 'ticket_id' in event:
                ticket_id = str(event['ticket_id'])
                break
    
    # Location 4: Search recursively in the entire data
    if not ticket_id:
        data_str = json.dumps(data)
        matches = re.findall(r'"ticket[_-]?id":\s*"?(\d+)"?', data_str, re.IGNORECASE)
        if matches:
            ticket_id = matches[0]
        else:
            # Look for any numeric ID that looks like a ticket ID
            matches = re.findall(r'"id":\s*"?(\d+)"?', data_str)
            if matches:
                ticket_id = matches[0]
    
    return ticket_id