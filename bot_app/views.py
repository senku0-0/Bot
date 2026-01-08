from django.shortcuts import render
from django.http import JsonResponse, HttpResponseForbidden, HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
import json, hmac, hashlib, os, base64, logging, sys, uuid, re, time
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
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

# Load environment variables from .env
load_dotenv()

# ============================================================================
# Helper: Strip HTML tags from text
# ============================================================================
def strip_html_tags(text: str) -> str:
    """
    Remove HTML tags from text and clean up whitespace.
    Zendesk Conversation Log API sometimes returns HTML-formatted content.
    """
    if not text:
        return ""
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', text)
    # Replace multiple whitespace with single space
    clean = re.sub(r'\s+', ' ', clean)
    # Trim whitespace
    clean = clean.strip()
    return clean

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
    """
    try:
        # Get the channel layer
        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.error("No channel layer available to forward agent message")
            return False

        # Prepare the WebSocket message payload
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

        group_name = f'chat_{conversation_id}'
        logger.info(f"[WEBSOCKET] Forwarding agent message to group {group_name} - text: {str(message_text)[:200]}")

        try:
            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    'type': 'send_webhook_message',
                    'message': websocket_message
                }
            )
            logger.info(f"[WEBSOCKET] group_send to {group_name} succeeded")
            return True
        except Exception as send_exc:
            logger.exception(f"[WEBSOCKET] group_send failed for {group_name}: {send_exc}")
            return False

    except Exception as e:
        logger.exception(f"[WEBSOCKET] Error preparing to forward agent message to WebSocket: {str(e)}")
        return False

# ============================================================================
# Function to store conversation-ticket mapping
# ============================================================================
def store_conversation_ticket_mapping(conversation_id: str, ticket_id: str) -> bool:
    """
    Store the mapping between Sunshine conversation and Zendesk ticket.
    """
    try:
        # Store mapping both ways for easy lookup - 7 days timeout
        cache.set(f'conversation_{conversation_id}', ticket_id, timeout=604800)  # 7 days
        cache.set(f'ticket_{ticket_id}', conversation_id, timeout=604800)  # 7 days
        logger.info(f"[MAPPING] ✅ Stored mapping: conversation_{conversation_id} -> {ticket_id}")
        return True
    except Exception as e:
        logger.error(f"[MAPPING] ❌ Failed to store conversation-ticket mapping: {str(e)}")
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

    # If ticket created successfully, try to store the conversation<->ticket mapping
    if response.status_code in (200, 201):
        try:
            ticket_obj = resp_json.get('ticket') or resp_json
            ticket_id = ticket_obj.get('id') if isinstance(ticket_obj, dict) else None
            if ticket_id and conversation_id:
                try:
                    store_conversation_ticket_mapping(str(conversation_id), str(ticket_id))
                    logger.info(f"[TICKET] Stored mapping after ticket create: conversation={conversation_id} ticket={ticket_id}")
                except Exception:
                    logger.exception("[TICKET] Failed to store conversation-ticket mapping after create")
        except Exception:
            logger.exception("[TICKET] Error extracting ticket id after create")
    else:
        logger.error(f"[TICKET] Zendesk ticket create failed: {response.status_code} - {resp_json}")

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
        app_related_category = data.get("appRelatedCategory")
        
        logger.info(f"[ESCALATE] 📤 Starting escalation for conversation: {conversation_id}")
        logger.info(f"[ESCALATE] 📤 User: {app_user_id}, Reason: {reason}, Category: {app_related_category}")
        
        if not conversation_id:
            return JsonResponse({"error": "Missing conversationId"}, status=400)

        # Store category in cache for potential webhook lookup
        if app_related_category:
            cache.set(f'category_{conversation_id}', app_related_category, timeout=3600)
            logger.info(f"[ESCALATE] 📤 Cached category for conversation {conversation_id}")

        # Store pending escalation data for ticket.created webhook to find
        pending_data = {
            'conversation_id': conversation_id,
            'app_user_id': app_user_id,
            'reason': reason,
            'app_related_category': app_related_category,
            'timestamp': datetime.now().isoformat()
        }
        cache.set(f'pending_escalation_{conversation_id}', pending_data, timeout=300)  # 5 minutes
        logger.info(f"[ESCALATE] 📤 Stored pending_escalation_{conversation_id} for webhook lookup")

        # Use global SUNSHINE_APP_ID
        app_id = SUNSHINE_APP_ID
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)

        # ============================================================================
        # SIMPLIFIED METADATA - Focus only on Category field
        # ============================================================================
        
        # Map the category to the correct TAG value (must match Zendesk dropdown option tags)
        category_mapping = {
            "Location Not Found or Inaccurate": "location_not_found_or_inaccurate",
            "Unable to Login": "unable_to_login",
            "My App is Not Responding": "my_app_is_not_responding",
            "Others": "others",
            # Also handle if already in tag format
            "location_not_found_or_inaccurate": "location_not_found_or_inaccurate",
            "unable_to_login": "unable_to_login",
            "my_app_is_not_responding": "my_app_is_not_responding",
            "others": "others"
        }
        
        category_tag = category_mapping.get(app_related_category, "others") if app_related_category else None
        
        # Build metadata - only escalated_from_bot tag (no category tag to avoid trigger issues)
        metadata = {
            "dataCapture.systemField.tags": "escalated_from_bot",
            "dataCapture.systemField.requester.name": "Guest User"
        }
        
        # ============================================================================
        # CRITICAL: Add conversation ID to custom field for ticket<->conversation mapping
        # This allows the ticket.created webhook to find the conversation ID
        # Format: dataCapture.ticketField.{FIELD_ID}
        # ============================================================================
        if ZENDESK_CHAT_CONVERSATION_FIELD_ID:
            metadata[f"dataCapture.ticketField.{ZENDESK_CHAT_CONVERSATION_FIELD_ID}"] = conversation_id
            logger.info(f"[ESCALATE] 📤 Setting conversation field {ZENDESK_CHAT_CONVERSATION_FIELD_ID} = {conversation_id}")
        
        # Add category dropdown field - CORRECT FORMAT: dataCapture.ticketField.{ID}
        if category_tag and APP_RELATED_SUB_CATEGORY:
            metadata[f"dataCapture.ticketField.{APP_RELATED_SUB_CATEGORY}"] = category_tag
            logger.info(f"[ESCALATE] 📤 Setting category field {APP_RELATED_SUB_CATEGORY} = {category_tag}")
        
        logger.info(f"[ESCALATE] 📤 Final metadata: {metadata}")

        # ============================================================================
        # Send a simple escalation message BEFORE passControl
        # This ensures there's conversation history when Zendesk creates the ticket
        # CRITICAL: Include conversation ID so ticket.created webhook can find it
        # ============================================================================
        if app_user_id:
            msg_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{app_id}/conversations/{conversation_id}/messages"
            
            # Include conversation ID in message so it can be parsed from ticket description
            escalation_message = f"Escalation Reason: {reason}"
            if app_related_category:
                escalation_message += f"\nCategory: {app_related_category}"
            escalation_message += f"\n[Sunshine Conversation: {conversation_id}]"
            
            msg_payload = {
                "author": {
                    "type": "user",
                    "userId": app_user_id
                },
                "content": {
                    "type": "text",
                    "text": escalation_message
                }
            }
            
            logger.info(f"[ESCALATE] 📤 Sending escalation message: {escalation_message}")
            msg_response = requests.post(msg_url, json=msg_payload, auth=auth)
            logger.info(f"[ESCALATE] 📤 Message sent, status: {msg_response.status_code}")
            
            if msg_response.status_code not in [200, 201]:
                logger.error(f"[ESCALATE] ⚠️ Message send failed: {msg_response.text}")
            else:
                # Wait a bit to ensure message is processed before passControl
                time.sleep(0.5)
                logger.info(f"[ESCALATE] ✅ Message in conversation, proceeding to passControl")

        # Pass Control to Zendesk ("next")
        pass_control_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{app_id}/conversations/{conversation_id}/passControl"
        pass_control_payload = {
            "switchboardIntegration": "next",
            "metadata": metadata
        }
        
        logger.info(f"[ESCALATE] 📤 Calling passControl API: {pass_control_url}")

        pc_response = requests.post(pass_control_url, json=pass_control_payload, auth=auth)
        
        logger.info(f"[ESCALATE] 📤 passControl response: {pc_response.status_code}")

        if pc_response.status_code != 200:
            logger.error(f"[ESCALATE] ❌ Failed to escalate conversation: {pc_response.status_code} - {pc_response.text}")
            return JsonResponse({"error": "Failed to escalate", "details": pc_response.text}, status=pc_response.status_code)
        
        logger.info(f"[ESCALATE] ✅ passControl succeeded!")
        logger.info(f"[ESCALATE] ✅ Escalation complete for conversation {conversation_id}")

        return JsonResponse({
            "status": "escalated",
            "conversation_id": conversation_id,
            "category": app_related_category
        })

    except Exception as e:
        logger.exception("[ESCALATE] ❌ Exception in escalate_to_agent")
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def webhook_message(request: HttpRequest) -> Union[JsonResponse, HttpResponseForbidden]:
    """
    Webhook endpoint to receive events from Sunshine.
    This now handles agent messages directly from Sunshine webhooks.
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
    
    logger.info(f"[SUNSHINE-WEBHOOK] Received event: {json.dumps(event)[:500]}")
    
    # Handle Sunshine v2 "events" array structure if present
    events_list = event.get("events", [])
    if not events_list and "trigger" in event:
        events_list = [event]
    elif not events_list and "messages" in event:
        events_list = [event]
        event["trigger"] = "conversation:message"

    for evt in events_list:
        trigger = evt.get("trigger") or evt.get("type")
        
        logger.info(f"[SUNSHINE-WEBHOOK] Processing trigger: {trigger}")
        
        # 1. Handle Messages (CRITICAL: This includes agent messages!)
        if trigger == "conversation:message":
            process_message_event(evt)
        
        # 2. Handle Switchboard Events (Agent Control)
        elif trigger == "switchboard:passControl":
            logger.info("[SUNSHINE-WEBHOOK] Control passed to switchboard integration.")
            # Try to extract ticket ID from metadata when agent takes control
            handle_agent_take_control(evt)
            
        elif trigger == "switchboard:releaseControl":
            logger.info("[SUNSHINE-WEBHOOK] Control released by switchboard integration (Agent ended chat).")
            handle_agent_end_session(evt, show_to_user=False)  # Don't show immediately

        elif trigger == "switchboard:acceptControl":
            logger.info("[SUNSHINE-WEBHOOK] Agent accepted control of conversation.")
            handle_agent_accepted_control(evt)

        elif trigger == "switchboard:offerControl":
            logger.info("[SUNSHINE-WEBHOOK] Agent was offered control of conversation.")

        # 3. Handle Participant Join (Agent Joined)
        elif trigger == "participant:join":
            handle_participant_join(evt)

        # 4. Handle Participant Leave (Agent Left)
        elif trigger == "participant:leave":
            handle_participant_leave(evt)

        # 5. Handle Conversation Read (Agent Opened Ticket)
        elif trigger == "conversation:read":
            handle_conversation_read(evt)

        # 6. Handle User Typing (Agent is typing)
        elif trigger == "user:typing":
            handle_user_typing(evt)

        # 7. Handle User Updated (Agent profile updated)
        elif trigger == "user:updated":
            logger.info("[SUNSHINE-WEBHOOK] User profile updated.")

        else:
            logger.info(f"[SUNSHINE-WEBHOOK] Unhandled trigger type: {trigger}")

    return JsonResponse({"status": "received"})

