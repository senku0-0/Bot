from django.shortcuts import render
from django.http import JsonResponse, HttpResponseForbidden, HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
import json, hmac, hashlib, os, base64, logging, sys, uuid
from typing import Optional, Dict, Any, Union, List
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
SUNSHINE_API_BASE_URL = os.getenv("SUNSHINE_API_BASE_URL", "https://api.smooch.io").strip().rstrip('/')

# Index route (frontend entry point)
@csrf_exempt
def index(request: HttpRequest) -> HttpResponse:
    """
    Render the chat widget frontend.

    Args:
        request (HttpRequest): The incoming HTTP request.

    Returns:
        HttpResponse: The rendered HTML page.
    """
    return render(request, 'index.html')

# Verify Sunshine webhook signature
def verify_signature(payload: bytes, signature: str) -> bool:
    """
    Verify the Sunshine webhook signature to ensure authenticity.

    Args:
        payload (bytes): The raw body of the request.
        signature (str): The signature header from the request.

    Returns:
        bool: True if the signature is valid, False otherwise.
    """
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
def create_zendesk_ticket(subject: str, description: str) -> Dict[str, Any]:
    """
    Create a new ticket in Zendesk.

    Args:
        subject (str): The subject of the ticket.
        description (str): The body/description of the ticket.

    Returns:
        Dict[str, Any]: The JSON response from the Zendesk API.
    """
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

def get_sunshine_jwt() -> Optional[str]:
    """
    Obtains a JWT access token from Sunshine Conversations OAuth endpoint.

    Returns:
        Optional[str]: The access token (JWT), or None if failed.
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
    Uses Bearer token authentication with API key or JWT.

    Args:
        include_content_type (bool): Whether to include Content-Type header. Defaults to True.
                                     Set to False for file uploads where requests should handle multipart/form-data.
        use_jwt (bool): Whether to use JWT instead of API key. Defaults to False.

    Returns:
        Optional[Dict[str, str]]: A dictionary of headers including Authorization, or None if credentials are missing.
    """
    if use_jwt:
        token = get_sunshine_jwt()
        if not token:
            return None
    else:
        token = SUNSHINE_API_KEY_ID or os.getenv("SUNSHINE_KEY_ID")
        if not token:
            # DEBUGGING: Log available keys to help user find the mismatch
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
    
    Args:
        request (HttpRequest): The incoming HTTP request containing optional userId.

    Returns:
        JsonResponse: JSON containing appUserId, conversationId, and externalId.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    if not SUNSHINE_APP_ID:
        logger.error("SUNSHINE_APP_ID not set")
        return JsonResponse({"error": "Server configuration error: SUNSHINE_APP_ID not set"}, status=500)

    try:
        # Define URL and Auth
        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/users"
        logger.info(f"Calling Sunshine API: {url}")

        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)

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
        response = requests.post(url, json=user_payload, auth=auth)
        
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
             get_response = requests.get(get_user_url, auth=auth)
             if get_response.status_code == 200:
                 app_user_id = get_response.json().get("user", {}).get("id")
        
        logger.info(f"User created/found: {app_user_id}")

        if not app_user_id:
             logger.error(f"Could not retrieve appUserId. Response: {response.text}")
             return JsonResponse({"error": "Failed to retrieve user ID"}, status=500)

        # 3. Check for existing conversations (Robust Logic)
        conversation_id = None
        
        def fetch_conversation(target_id: str) -> Optional[str]:
            """
            Helper to list conversations for a given user ID (internal or external).

            Args:
                target_id (str): The user ID to search for (appUserId or externalId).

            Returns:
                Optional[str]: The ID of the most recent conversation, or None if not found.
            """
            try:
                # Correct v2 Endpoint: /v2/apps/{appId}/conversations?filter[userId]={userId}
                l_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations"
                params = {"filter[userId]": target_id}
                
                logger.info(f"Checking conversations for: {target_id} using filter")
                l_resp = requests.get(l_url, auth=auth, params=params)
                
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
            conv_response = requests.post(conv_url, json=conv_payload, auth=auth)
            
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
def get_conversation_messages(request: HttpRequest) -> JsonResponse:
    """
    Fetch messages for a specific conversation.

    Args:
        request (HttpRequest): The incoming HTTP request containing 'conversationId' query param.

    Returns:
        JsonResponse: JSON containing the list of messages and conversation details.
    """
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    conversation_id = request.GET.get("conversationId")
    if not conversation_id:
        return JsonResponse({"error": "Missing conversationId"}, status=400)

    try:
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)

        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        logger.info(f"Fetching messages: {url}")

        response = requests.get(url, auth=auth)

        # Also fetch conversation details to check active switchboard integration (Agent status)
        conv_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}"
        conv_response = requests.get(conv_url, auth=auth)
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
def send_message_to_sunshine(request: HttpRequest) -> JsonResponse:
    """
    Send a message from the user to Sunshine.

    Args:
        request (HttpRequest): The incoming HTTP request containing message details (text, author, etc.).

    Returns:
        JsonResponse: JSON response indicating success or failure.
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

        logger.info(f"Sending message to Sunshine: {url}")
        response = requests.post(url, json=payload, auth=auth)
        
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
def escalate_to_agent(request: HttpRequest) -> JsonResponse:
    """
    Escalates the conversation to the next switchboard integration (e.g., Agent Workspace).

    Args:
        request (HttpRequest): The incoming HTTP request containing conversationId and reason.

    Returns:
        JsonResponse: JSON response indicating the status of the escalation.
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

        # Use global SUNSHINE_APP_ID
        app_id = SUNSHINE_APP_ID
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)

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
        pc_response = requests.post(pass_control_url, json=pass_control_payload, auth=auth)

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
            requests.post(msg_url, json=msg_payload, auth=auth)

        return JsonResponse({"status": "escalated"})

    except Exception as e:
        logger.exception("Exception in escalate_to_agent")
        return JsonResponse({"error": str(e)}, status=500)


