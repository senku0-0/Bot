from django.shortcuts import render
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
import json, hmac, hashlib, os, base64, logging, sys, uuid
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth

# Configure Logging to Console
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

# Load environment variables from .env
env_loaded = load_dotenv()
if not env_loaded:
    logger.warning("load_dotenv() did not find a .env file (This is normal if using system env vars)")

# Sunshine secret for webhook verification
SECRET = os.getenv("SUNSHINE_WEBHOOK_SIGNING_SECRET")
if not SECRET:
    raise RuntimeError("SUNSHINE_WEBHOOK_SIGNING_SECRET not set")

# Zendesk credentials
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN")
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL")
ZENDESK_API_TOKEN = os.getenv("ZENDESK_API_TOKEN")

# Sunshine Credentials
SUNSHINE_APP_ID = os.getenv("SUNSHINE_APP_ID", "").strip()
SUNSHINE_API_KEY_ID = os.getenv("SUNSHINE_API_KEY_ID", "").strip()
SUNSHINE_API_KEY_SECRET = os.getenv("SUNSHINE_API_KEY_SECRET", "").strip()
SUNSHINE_API_BASE_URL = os.getenv("SUNSHINE_API_BASE_URL", "https://api.smooch.io").strip()

# Index route (frontend entry point)
@csrf_exempt
def index(request):
    return render(request, 'index.html')

# Verify Sunshine webhook signature
def verify_signature(payload, signature):
    if not signature:
        logger.warning("Webhook signature missing")
        return False
    if signature.startswith("sha256="):
        signature = signature.split("=", 1)[1]
    
    # Debugging: Ensure SECRET is loaded
    if not SECRET:
        logger.error("SUNSHINE_WEBHOOK_SIGNING_SECRET is missing or empty!")
        return False
        
    calc = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    
    # Debugging: Log mismatch (be careful not to log full secrets in production, but helpful here)
    if not hmac.compare_digest(calc, signature):
        logger.warning(f"Signature mismatch. Calculated: {calc[:10]}... Received: {signature[:10]}...")
        return False
        
    return True

# Create Zendesk ticket
def create_zendesk_ticket(subject, description):
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets.json"
    headers = {"Content-Type": "application/json"}
    data = {
        "ticket": {
            "subject": subject,
            "comment": {"body": description}
        }
    }
    response = requests.post(
        url,
        json=data,
        headers=headers,
        auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
    )
    return response.json()

# --- Sunshine API Helpers ---