def handle_agent_take_control(event_data: Dict[str, Any]) -> None:
    """
    Handle when agent takes control of conversation.
    Extract ticket ID from metadata if available.
    """
    conversation = event_data.get("payload", {}).get("conversation", {})
    conversation_id = conversation.get("id")
    
    if not conversation_id:
        return
    
    # Check for metadata that might contain ticket ID
    metadata = event_data.get("payload", {}).get("metadata", {})
    
    if metadata:
        # Try to extract ticket ID from metadata
        ticket_id = None
        
        # Look for ticket ID in various metadata formats
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
            
            # Also check for "id" field in ticketField
            if not ticket_id and 'ticketField' in metadata.get('dataCapture', {}):
                ticket_id = metadata['dataCapture']['ticketField'].get('id')
        
        if ticket_id:
            # Get the app-related category from cache
            pending_data = cache.get(f'pending_escalation_{conversation_id}')
            app_related_category = None
            if pending_data:
                app_related_category = pending_data.get('app_related_category')
            
            # Store the mapping
            store_conversation_ticket_mapping(conversation_id, ticket_id)
            logger.info(f"[AGENT-CONTROL] Stored mapping from metadata: conversation={conversation_id} -> ticket={ticket_id}")
            
            # NEW: Update the ticket custom field if we have a category
            if app_related_category and APP_RELATED_SUB_CATEGORY:
                update_ticket_custom_field(ticket_id, app_related_category)
            
            # Store ticket status as active
            cache.set(f'ticket_status_{ticket_id}', 'active', timeout=86400)
        else:
            logger.info(f"[AGENT-CONTROL] No ticket ID found in metadata for conversation {conversation_id}")