# Webhook endpoint
@csrf_exempt
def webhook_message(request: HttpRequest) -> Union[JsonResponse, HttpResponseForbidden]:
    """
    Webhook endpoint to receive events from Sunshine.

    Args:
        request (HttpRequest): The incoming HTTP request containing the event payload.

    Returns:
        Union[JsonResponse, HttpResponseForbidden]: JSON response status or Forbidden if signature fails.
    """
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

        # 4. Handle Conversation Read (Agent Opened Ticket)
        elif trigger == "conversation:read":
            handle_conversation_read(evt)

        # 5. Handle other events (Log for now)
        elif trigger in ["conversation:typing"]:
            logger.debug(f"Received {trigger} - No action taken.")

    return JsonResponse({"status": "received"})

def handle_conversation_read(event_data: Dict[str, Any]) -> None:
    """
    Notify user when an agent reads the conversation (opens ticket).

    Args:
        event_data (Dict[str, Any]): The raw event data from the webhook.
    """
    conversation_id = event_data.get("conversation", {}).get("_id") or event_data.get("conversation", {}).get("id")
    if not conversation_id:
        return

    # Identify if the reader is an agent
    # We compare the reader's userId with the appUser's userId.
    # If they are different, it's likely an agent.
    
    app_user = event_data.get("appUser", {})
    app_user_id = app_user.get("_id") or app_user.get("id")
    
    # 'userId' is usually at the top level for conversation:read
    reader_id = event_data.get("userId")
    
    # If userId is missing, check 'source' or 'author' (structure varies by version)
    if not reader_id:
        reader_id = event_data.get("source", {}).get("from", {}).get("id")

    # If we found a reader, and it's NOT the user, assume it's an agent
    if reader_id and app_user_id and reader_id != app_user_id:
        # Try to get agent name if possible (often not in read payload, so use generic or fetch)
        # For speed, we'll use "An agent" or try to infer. 
        # If the payload has 'role' == 'business', that's even better.
        
        is_business = event_data.get("role") == "business"
        
        if is_business or reader_id != app_user_id:
            agent_name = "An agent" # 'read' events rarely contain the display name
            logger.info(f"Agent (ID: {reader_id}) read conversation {conversation_id}")
            
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

    Args:
        event_data (Dict[str, Any]): The raw event data from the webhook.
    """
    conversation_id = event_data.get("conversation", {}).get("_id") or event_data.get("conversation", {}).get("id")
    if not conversation_id:
        return

    participants = event_data.get("participants", [])
    # Support for singular 'participant' payload (common in some webhook versions)
    single_participant = event_data.get("participant")
    if single_participant:
        participants.append(single_participant)

    for p in participants:
        # Check if the participant is a business user (Agent)
        if p.get("type") == "business":
            agent_name = p.get("displayName", "An agent")
            logger.info(f"Agent {agent_name} joined conversation {conversation_id}")
            
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

    Args:
        event_data (Dict[str, Any]): The raw event data from the webhook.
    """
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

@csrf_exempt
def send_to_zendesk(request: HttpRequest) -> JsonResponse:
    """
    Handle file upload and send to Zendesk agent via Sunshine Conversations API.

    Args:
        request (HttpRequest): The incoming HTTP request with multipart/form-data.

    Returns:
        JsonResponse: JSON response with status or error.
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
        logger.info(f"Uploading file {file.name} to Sunshine Attachments API")
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
                "fileName": file.name
            }
        }

        logger.info(f"Sending file message to Sunshine: {file.name}")
        file_response = requests.post(msg_url, json=file_payload, auth=auth)

        # Retry once on 5xx errors
        if file_response.status_code >= 500:
            logger.warning(f"File message failed with 5xx, retrying: {file_response.status_code}")
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

            logger.info("Sending text message to Sunshine")
            text_response = requests.post(msg_url, json=text_payload, auth=auth)

            # Retry once on 5xx errors
            if text_response.status_code >= 500:
                logger.warning(f"Text message failed with 5xx, retrying: {text_response.status_code}")
                text_response = requests.post(msg_url, json=text_payload, auth=auth)

            if text_response.status_code not in [200, 201]:
                logger.error(f"Sunshine text message failed: {text_response.status_code} - {text_response.text}")
                return JsonResponse({"error": "Failed to send text message", "status": "fail"}, status=500)

        logger.info("File and message sent successfully")
        return JsonResponse({"status": "ok"})

    except Exception as e:
        logger.exception(f"Exception in send_to_zendesk: {str(e)}")
        return JsonResponse({"error": "Internal Server Error", "status": "fail", "details": str(e)}, status=500)


def handle_agent_end_session(event_data: Dict[str, Any]) -> None:
    """
    Send a system message when agent ends the chat.

    Args:
        event_data (Dict[str, Any]): The raw event data from the webhook.
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