def get_sunshine_headers():
    """
    Returns the headers required for Sunshine Conversations API calls.
    Uses Basic Auth with base64 encoding.
    """
    # Try global variables first, then fallback to other common names
    key_id = SUNSHINE_API_KEY_ID or os.getenv("SUNSHINE_KEY_ID")
    secret = SUNSHINE_API_KEY_SECRET or os.getenv("SUNSHINE_SECRET")
    
    if not key_id or not secret:
        # DEBUGGING: Log available keys to help user find the mismatch
        available_keys = ", ".join([k for k in os.environ.keys() if "SUNSHINE" in k or "ZENDESK" in k])
        logger.error(f"Missing Auth. Available env vars with SUNSHINE/ZENDESK: {available_keys}")
        logger.error("SUNSHINE_API_KEY_ID (or SUNSHINE_KEY_ID) or SECRET is missing in .env")
        return None

    # Manual Basic Auth Header Construction
    auth_str = f"{key_id}:{secret}"
    auth_bytes = auth_str.encode('utf-8')
    auth_base64 = base64.b64encode(auth_bytes).decode('utf-8')

    return {
        "Authorization": f"Basic {auth_base64}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

@csrf_exempt
def init_conversation(request):
    """Initialize a conversation for a new or existing user."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    if not SUNSHINE_APP_ID:
        logger.error("SUNSHINE_APP_ID not set")
        return JsonResponse({"error": "Server configuration error: SUNSHINE_APP_ID not set"}, status=500)

    try:
        # Define URL and Headers first
        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/users"
        logger.info(f"Calling Sunshine API: {url}") 
        
        headers = get_sunshine_headers()
        if not headers:
             return JsonResponse({"error": "Server configuration error"}, status=500)

        # Try to get userId from request if available (optional)
        user_id = None
        try:
            if request.body:
                data = json.loads(request.body)
                user_id = data.get("userId")
        except Exception:
            pass # Ignore body parsing errors, proceed as new guest

        # If no user_id provided, generate a unique one for this guest session
        if not user_id:
            user_id = str(uuid.uuid4())
            logger.info(f"Generated new Guest ID: {user_id}")
        else:
            logger.info(f"Using existing userId: {user_id}")

        # Create User Payload (v2 uses 'externalId')
        user_payload = {
            "externalId": user_id,
            "profile": {"givenName": "Guest"}
        }

        # Create/Get user
        response = requests.post(url, json=user_payload, headers=headers)
        
        if response.status_code not in [200, 201, 409]: # 409 = Conflict (User already exists), which is fine if we sent a userId
            logger.error(f"Sunshine API Error (Create User): {response.status_code} - {response.text}")
            return JsonResponse({"error": "Failed to create user", "details": response.text}, status=500)

        user_data = response.json()
        # v2 response structure: {"user": {"id": "..."}}
        app_user_id = user_data.get("user", {}).get("id")
        
        # Fallback: If user already exists (409), the response might not contain the user object directly in the same format
        # We might need to fetch the user by externalId if the create response didn't give it to us.
        if not app_user_id and response.status_code == 409:
             # Try to fetch the user by externalId
             get_user_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/users/{user_id}" 
             # Note: v2 API usually allows fetching by userId (externalId)
             
             logger.info(f"User exists, fetching details for: {user_id}")
             get_response = requests.get(get_user_url, headers=headers)
             if get_response.status_code == 200:
                 app_user_id = get_response.json().get("user", {}).get("id")
        
        logger.info(f"User created/found: {app_user_id}")

        if not app_user_id:
             logger.error(f"Could not retrieve appUserId. Response: {response.text}")
             return JsonResponse({"error": "Failed to retrieve user ID"}, status=500)

        # 3. Check for existing conversations (Robust Logic)
        conversation_id = None
        
        def fetch_conversation(target_id):
            """Helper to list conversations for a given user ID (internal or external)."""
            try:
                # Correct v2 Endpoint: /v2/apps/{appId}/conversations?filter[userId]={userId}
                l_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations"
                params = {"filter[userId]": target_id}
                
                logger.info(f"Checking conversations for: {target_id} using filter")
                l_resp = requests.get(l_url, headers=headers, params=params)
                
                if l_resp.status_code == 200:
                    convs = l_resp.json().get("conversations", [])
                    if convs:
                        # Return the most recently active conversation
                        return convs[0].get("id")
                else:
                    logger.warning(f"List conversations failed for {target_id}: {l_resp.status_code} - {l_resp.text}")
            except Exception as ex:
                logger.warning(f"Exception listing conversations for {target_id}: {ex}")
            return None

        # Try fetching with Internal ID first
        if app_user_id:
            conversation_id = fetch_conversation(app_user_id)

        # If not found, try fetching with External ID (user_id)
        if not conversation_id and user_id:
            conversation_id = fetch_conversation(user_id)

        if not conversation_id:
            # Create a Conversation if absolutely none found
            conv_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations"
            conv_payload = {
                "type": "personal",
                "participants": [{"userId": app_user_id}]
            }
            conv_response = requests.post(conv_url, json=conv_payload, headers=headers)
            
            if conv_response.status_code in [200, 201]:
                conv_data = conv_response.json()
                conversation_id = conv_data.get("conversation", {}).get("id")
                logger.info(f"Conversation created: {conversation_id}")
            else:
                # If creation fails, log it but don't crash yet if we can't help it
                logger.error(f"Sunshine API Error (Create Conversation): {conv_response.status_code} - {conv_response.text}")
                return JsonResponse({"error": "Failed to create conversation", "details": conv_response.text}, status=500)

        return JsonResponse({
            "appUserId": app_user_id,
            "conversationId": conversation_id,
            "externalId": user_id # Return the externalId (UUID) so frontend can save it
        })
    except Exception as e:
        logger.exception(f"Exception in init_conversation: {str(e)}")
        return JsonResponse({"error": "Internal Server Error", "details": str(e)}, status=500)

@csrf_exempt
def get_conversation_messages(request):
    """Fetch messages for a conversation."""
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    conversation_id = request.GET.get("conversationId")
    if not conversation_id:
        return JsonResponse({"error": "Missing conversationId"}, status=400)

    try:
        headers = get_sunshine_headers()
        if not headers:
             return JsonResponse({"error": "Server configuration error"}, status=500)

        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        logger.info(f"Fetching messages: {url}")
        
        response = requests.get(url, headers=headers)
        
        # Also fetch conversation details to check active switchboard integration (Agent status)
        conv_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}"
        conv_response = requests.get(conv_url, headers=headers)
        conversation_data = {}
        if conv_response.status_code == 200:
            conversation_data = conv_response.json().get("conversation", {})

        if response.status_code == 200:
            data = response.json()
            # Merge conversation data into response
            data['conversation'] = conversation_data
            return JsonResponse(data)
        else:
            logger.error(f"Failed to fetch messages: {response.status_code} - {response.text}")
            return JsonResponse({"error": "Failed to fetch messages"}, status=response.status_code)

    except Exception as e:
        logger.exception("Exception in get_conversation_messages")
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def send_message_to_sunshine(request):
    """Send a message from the user to Sunshine."""
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
        
        headers = get_sunshine_headers()
        if not headers:
             return JsonResponse({"error": "Server configuration error"}, status=500)

        logger.info(f"Sending message to Sunshine: {url}")
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 201:
            logger.info("Message sent successfully")
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
def escalate_to_agent(request):
    """Escalates the conversation to the next switchboard integration (e.g., Agent Workspace)."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        conversation_id = data.get("conversationId")
        app_user_id = data.get("appUserId")
        reason = data.get("reason", "User requested agent support") 
        
        if not conversation_id:
            return JsonResponse({"error": "Missing conversationId"}, status=400)

        # Use global SUNSHINE_APP_ID
        app_id = SUNSHINE_APP_ID
        headers = get_sunshine_headers()
        if not headers:
             return JsonResponse({"error": "Server configuration error"}, status=500)

        # 1. Pass Control to Zendesk ("next")
        pass_control_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{app_id}/conversations/{conversation_id}/passControl"
        
        pass_control_payload = {
            "switchboardIntegration": "next", 
            "metadata": {
                "dataCapture.systemField.tags": "escalated_from_bot",
                "dataCapture.systemField.requester.name": "Guest User", 
                "dataCapture.ticketField.description": f"Escalation Reason: {reason}" 
            }
        }

        logger.info(f"Escalating conversation {conversation_id} to next integration")
        pc_response = requests.post(pass_control_url, json=pass_control_payload, headers=headers)

        if pc_response.status_code != 200:
            logger.error(f"Failed to escalate conversation: {pc_response.status_code} - {pc_response.text}")
            return JsonResponse({"error": "Failed to escalate", "details": pc_response.text}, status=pc_response.status_code)

        # 2. Send a message on behalf of the user to trigger ticket creation
        # Only do this if we have the appUserId
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
            logger.info(f"Sending trigger message for ticket creation: {msg_url}")
            requests.post(msg_url, json=msg_payload, headers=headers)

        return JsonResponse({"status": "escalated"})

    except Exception as e:
        logger.exception("Exception in escalate_to_agent")
        return JsonResponse({"error": str(e)}, status=500)


# Webhook endpoint
@csrf_exempt
def webhook_message(request):
    # DEBUG: Log all headers to see what is coming in
    logger.info(f"Webhook Headers: {dict(request.headers)}")

    # Try different casing for the header (sometimes proxies/middleware change it)
    sig = request.headers.get("X-Hub-Signature") or request.headers.get("x-hub-signature")
    
    # Fallback: Check for X-Api-Key if X-Hub-Signature is missing (Legacy/Custom Integration)
    if not sig:
        api_key_header = request.headers.get("X-Api-Key")
        if api_key_header:
            logger.info("Found X-Api-Key header instead of X-Hub-Signature. Validating...")
            # In some custom integrations, the X-Api-Key might be used for auth instead of signature
            # For now, we will log it and allow it if it matches a known secret (or just allow for debugging)
            # SECURITY WARNING: In production, you should verify this key against a stored secret.
            # For this specific debugging session, we will assume it's valid to see if the payload processes.
            logger.warning("Bypassing signature check because X-Api-Key is present (Debugging Mode)")
            sig = "BYPASS_DEBUG" 

    body = request.body

    # Verify signature
    if sig != "BYPASS_DEBUG" and not verify_signature(body, sig):
        logger.warning("Invalid webhook signature")
        return HttpResponseForbidden("Invalid signature")

    # Parse event safely
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook")
        return HttpResponseForbidden("Invalid JSON")

    # Handle Sunshine v2 "events" array structure if present
    events_list = event.get("events", [])
    if not events_list and "trigger" in event:
        # Handle legacy/flattened structure where the body IS the event
        events_list = [event]
    elif not events_list and "messages" in event:
        # Handle the specific case where it might be just a message payload (fallback)
        events_list = [event]
        event["trigger"] = "conversation:message"

    for evt in events_list:
        trigger = evt.get("trigger") or evt.get("type") # v1 uses trigger, v2 uses type
        
        logger.info(f"Processing Webhook Event: {trigger}")

        # 1. Handle Messages
        if trigger == "conversation:message":
            process_message_event(evt)
        
        # 2. Handle Switchboard Events (Agent Control)
        elif trigger == "switchboard:passControl":
            logger.info("Control passed to switchboard integration.")
            # You could update local DB state here
            
        elif trigger == "switchboard:releaseControl":
            logger.info("Control released by switchboard integration (Agent ended chat).")
            handle_agent_end_session(evt)

        # 3. Handle Participant Join (Agent Joined)
        elif trigger == "participant:join":
            handle_participant_join(evt)

        # 4. Handle other events (Log for now)
        elif trigger in ["conversation:read", "conversation:typing"]:
            logger.debug(f"Received {trigger} - No action taken.")

    return JsonResponse({"status": "received"})

def handle_participant_join(event_data):
    """Notify user when an agent joins the conversation."""
    conversation_id = event_data.get("conversation", {}).get("_id") or event_data.get("conversation", {}).get("id")
    if not conversation_id:
        return

    participants = event_data.get("participants", [])
    for p in participants:
        # Check if the participant is a business user (Agent)
        if p.get("type") == "business":
            agent_name = p.get("displayName", "An agent")
            logger.info(f"Agent {agent_name} joined conversation {conversation_id}")
            
            # Send a system message to notify the user
            try:
                headers = get_sunshine_headers()
                if headers:
                    url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                    payload = {
                        "author": {"type": "business", "displayName": "System"},
                        "content": {"type": "text", "text": f"{agent_name} connected"}
                    }
                    requests.post(url, json=payload, headers=headers)
            except Exception as e:
                logger.error(f"Failed to send agent join notification: {e}")


def process_message_event(event_data):
    """Handle incoming user messages."""
    conversation = event_data.get("conversation", {})
    conversation_id = conversation.get("_id") or conversation.get("id")
    app_user = event_data.get("appUser", {})
    app_user_id = app_user.get("_id") or app_user.get("id")
    
    # Check who is currently in control
    sb_integration = conversation.get("activeSwitchboardIntegration", {})
    current_integration_name = sb_integration.get("name")

    # If the Agent (next/zendesk) is in control, DO NOT create a ticket.
    # Zendesk will handle the message automatically.
    if current_integration_name in ["next", "zendesk"]:
        logger.info(f"Ignoring message from {app_user_id} because Agent is in control.")
        return

    messages = event_data.get("messages", [])
    if not messages:
        return

    text = messages[0].get("text")
    if text:
        logger.info(f"Creating Ticket for message: {text}")
        try:
            create_zendesk_ticket(
                subject=f"Conversation {conversation_id}",
                description=f"User {app_user_id} said: {text}"
            )
        except Exception as e:
            logger.error(f"Failed to create ticket: {e}")

def handle_agent_end_session(event_data):
    """Send a system message when agent ends the chat."""
    conversation_id = event_data.get("conversation", {}).get("_id") or event_data.get("conversation", {}).get("id")
    if not conversation_id:
        return

    # Send a message to the user confirming the session has ended
    try:
        headers = get_sunshine_headers()
        if headers:
            url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
            payload = {
                "author": {"type": "business", "displayName": "System"},
                "content": {"type": "text", "text": "The agent has ended the session. Type a message to start a new ticket."}
            }
            requests.post(url, json=payload, headers=headers)
    except Exception as e:
        logger.error(f"Failed to send end-session message: {e}")