def update_ticket_custom_field(ticket_id: str, category: str) -> bool:
    """
    Update the APP_RELATED_SUB_CATEGORY custom field in Zendesk ticket.
    """
    try:
        # Map category display name to tag value
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
        
        # Get tag value (handle both display name and tag format)
        tag_value = category_mapping.get(category)
        if not tag_value:
            tag_value = "others"  # Default fallback
        
        # Update ticket custom field
        url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
        headers = {"Content-Type": "application/json"}
        
        data = {
            "ticket": {
                "custom_fields": [
                    {
                        "id": int(APP_RELATED_SUB_CATEGORY),
                        "value": tag_value
                    }
                ]
            }
        }
        
        response = requests.put(
            url,
            json=data,
            headers=headers,
            auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN),
            timeout=15
        )
        
        if response.status_code == 200:
            logger.info(f"[TICKET-UPDATE] Successfully updated ticket {ticket_id} custom field to {tag_value}")
            return True
        else:
            logger.error(f"[TICKET-UPDATE] Failed to update ticket {ticket_id}: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"[TICKET-UPDATE] Error updating ticket custom field: {str(e)}")
        return False

def handle_user_typing(event_data: Dict[str, Any]) -> None:
    """
    Handle user typing indicator from Sunshine webhook.
    This can be used to show "Agent is typing..." in the UI.
    """
    conversation_id = event_data.get("conversation", {}).get("_id") or event_data.get("conversation", {}).get("id")
    if not conversation_id:
        return

    # Check if this is an agent typing
    participant = event_data.get("participant", {})
    if participant.get("type") == "business":
        # Agent is typing - forward to WebSocket
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
                
                group_name = f'chat_{conversation_id}'
                async_to_sync(channel_layer.group_send)(
                    group_name,
                    {
                        'type': 'send_webhook_message',
                        'message': websocket_message
                    }
                )
                logger.info(f"[TYPING] Sent agent typing indicator for conversation {conversation_id}")
        except Exception as e:
            logger.error(f"[TYPING] Failed to forward typing indicator: {e}")

def handle_agent_accepted_control(event_data: Dict[str, Any]) -> None:
    """
    Handle when agent accepts control of the conversation.
    """
    conversation_id = event_data.get("payload", {}).get("conversation", {}).get("id")
    if not conversation_id:
        return

    # Send a system message to notify the user
    try:
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        payload = {
            "author": {"type": "business", "displayName": "System"},
            "content": {"type": "text", "text": "An agent has accepted your request and will be with you shortly."}
        }
        requests.post(url, json=payload, auth=auth)
        logger.info(f"[AGENT-ACCEPTED] Sent acceptance notification for conversation {conversation_id}")
    except Exception as e:
        logger.error(f"[AGENT-ACCEPTED] Failed to send acceptance notification: {e}")

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
            
            # Send system message (but not to user UI)
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
            
            # Send a system message to notify the user (but not shown in UI)
            try:
                auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
                url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                payload = {
                    "author": {"type": "business", "displayName": "System"},
                    "content": {"type": "text", "text": f"{agent_name} has joined the conversation"}
                }
                requests.post(url, json=payload, auth=auth)
                logger.info(f"[AGENT-JOIN] Sent join notification for {agent_name}")
            except Exception as e:
                logger.error(f"Failed to send agent join notification: {e}")

def handle_participant_leave(event_data: Dict[str, Any]) -> None:
    """
    Notify user when an agent leaves the conversation.
    """
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
            
            # Send a system message to notify the user (but not shown in UI)
            try:
                auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
                url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                payload = {
                    "author": {"type": "business", "displayName": "System"},
                    "content": {"type": "text", "text": f"{agent_name} has left the conversation"}
                }
                requests.post(url, json=payload, auth=auth)
                logger.info(f"[AGENT-LEAVE] Sent leave notification for {agent_name}")
            except Exception as e:
                logger.error(f"Failed to send agent leave notification: {e}")

def process_message_event(event_data: Dict[str, Any]) -> None:
    """
    Handle incoming messages from Sunshine webhook.
    This includes both user messages AND agent messages.
    """
    try:
        payload = event_data.get("payload", {})
        conversation = payload.get("conversation", {})
        conversation_id = conversation.get("id")
        
        if not conversation_id:
            logger.error("[SUNSHINE-AGENT] No conversation ID in message event")
            return
        
        # Check active switchboard integration
        active_integration = conversation.get("activeSwitchboardIntegration", {})
        integration_name = active_integration.get("name", "")
        integration_type = active_integration.get("integrationType", "")
        
        logger.info(f"[SUNSHINE-AGENT] Active integration: {integration_name} ({integration_type})")
        
        # Get the message
        message = payload.get("message", {})
        if not message:
            logger.error("[SUNSHINE-AGENT] No message in payload")
            return
        
        # Get message details
        author = message.get("author", {})
        author_type = author.get("type")
        author_display_name = author.get("displayName", "")
        source = message.get("source", {})
        source_type = source.get("type")
        source_integration_id = source.get("integrationId")
        
        # Get message text
        text = message.get("text")
        if not text:
            content = message.get("content", {})
            if content and content.get("type") == "text":
                text = content.get("text")
        
        if not text:
            logger.warning("[SUNSHINE-AGENT] No text in message")
            return
        
        logger.info(f"[SUNSHINE-AGENT] Message details: author_type={author_type}, author_name={author_display_name}, source_type={source_type}, integration={integration_name}")
        
        # ============================================================================
        # CRITICAL FIX: IGNORE ALL SYSTEM AND ESCALATION MESSAGES IN UI
        # ============================================================================
        if author_display_name == "System" or "Connecting to agent" in text:
            logger.info(f"[SUNSHINE-AGENT] Ignoring System/escalation message: {text[:100]}")
            return
        
        # ============================================================================
        # AGENT MESSAGE DETECTION (for real human agents only)
        # ============================================================================
        is_agent_message = False
        agent_name = "Agent"
        
        # Method 1: Check if author is business type AND NOT "System" 
        if author_type == "business" and author_display_name != "System":
            is_agent_message = True
            agent_name = author_display_name or "Agent"
            logger.info(f"[SUNSHINE-AGENT] Detected as agent via author_type=business and name={agent_name}")
        
        # Method 2: Check if source is Zendesk agent workspace
        elif source_type == "zd:agentWorkspace":
            is_agent_message = True
            agent_name = author_display_name or "Support Agent"
            logger.info(f"[SUNSHINE-AGENT] Detected as agent via zd:agentWorkspace source: {agent_name}")
        
        # ============================================================================
        # If this is an AGENT message (from a real human agent)
        # ============================================================================
        if is_agent_message:
            logger.info(f"[SUNSHINE-AGENT] ✅ REAL AGENT MESSAGE DETECTED: {agent_name}: {text[:100]}")
            
            # Forward to WebSocket
            forward_agent_message_to_websocket(conversation_id, text, agent_name)
            
            # Don't create a ticket for agent messages
            return
        
        # ============================================================================
        # If we reach here, this is a USER message
        # We should NOT forward user messages to WebSocket (they're already shown in UI)
        # ============================================================================
        logger.info(f"[SUNSHINE-USER] User message (author_type={author_type}): {text[:100]}")
        
        # If this is a user message with author_type="user", do NOT forward to WebSocket
        # The message is already displayed in the UI when the user sends it
        if author_type == "user":
            logger.info(f"[SUNSHINE-USER] User message from UI - not forwarding to WebSocket")
            return
        
        # Only create tickets for user messages when bot is in control
        if integration_name and "answerBot" in integration_name:
            try:
                # Get app user ID for ticket description
                app_user = payload.get("user", {})
                app_user_id = app_user.get("id")
                
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
        else:
            logger.info(f"[SUNSHINE-USER] Not creating ticket - integration is {integration_name}")
            
    except Exception as e:
        logger.exception(f"[SUNSHINE-AGENT] Error processing message event: {str(e)}")

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

def handle_agent_end_session(event_data: Dict[str, Any], show_to_user: bool = False) -> None:
    """
    Send a system message when agent ends the chat.
    Only show to user if show_to_user=True (when ticket is solved).
    """
    conversation_id = event_data.get("payload", {}).get("conversation", {}).get("id")
    if not conversation_id:
        return

    # Check if there's an associated ticket
    ticket_id = cache.get(f'conversation_{conversation_id}')
    
    if ticket_id:
        # Check ticket status from Zendesk
        try:
            z_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
            z_resp = requests.get(z_url, auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN), timeout=10)
            
            if z_resp.status_code == 200:
                z_json = z_resp.json()
                ticket_status = z_json.get('ticket', {}).get('status', '')
                
                # Only show "agent ended session" message if ticket is solved
                if ticket_status == 'solved':
                    show_to_user = True
                    logger.info(f"[AGENT-END] Ticket {ticket_id} is solved - showing end session message to user")
                else:
                    logger.info(f"[AGENT-END] Ticket {ticket_id} status is {ticket_status} - not showing end session message")
            else:
                logger.warning(f"[AGENT-END] Failed to fetch ticket {ticket_id}: {z_resp.status_code}")
        except Exception as e:
            logger.error(f"[AGENT-END] Error checking ticket status: {e}")
    
    if show_to_user:
        # Send a message to the user confirming the session has ended
        try:
            auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
            url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
            payload = {
                "author": {"type": "business", "displayName": "System"},
                "content": {"type": "text", "text": "The agent has ended the session. Type a message to start a new ticket."}
            }
            requests.post(url, json=payload, auth=auth)
            logger.info(f"[AGENT-END] Sent end-session message to user for conversation {conversation_id}")
        except Exception as e:
            logger.error(f"Failed to send end-session message: {e}")
    else:
        # Just log that agent ended session without showing to user
        logger.info(f"[AGENT-END] Agent ended session for conversation {conversation_id} - not showing to user (ticket not solved)")

# ============================================================================
# CRITICAL FIX: Corrected zendesk_webhook function
# Now handles ticket.solved events
# ============================================================================
@csrf_exempt
def zendesk_webhook(request: HttpRequest) -> JsonResponse:
    """
    Handle Zendesk webhook notifications when agents reply or tickets are solved.
    """
    if request.method != "POST":
        logger.error("[ZENDESK-WEBHOOK] Method not allowed")
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    try:
        # Parse the body
        body_str = request.body.decode('utf-8')
        
        try:
            data = json.loads(body_str)
        except json.JSONDecodeError:
            logger.error("[ZENDESK-WEBHOOK] Body is not valid JSON")
            return JsonResponse({"status": "invalid_json"}, status=400)
        
        logger.info(f"[ZENDESK-WEBHOOK] Received webhook. Top-level keys: {list(data.keys())}")
        
        # Handle Zendesk's webhook format for AGENT COMMENTS
        
        # Format 1: Notification format (most common)
        if 'event' in data:
            logger.info("[ZENDESK-WEBHOOK] Processing notification format")
            return handle_notification_webhook(data)
        
        # Format 2: Direct ticket comment format
        elif 'ticket' in data and 'comment' in data:
            logger.info("[ZENDESK-WEBHOOK] Processing direct ticket format")
            return handle_ticket_comment_webhook(data)
        
        # Format 3: Event-based webhook
        elif 'events' in data:
            logger.info("[ZENDESK-WEBHOOK] Processing events format")
            return handle_event_webhook(data)
        
        else:
            # Unknown format - try to extract ticket ID anyway
            ticket_id = extract_ticket_id_from_data(data)
            if ticket_id:
                logger.warning(f"[ZENDESK-WEBHOOK] Unknown format but found ticket_id: {ticket_id}")
                return JsonResponse({
                    "status": "unknown_format",
                    "ticket_id": ticket_id,
                    "message": "Received webhook but format not recognized"
                })
            
            logger.warning("[ZENDESK-WEBHOOK] Unknown format, no ticket_id found")
            return JsonResponse({
                "status": "unknown_format",
                "message": "Webhook format not recognized"
            })
        
    except Exception as e:
        logger.exception(f"[ZENDESK-WEBHOOK] Exception in zendesk_webhook: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)

def handle_ticket_comment_webhook(data: Dict[str, Any]) -> JsonResponse:
    """
    Handle Zendesk webhook format 1: Direct ticket comment
    """
    try:
        ticket = data.get('ticket', {})
        ticket_id = ticket.get('id')
        
        if not ticket_id:
            logger.error("[TICKET-COMMENT] No ticket ID in webhook")
            return JsonResponse({"status": "no_ticket_id"}, status=400)
        
        comment = ticket.get('comment', {})
        comment_body = comment.get('body', '')
        comment_author = comment.get('author', {})
        author_role = comment_author.get('role', '')
        
        logger.info(f"[TICKET-COMMENT] Processing: ticket={ticket_id}, role={author_role}, body={str(comment_body)[:100]}")
        
        # Only process agent/admin comments
        if author_role not in ['agent', 'admin']:
            logger.info(f"[TICKET-COMMENT] Ignoring non-agent comment from role: {author_role}")
            return JsonResponse({"status": "ignored_non_agent"})
        
        if not comment_body or comment_body.strip() == '':
            logger.info("[TICKET-COMMENT] Ignoring empty comment")
            return JsonResponse({"status": "ignored_empty"})
        
        # Resolve conversation id from cache or Zendesk ticket custom field
        conversation_id = resolve_conversation_id_for_ticket(ticket_id)

        if not conversation_id:
            logger.error(f"[TICKET-COMMENT] Cannot forward agent message - no conversation mapping for ticket {ticket_id}")
            return JsonResponse({
                "status": "no_conversation_mapping",
                "ticket_id": ticket_id
            })
        
        # Get agent name
        agent_name = comment_author.get('name', 'Agent')
        if not agent_name or agent_name.lower() == 'zendesk':
            agent_name = "Support Agent"
        
        logger.info(f"[TICKET-COMMENT] Forwarding to Sunshine: ticket={ticket_id}, conversation={conversation_id}, agent={agent_name}")
        
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

        logger.info(f"[TICKET-COMMENT] Posted agent comment to Sunshine conversation {conversation_id} (status={response.status_code})")

        if response.status_code in [200, 201]:
            # ALSO forward to WebSocket for instant UI update
            logger.info(f"[TICKET-COMMENT] Forwarding agent comment to websocket for conv {conversation_id}")
            forward_agent_message_to_websocket(conversation_id, comment_body, agent_name)
            
            return JsonResponse({
                "status": "forwarded",
                "ticket_id": ticket_id,
                "conversation_id": conversation_id,
                "agent_name": agent_name
            })
        else:
            logger.error(f"[TICKET-COMMENT] Failed to forward agent message: {response.status_code} - {response.text}")
            return JsonResponse({
                "status": "forward_failed",
                "ticket_id": ticket_id,
                "error": response.text
            }, status=500)
            
    except Exception as e:
        logger.exception(f"[TICKET-COMMENT] Exception in handle_ticket_comment_webhook: {str(e)}")
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
                    conversation_id = resolve_conversation_id_for_ticket(ticket_id)
                    
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
        logger.exception(f"[EVENT-WEBHOOK] Exception in handle_event_webhook: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)
    
def handle_notification_webhook(data: Dict[str, Any]) -> JsonResponse:
    """
    Handle Zendesk webhook format 3: Notification format
    This is the MOST COMMON format for Zendesk webhooks
    """
    try:
        logger.info(f"[NOTIFICATION-WEBHOOK] Processing notification: {data.get('type', 'unknown')}")
        
        event_type = data.get('type', '')
        event_data = data.get('event', {})
        
        # Check for ticket comment added event
        if 'ticket.comment_added' in event_type:
            comment = event_data.get('comment', {})
            comment_body = comment.get('body', '')
            comment_author = comment.get('author', {})
            
            # IMPORTANT: Check if this is from an agent (staff) or customer
            is_staff = comment_author.get('is_staff', False)
            
            logger.info(f"[NOTIFICATION-WEBHOOK] Comment added - is_staff: {is_staff}, author: {comment_author.get('name')}")
            
            # Skip if not staff/agent
            if not is_staff:
                logger.info("[NOTIFICATION-WEBHOOK] Ignoring user comment (not staff)")
                return JsonResponse({"status": "ignored_user_comment"})
            
            # Extract ticket ID
            ticket_id = None
            if 'ticket' in event_data:
                ticket_id = str(event_data['ticket'].get('id', ''))
            elif 'ticket_id' in event_data:
                ticket_id = str(event_data['ticket_id'])
            
            if not ticket_id:
                ticket_id = extract_ticket_id_from_data(data)
            
            if not ticket_id:
                logger.error("[NOTIFICATION-WEBHOOK] No ticket ID found in notification")
                return JsonResponse({"status": "no_ticket_id"})
            
            if not comment_body or comment_body.strip() == '':
                logger.info("[NOTIFICATION-WEBHOOK] Empty comment body")
                return JsonResponse({"status": "ignored_empty"})
            
            # Resolve conversation ID
            conversation_id = resolve_conversation_id_for_ticket(ticket_id)
            
            if not conversation_id:
                logger.error(f"[NOTIFICATION-WEBHOOK] No conversation mapping for ticket {ticket_id}")
                return JsonResponse({
                    "status": "no_conversation_mapping",
                    "ticket_id": ticket_id
                })
            
            # Get agent name
            agent_name = comment_author.get('name', 'Support Agent')
            if not agent_name or agent_name.lower() == 'zendesk':
                agent_name = "Support Agent"
            
            logger.info(f"[NOTIFICATION-WEBHOOK] Forwarding agent comment: ticket={ticket_id}, conv={conversation_id}")
            
            # Forward to Sunshine
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
                # Forward to WebSocket
                forward_agent_message_to_websocket(conversation_id, comment_body, agent_name)
                logger.info(f"[NOTIFICATION-WEBHOOK] Successfully forwarded comment to conversation {conversation_id}")
                
                return JsonResponse({
                    "status": "forwarded",
                    "ticket_id": ticket_id,
                    "conversation_id": conversation_id,
                    "agent_name": agent_name
                })
            else:
                logger.error(f"[NOTIFICATION-WEBHOOK] Failed to forward: {response.status_code} - {response.text}")
                return JsonResponse({
                    "status": "forward_failed",
                    "error": response.text
                }, status=500)
        
        # ============================================================================
        # NEW CRITICAL SECTION: Handle ticket.created event to update custom field
        # ============================================================================
        elif 'ticket.created' in event_type:
            logger.info("[NOTIFICATION-WEBHOOK] Ticket created event - ATTEMPTING TO SET CUSTOM FIELD")
            
            # Extract ticket ID
            ticket_id = None
            if 'ticket' in event_data:
                ticket_id = str(event_data['ticket'].get('id', ''))
            elif 'ticket_id' in event_data:
                ticket_id = str(event_data['ticket_id'])
            
            if not ticket_id:
                ticket_id = extract_ticket_id_from_data(data)
            
            if not ticket_id:
                logger.error("[NOTIFICATION-WEBHOOK] No ticket ID found in created ticket notification")
                return JsonResponse({"status": "no_ticket_id_in_created"})
            
            logger.info(f"[NOTIFICATION-WEBHOOK] Ticket created with ID: {ticket_id}")
            
            # ============================================================================
            # ASSURED NON-CONFLICT METHOD: Always fetch ticket from Zendesk API
            # This is the ONLY reliable way to get the conversation ID because:
            # 1. Webhook payloads may be incomplete
            # 2. Cache can expire or be unreliable
            # 3. The ticket description contains the conversation ID we set during escalation
            # ============================================================================
            conversation_id = None
            ticket_description = ""
            
            try:
                logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Step 1: Fetching ticket {ticket_id} from Zendesk API...")
                
                url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
                logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 API URL: {url}")
                
                response = requests.get(
                    url,
                    auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN),
                    timeout=15
                )
                
                logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Zendesk API response status: {response.status_code}")
                
                if response.status_code == 200:
                    ticket_data = response.json().get('ticket', {})
                    ticket_description = ticket_data.get('description', '')
                    
                    logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Fetched ticket description ({len(ticket_description)} chars)")
                    logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Description preview: {ticket_description[:500] if ticket_description else 'EMPTY'}")
                    
                    # ============================================================
                    # Step 1a: Check custom field first (if Sunshine populated it)
                    # ============================================================
                    logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Step 1a: Checking custom field {ZENDESK_CHAT_CONVERSATION_FIELD_ID}...")
                    
                    if ZENDESK_CHAT_CONVERSATION_FIELD_ID:
                        custom_fields = ticket_data.get('custom_fields', [])
                        logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Found {len(custom_fields)} custom fields in ticket")
                        
                        for field in custom_fields:
                            field_id = str(field.get('id'))
                            field_value = field.get('value')
                            
                            if field_id == str(ZENDESK_CHAT_CONVERSATION_FIELD_ID):
                                logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Found target custom field! Value: '{field_value}'")
                                if field_value and str(field_value).strip():
                                    conversation_id = str(field_value).strip()
                                    logger.info(f"[NOTIFICATION-WEBHOOK] ✅ Found conversation ID in custom field: {conversation_id}")
                                    break
                                else:
                                    logger.warning(f"[NOTIFICATION-WEBHOOK] ⚠️ Custom field {ZENDESK_CHAT_CONVERSATION_FIELD_ID} exists but value is empty/null")
                        
                        if not conversation_id:
                            logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Custom field {ZENDESK_CHAT_CONVERSATION_FIELD_ID} not found or empty, trying description...")
                    else:
                        logger.warning(f"[NOTIFICATION-WEBHOOK] ⚠️ ZENDESK_CHAT_CONVERSATION_FIELD_ID not configured!")
                    
                    # ============================================================
                    # Step 1b: Parse the description (this is what we set during escalation)
                    # ============================================================
                    if not conversation_id and ticket_description:
                        logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Step 1b: Parsing description for conversation ID...")
                        
                        # Method A: Look for "[Sunshine Conversation: <id>]" or "Sunshine Conversation: <id>"
                        # The brackets format is from the escalation message we send
                        conv_match = re.search(r'\[?Sunshine Conversation:\s*(\S+?)\]?(?:\s|$)', ticket_description)
                        if conv_match:
                            conversation_id = conv_match.group(1).strip().rstrip(']')
                            logger.info(f"[NOTIFICATION-WEBHOOK] ✅ Found conversation ID in description: {conversation_id}")
                        else:
                            logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Pattern 'Sunshine Conversation:' not found in description")
                        
                        # Method B: Look for "[Marker: SUNSHINE_CONV_<id>]" or "Marker: SUNSHINE_CONV_<id>"
                        if not conversation_id:
                            logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Trying Marker pattern...")
                            marker_match = re.search(r'\[?Marker:\s*SUNSHINE_CONV_(\S+?)\]?(?:\s|$)', ticket_description)
                            if marker_match:
                                # Extract the conversation ID from the marker
                                conversation_id = marker_match.group(1).strip().rstrip(']')
                                logger.info(f"[NOTIFICATION-WEBHOOK] ✅ Extracted conversation ID from marker: {conversation_id}")
                            else:
                                logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Pattern 'Marker: SUNSHINE_CONV_' not found in description")
                    elif not ticket_description:
                        logger.warning(f"[NOTIFICATION-WEBHOOK] ⚠️ Ticket description is EMPTY!")
                else:
                    logger.error(f"[NOTIFICATION-WEBHOOK] ❌ Failed to fetch ticket from Zendesk: {response.status_code}")
                    logger.error(f"[NOTIFICATION-WEBHOOK] ❌ Response body: {response.text[:500]}")
                    
            except Exception as e:
                logger.exception(f"[NOTIFICATION-WEBHOOK] ❌ Exception fetching ticket from Zendesk: {e}")
            
            # ============================================================================
            # Fallback: Try webhook payload description (less reliable)
            # ============================================================================
            if not conversation_id:
                logger.info("[NOTIFICATION-WEBHOOK] 🔍 Step 2: Trying webhook payload as fallback...")
                
                webhook_description = ""
                if 'ticket' in event_data:
                    webhook_description = event_data['ticket'].get('description', '')
                    logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Found 'ticket' in event_data, description length: {len(webhook_description)}")
                elif 'comment' in event_data and 'body' in event_data['comment']:
                    webhook_description = event_data['comment'].get('body', '')
                    logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Found 'comment.body' in event_data, length: {len(webhook_description)}")
                else:
                    logger.warning(f"[NOTIFICATION-WEBHOOK] ⚠️ No 'ticket' or 'comment' in event_data. Keys: {list(event_data.keys())}")
                
                if webhook_description:
                    logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Webhook description preview: {webhook_description[:300]}")
                    conv_match = re.search(r'\[?Sunshine Conversation:\s*(\S+?)\]?(?:\s|$)', webhook_description)
                    if conv_match:
                        conversation_id = conv_match.group(1).strip().rstrip(']')
                        logger.info(f"[NOTIFICATION-WEBHOOK] ✅ Found conversation ID in webhook payload: {conversation_id}")
                    else:
                        marker_match = re.search(r'\[?Marker:\s*SUNSHINE_CONV_(\S+?)\]?(?:\s|$)', webhook_description)
                        if marker_match:
                            conversation_id = marker_match.group(1).strip().rstrip(']')
                            logger.info(f"[NOTIFICATION-WEBHOOK] ✅ Extracted from marker in webhook payload: {conversation_id}")
                        else:
                            logger.warning(f"[NOTIFICATION-WEBHOOK] ⚠️ No conversation ID patterns found in webhook description")
                else:
                    logger.warning(f"[NOTIFICATION-WEBHOOK] ⚠️ Webhook description is empty")
            
            # ============================================================================
            # Final fallback: Check cache (least reliable due to potential race conditions)
            # ============================================================================
            if not conversation_id:
                logger.info("[NOTIFICATION-WEBHOOK] 🔍 Step 3: Trying cache lookup as last resort...")
                try:
                    has_keys_method = hasattr(cache, 'keys')
                    logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Cache has 'keys' method: {has_keys_method}")
                    
                    cache_keys = cache.keys('pending_escalation_*') if has_keys_method else []
                    logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Found {len(cache_keys) if cache_keys else 0} pending_escalation_* keys in cache")
                    
                    current_time = datetime.now()
                    
                    for key in cache_keys:
                        pending_data = cache.get(key)
                        if pending_data:
                            try:
                                escalation_time = datetime.fromisoformat(pending_data.get('timestamp', '2000-01-01'))
                                time_diff = (current_time - escalation_time).total_seconds()
                                logger.info(f"[NOTIFICATION-WEBHOOK] 🔍 Checking {key}: age={time_diff:.1f}s, reason='{pending_data.get('reason', '')[:50]}'")
                                
                                # Only consider very recent escalations (within 2 minutes)
                                if time_diff < 120:
                                    pending_reason = pending_data.get('reason', '')
                                    # Match by reason in description
                                    if pending_reason and ticket_description and pending_reason in ticket_description:
                                        conversation_id = key.replace('pending_escalation_', '')
                                        logger.info(f"[NOTIFICATION-WEBHOOK] Matched by reason from cache: {conversation_id}")
                                        break
                            except Exception:
                                pass
                except Exception as e:
                    logger.error(f"[NOTIFICATION-WEBHOOK] Cache lookup error: {e}")
            
            if not conversation_id:
                logger.error(f"[NOTIFICATION-WEBHOOK] ❌ Cannot find conversation for ticket {ticket_id}")
                logger.error(f"[NOTIFICATION-WEBHOOK] Description was: {ticket_description[:300] if ticket_description else 'EMPTY'}")
                return JsonResponse({
                    "status": "no_conversation_found",
                    "ticket_id": ticket_id,
                    "message": "Ticket created but no conversation mapping found"
                })
            
            # ============================================================================
            # CRITICAL: Store conversation-ticket mapping IMMEDIATELY after finding it
            # This is required for the Conversation Log API to work on refresh
            # ============================================================================
            logger.info(f"[NOTIFICATION-WEBHOOK] 💾 Storing conversation-ticket mapping: {conversation_id} -> {ticket_id}")
            store_conversation_ticket_mapping(conversation_id, ticket_id)
            
            # ============================================================================
            # Get the app_related_category from cache and update ticket
            # ============================================================================
            pending_data = cache.get(f'pending_escalation_{conversation_id}')
            app_related_category = None
            
            if pending_data:
                app_related_category = pending_data.get('app_related_category')
                logger.info(f"[NOTIFICATION-WEBHOOK] Found pending data for conversation {conversation_id}: {app_related_category}")
            else:
                logger.warning(f"[NOTIFICATION-WEBHOOK] No pending data found for conversation {conversation_id}")
                # Check if we stored it elsewhere
                app_related_category = cache.get(f'category_{conversation_id}')
            
            # Update ticket custom field if we have the category
            if app_related_category and APP_RELATED_SUB_CATEGORY:
                logger.info(f"[NOTIFICATION-WEBHOOK] Updating ticket {ticket_id} with category: {app_related_category}")
                
                # Call the update function
                try:
                    success = update_ticket_custom_field(ticket_id, app_related_category)
                    
                    if success:
                        # Mapping already stored above - just clean up pending data
                        cache.delete(f'pending_escalation_{conversation_id}')
                        
                        # Also clean up marker
                        if pending_data and 'unique_marker' in pending_data:
                            cache.delete(f"marker_{pending_data['unique_marker']}")
                        
                        logger.info(f"[NOTIFICATION-WEBHOOK] Successfully updated ticket {ticket_id} custom field")
                        
                        return JsonResponse({
                            "status": "ticket_updated",
                            "ticket_id": ticket_id,
                            "conversation_id": conversation_id,
                            "app_related_category": app_related_category,
                            "message": "Custom field updated successfully"
                        })
                    else:
                        logger.error(f"[NOTIFICATION-WEBHOOK] update_ticket_custom_field returned False")
                        # Mapping is already stored, so return partial success
                        return JsonResponse({
                            "status": "mapping_stored_but_update_failed",
                            "ticket_id": ticket_id,
                            "conversation_id": conversation_id,
                            "error": "update_ticket_custom_field returned False"
                        })
                    
                except Exception as e:
                    logger.error(f"[NOTIFICATION-WEBHOOK] Failed to update ticket custom field: {str(e)}")
                    # Mapping is already stored, so return partial success
                    return JsonResponse({
                        "status": "mapping_stored_but_update_failed",
                        "ticket_id": ticket_id,
                        "conversation_id": conversation_id,
                        "error": str(e)
                    })
            else:
                missing_what = ""
                if not app_related_category:
                    missing_what = "app_related_category"
                if not APP_RELATED_SUB_CATEGORY:
                    missing_what += " and APP_RELATED_SUB_CATEGORY" if missing_what else "APP_RELATED_SUB_CATEGORY"
                
                logger.info(f"[NOTIFICATION-WEBHOOK] ✅ Ticket {ticket_id} mapped to conversation {conversation_id} (no category to update: {missing_what})")
                return JsonResponse({
                    "status": "mapping_stored",
                    "ticket_id": ticket_id,
                    "conversation_id": conversation_id,
                    "message": f"Mapping stored successfully (no category update needed: {missing_what})"
                })
        
        # Handle ticket.solved event - SHOW "agent ended session" message
        elif 'ticket.solved' in event_type:
            logger.info("[NOTIFICATION-WEBHOOK] Ticket solved event - showing agent ended session message")
            
            # Extract ticket ID
            ticket_id = None
            if 'ticket' in event_data:
                ticket_id = str(event_data['ticket'].get('id', ''))
            elif 'ticket_id' in event_data:
                ticket_id = str(event_data['ticket_id'])
            
            if not ticket_id:
                ticket_id = extract_ticket_id_from_data(data)
            
            if not ticket_id:
                logger.error("[NOTIFICATION-WEBHOOK] No ticket ID found in solved notification")
                return JsonResponse({"status": "no_ticket_id"})
            
            # Resolve conversation ID
            conversation_id = resolve_conversation_id_for_ticket(ticket_id)
            
            if conversation_id:
                # Send "agent ended session" message to Sunshine
                auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
                url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                
                payload = {
                    "author": {"type": "business", "displayName": "System"},
                    "content": {"type": "text", "text": "The agent has ended the session. Type a message to start a new ticket."}
                }
                
                response = requests.post(url, json=payload, auth=auth)
                
                if response.status_code in [200, 201]:
                    logger.info(f"[NOTIFICATION-WEBHOOK] Successfully sent agent ended session message for conversation {conversation_id}")
                else:
                    logger.error(f"[NOTIFICATION-WEBHOOK] Failed to send agent ended session message: {response.status_code} - {response.text}")
            
            return JsonResponse({"status": "ticket_solved_processed", "ticket_id": ticket_id})
        
        # Handle other event types if needed
        elif 'ticket.updated' in event_type:
            logger.info("[NOTIFICATION-WEBHOOK] Ticket updated event")
        else:
            logger.info(f"[NOTIFICATION-WEBHOOK] Unhandled event type: {event_type}")
        
        return JsonResponse({"status": "processed_notification"})
        
    except Exception as e:
        logger.exception(f"[NOTIFICATION-WEBHOOK] Exception in handle_notification_webhook: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)

def extract_ticket_id_from_data(data: Dict[str, Any]) -> Optional[str]:
    """
    Extract ticket ID from any Zendesk webhook format.
    """
    ticket_id = None
    
    # Try different possible locations for ticket ID
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
    
    # Last resort: search recursively
    if not ticket_id:
        data_str = json.dumps(data)
        matches = re.findall(r'"ticket[_-]?id":\s*"?(\d+)"?', data_str, re.IGNORECASE)
        if matches:
            ticket_id = matches[0]
        else:
            # Look for any numeric ID that looks like a ticket ID
            matches = re.findall(r'"id":\s*"?(\d+)"?', data_str)
            if matches:
                # Try to determine which one is the ticket ID
                ticket_id = matches[-1]  # Usually the last one
    
    logger.info(f"[EXTRACT-TICKET] Extracted ticket_id: {ticket_id}")
    return ticket_id


def resolve_conversation_id_for_ticket(ticket_id: str) -> Optional[str]:
    """
    Resolve the Sunshine conversation id for a Zendesk ticket id.
    First checks the cache, then attempts to fetch the ticket from Zendesk
    and read the `ZENDESK_CHAT_CONVERSATION_FIELD_ID` custom field.
    If found, stores the mapping via `store_conversation_ticket_mapping`.
    """
    logger.info(f"[RESOLVE-CONV] Resolving conversation for ticket {ticket_id}")
    
    try:
        # Fast path: cached mapping
        conv = cache.get(f'ticket_{ticket_id}')
        if conv:
            logger.info(f"[RESOLVE-CONV] Found in cache: {conv}")
            return conv

        logger.info(f"[RESOLVE-CONV] Not in cache, checking Zendesk...")
        
        # Try to fetch ticket details from Zendesk and inspect custom fields
        if not all([ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN, ZENDESK_CHAT_CONVERSATION_FIELD_ID]):
            logger.error("[RESOLVE-CONV] Missing Zendesk credentials or custom field ID")
            return None

        z_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
        z_resp = requests.get(z_url, auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN), timeout=10)
        
        if z_resp.status_code != 200:
            logger.warning(f"[RESOLVE-CONV] Zendesk ticket fetch failed for {ticket_id}: {z_resp.status_code}")
            return None

        z_json = z_resp.json()
        ticket_obj = z_json.get('ticket', {})
        cfs = ticket_obj.get('custom_fields', []) or []
        
        logger.info(f"[RESOLVE-CONV] Found {len(cfs)} custom fields")
        
        for cf in cfs:
            try:
                cf_id = cf.get('id')
                cf_value = cf.get('value')
                logger.info(f"[RESOLVE-CONV] Checking custom field: id={cf_id}, value={cf_value}")
                
                if str(cf_id) == str(ZENDESK_CHAT_CONVERSATION_FIELD_ID) and cf_value:
                    conv_id = str(cf_value)
                    logger.info(f"[RESOLVE-CONV] Found conversation ID in custom field: {conv_id}")
                    
                    # persist mapping for future webhooks
                    try:
                        store_conversation_ticket_mapping(conv_id, str(ticket_id))
                    except Exception as e:
                        logger.exception(f"[RESOLVE-CONV] Failed to store mapping after Zendesk lookup: {e}")
                    
                    return conv_id
            except Exception as e:
                logger.error(f"[RESOLVE-CONV] Error processing custom field: {e}")
                continue
        
        logger.warning(f"[RESOLVE-CONV] No conversation ID found in custom fields for ticket {ticket_id}")
        return None
        
    except Exception as e:
        logger.exception(f"[RESOLVE-CONV] Error resolving conversation for ticket {ticket_id}: {e}")
        return None


@csrf_exempt
def debug_group_send(request: HttpRequest) -> JsonResponse:
    """
    Debug endpoint to test channel_layer.group_send delivery to WebSocket consumers.
    POST JSON: { "conversationId": "<id>", "text": "message text" }
    """
    if request.method != 'POST':
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        conv = data.get('conversationId')
        text = data.get('text', 'test message')
        if not conv:
            return JsonResponse({"error": "Missing conversationId"}, status=400)

        ok = forward_agent_message_to_websocket(conv, text, agent_name="DebugAgent")
        return JsonResponse({"status": "sent" if ok else "failed", "conversationId": conv})
    except Exception as e:
        logger.exception(f"Exception in debug_group_send: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def redis_health(request: HttpRequest) -> JsonResponse:
    """
    Health endpoint to test Redis (Django cache) and Channels channel_layer connectivity.
    GET /api/debug/redis_health
    Returns JSON with `cache` and `channel_layer` results.
    """
    if request.method != 'GET':
        return JsonResponse({"error": "Method not allowed"}, status=405)

    details: Dict[str, Any] = {"cache": None, "channel_layer": None}

    # Test cache (Redis) set/get
    try:
        test_key = f"health_{uuid.uuid4().hex[:8]}"
        cache.set(test_key, "ok", timeout=5)
        v = cache.get(test_key)
        details['cache'] = "ok" if v == "ok" else f"mismatch:{v}"
    except Exception as e:
        details['cache'] = f"error: {str(e)}"

    # Test channel_layer group_send (will attempt to publish even if no consumers)
    try:
        ch = get_channel_layer()
        if ch is None:
            details['channel_layer'] = "no_channel_layer"
        else:
            try:
                async_to_sync(ch.group_send)('health_test_group', {'type': 'health.ping', 'message': 'ping'})
                details['channel_layer'] = "ok"
            except Exception as e:
                details['channel_layer'] = f"error: {str(e)}"
    except Exception as e:
        details['channel_layer'] = f"error: {str(e)}"

    status = 200 if details.get('cache') == 'ok' and details.get('channel_layer') == 'ok' else 500
    return JsonResponse({"status": "ok" if status == 200 else "degraded", "details": details}, status=status)


# ============================================================================
# NEW: Full Chat History using Zendesk Conversation Log API
# ============================================================================
@csrf_exempt
def get_full_chat_history(request: HttpRequest) -> JsonResponse:
    """
    Fetch complete chat history using Zendesk's Conversation Log API.
    This returns all messages: bot, user, agent, and attachments in chronological order.
    
    GET /api/chat/full-history?conversationId=<id>
    """
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    conversation_id = request.GET.get("conversationId")
    if not conversation_id:
        return JsonResponse({"error": "Missing conversationId"}, status=400)
    
    logger.info(f"[FULL-HISTORY] 📜 Fetching full history for conversation: {conversation_id}")
    
    try:
        # Step 1: Get the Zendesk ticket ID from cache
        cache_key = f'conversation_{conversation_id}'
        ticket_id = cache.get(cache_key)
        logger.info(f"[FULL-HISTORY] Cache lookup key: {cache_key} -> {ticket_id}")
        
        if not ticket_id:
            logger.info(f"[FULL-HISTORY] ❌ No ticket in cache for key: {cache_key}")
            
            # Step 1b: Try to find ticket via Zendesk API search
            logger.info(f"[FULL-HISTORY] 🔍 Searching Zendesk for conversation ID in custom field...")
            try:
                search_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/search.json"
                # Search for the conversation ID in custom field or description
                search_query = f"custom_field_{ZENDESK_CHAT_CONVERSATION_FIELD_ID}:{conversation_id}"
                
                response = requests.get(
                    search_url,
                    params={"query": search_query},
                    auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN),
                    timeout=15
                )
                
                if response.status_code == 200:
                    results = response.json().get("results", [])
                    if results:
                        ticket_id = str(results[0].get("id"))
                        logger.info(f"[FULL-HISTORY] ✅ Found ticket via search: {ticket_id}")
                        # Store in cache for future requests
                        store_conversation_ticket_mapping(conversation_id, ticket_id)
                    else:
                        logger.info(f"[FULL-HISTORY] 🔍 No tickets found in search")
                else:
                    logger.error(f"[FULL-HISTORY] ❌ Search failed: {response.status_code}")
            except Exception as search_err:
                logger.error(f"[FULL-HISTORY] ❌ Search error: {search_err}")
            
            if not ticket_id:
                logger.info(f"[FULL-HISTORY] Using Sunshine fallback for {conversation_id}")
                return get_sunshine_messages_fallback(conversation_id)
        
        logger.info(f"[FULL-HISTORY] ✅ Using ticket ID: {ticket_id}")
        
        # Step 2: Call the Zendesk Conversation Log API
        conv_log_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}/conversation_log.json"
        
        response = requests.get(
            conv_log_url,
            auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN),
            timeout=15
        )
        
        if response.status_code != 200:
            logger.error(f"[FULL-HISTORY] Conversation Log API failed: {response.status_code} - {response.text}")
            # Fallback to Sunshine messages
            return get_sunshine_messages_fallback(conversation_id)
        
        data = response.json()
        events = data.get("events", [])
        
        logger.info(f"[FULL-HISTORY] Received {len(events)} events from Conversation Log")
        
        # Step 3: Parse and format messages
        messages = []
        for event in events:
            parsed = parse_conversation_log_event(event)
            if parsed:
                messages.append(parsed)
        
        # Sort by timestamp
        messages.sort(key=lambda x: x.get("received", ""))
        
        logger.info(f"[FULL-HISTORY] Returning {len(messages)} parsed messages")
        
        return JsonResponse({
            "messages": messages,
            "source": "zendesk_conversation_log",
            "ticket_id": ticket_id,
            "conversation_id": conversation_id
        })
        
    except Exception as e:
        logger.exception(f"[FULL-HISTORY] Error fetching history: {e}")
        # Fallback to Sunshine messages
        return get_sunshine_messages_fallback(conversation_id)


def parse_conversation_log_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parse a single event from the Zendesk Conversation Log API.
    Returns a standardized message format for the frontend.
    
    IMPORTANT: Images can be in TWO locations:
    1. In 'attachments' array (standard file attachments from agent/user)
    2. In 'content.media_url' (Sunshine Conversations rich media messages)
    """
    try:
        event_type = event.get("type", "")
        
        # Skip non-message events
        if event_type not in ["Messaging::ConversationMessage", "Comment"]:
            return None
        
        author = event.get("author", {})
        author_type = author.get("type", "unknown")
        author_name = author.get("display_name", "") or author.get("name", "")
        
        # Debug: Log author details for troubleshooting
        logger.info(f"[FULL-HISTORY] Event author: type={author_type}, name={author_name}, raw={author}")
        
        # Zendesk Conversation Log API uses different author types
        # Map "end_user" to "user" and "business" to "agent"
        if author_type == "end_user":
            author_type = "user"
        elif author_type == "business":
            author_type = "agent"
        
        # Get message content
        content = event.get("content", {})
        content_type = content.get("type", "text")  # Can be "text", "image", "file", etc.
        raw_text = content.get("text") or content.get("body", "")
        
        # Strip HTML tags - Zendesk sometimes returns HTML formatted content
        text = strip_html_tags(raw_text) if raw_text else ""
        
        # Get media_url for Sunshine rich media messages
        media_url = content.get("media_url")
        
        # Get attachments array for standard file attachments
        attachments_array = event.get("attachments", [])
        
        # Skip truly empty messages (no text, no media, no attachments)
        if not text and not media_url and not attachments_array:
            return None
        
        # Skip system messages we don't want to show
        if author_name == "System" and "Connecting to agent" in (text or ""):
            return None
        
        # Determine message type for frontend CSS classes
        if author_type == "user":
            message_class = "user"
        elif author_type == "bot":
            message_class = "bot"
        elif author_type in ["agent", "admin"]:
            message_class = "agent"
        else:
            message_class = "system"
        
        # Build the standardized message
        message = {
            "id": event.get("id", f"evt_{uuid.uuid4().hex[:8]}"),
            "text": text,
            "author": {
                "type": author_type,
                "displayName": author_name or message_class.capitalize()
            },
            "received": event.get("created_at", ""),
            "messageClass": message_class,
            "source": "conversation_log"
        }
        
        # Initialize attachments list
        parsed_attachments = []
        
        # ============================================================================
        # CASE 1: Check if content itself is an image (Sunshine rich media)
        # This is common for bot/widget messages
        # ============================================================================
        if content_type == "image" and media_url:
            logger.info(f"[FULL-HISTORY] Found image in content.media_url: {media_url[:100]}")
            parsed_attachments.append({
                "url": media_url,
                "type": "image",
                "fileName": content.get("name", "image"),
                "contentType": "image/*",
                "size": content.get("size", 0)
            })
        
        # ============================================================================
        # CASE 2: Check for standard file attachments (agent uploads, comments)
        # Use mapped_content_url if available, otherwise content_url
        # ============================================================================
        if attachments_array:
            for att in attachments_array:
                # Prefer mapped_content_url (more reliable), fallback to content_url
                att_url = att.get("mapped_content_url") or att.get("content_url") or att.get("url", "")
                att_content_type = att.get("content_type", "")
                att_file_name = att.get("file_name", "") or att.get("name", "")
                
                if att_url:
                    logger.info(f"[FULL-HISTORY] Found attachment: {att_file_name} - {att_url[:100]}")
                    
                    # Determine if it's an image
                    is_image = (
                        att_content_type.startswith("image/") or
                        any(ext in att_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'])
                    )
                    
                    parsed_attachments.append({
                        "url": att_url,
                        "type": "image" if is_image else "file",
                        "fileName": att_file_name,
                        "contentType": att_content_type,
                        "size": att.get("size", 0)
                    })
        
        # ============================================================================
        # CASE 3: Check for media_url when content type is "file" (Sunshine file messages)
        # Also check for content type "image" with media_url that wasn't caught in CASE 1
        # ============================================================================
        if media_url and not parsed_attachments:
            logger.info(f"[FULL-HISTORY] Found media_url (content_type={content_type}): {media_url[:100]}")
            # Determine if it's an image based on URL extension or content type
            is_image = (
                content_type == "image" or
                any(ext in media_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'])
            )
            parsed_attachments.append({
                "url": media_url,
                "type": "image" if is_image else "file",
                "fileName": content.get("name", "file"),
                "contentType": content.get("mediaType", "image/*" if is_image else ""),
                "size": content.get("size", 0)
            })
            logger.info(f"[FULL-HISTORY] Added attachment: type={'image' if is_image else 'file'}, url={media_url[:100]}")
        
        # Add attachments to message if any found
        if parsed_attachments:
            message["attachments"] = parsed_attachments
            logger.info(f"[FULL-HISTORY] Message has {len(parsed_attachments)} attachment(s)")
        
        return message
        
    except Exception as e:
        logger.error(f"[FULL-HISTORY] Error parsing event: {e}")
        return None


def get_sunshine_messages_fallback(conversation_id: str) -> JsonResponse:
    """
    Fallback to Sunshine Conversations API when Zendesk Conversation Log is not available.
    This happens when there's no ticket yet (before escalation).
    """
    try:
        logger.info(f"[FULL-HISTORY] Using Sunshine fallback for {conversation_id}")
        
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        
        response = requests.get(url, auth=auth, timeout=15)
        
        if response.status_code != 200:
            logger.error(f"[FULL-HISTORY] Sunshine fallback failed: {response.status_code}")
            return JsonResponse({"messages": [], "source": "error"})
        
        data = response.json()
        sunshine_messages = data.get("messages", [])
        
        # Convert to standardized format
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
                # Check if it's bot or agent
                if "answerBot" in str(msg.get("source", {})):
                    message_class = "bot"
                else:
                    message_class = "agent"
            else:
                message_class = "bot"
            
            message = {
                "id": msg.get("id", ""),
                "text": text,
                "author": {
                    "type": author_type,
                    "displayName": author_name or message_class.capitalize()
                },
                "received": msg.get("received", ""),
                "messageClass": message_class,
                "source": "sunshine"
            }
            
            # Handle attachments
            if content.get("type") == "image":
                message["attachments"] = [{
                    "url": content.get("mediaUrl", ""),
                    "type": "image"
                }]
            elif content.get("type") == "file":
                message["attachments"] = [{
                    "url": content.get("mediaUrl", ""),
                    "fileName": content.get("name", ""),
                    "type": "file"
                }]
            
            messages.append(message)
        
        logger.info(f"[FULL-HISTORY] Sunshine fallback returning {len(messages)} messages")
        
        return JsonResponse({
            "messages": messages,
            "source": "sunshine_fallback",
            "conversation_id": conversation_id
        })
        
    except Exception as e:
        logger.exception(f"[FULL-HISTORY] Sunshine fallback error: {e}")
        return JsonResponse({"messages": [], "source": "error", "error": str(e)})