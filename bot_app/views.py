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

        # 3. Check for existing conversations first (to avoid Multi-convo error)
        conversation_id = None
        list_conv_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/users/{app_user_id}/conversations"
        
        try:
            list_response = requests.get(list_conv_url, headers=headers)
            if list_response.status_code == 200:
                conversations = list_response.json().get("conversations", [])
                if conversations:
                    # Use the most recent conversation
                    conversation_id = conversations[0].get("id")
                    logger.info(f"Found existing conversation: {conversation_id}")
        except Exception as e:
            logger.warning(f"Failed to list conversations: {e}")

        if not conversation_id:
            # Create a Conversation if none found
            conv_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations"
            conv_payload = {
                "type": "personal",
                "participants": [{"userId": app_user_id}]
            }
            conv_response = requests.post(conv_url, json=conv_payload, headers=headers)
            
            if conv_response.status_code not in [200, 201]:
                logger.error(f"Sunshine API Error (Create Conversation): {conv_response.status_code} - {conv_response.text}")
                return JsonResponse({"error": "Failed to create conversation", "details": conv_response.text}, status=500)

            conv_data = conv_response.json()
            conversation_id = conv_data.get("conversation", {}).get("id")
            logger.info(f"Conversation created: {conversation_id}")

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
        
        if response.status_code == 200:
            return JsonResponse(response.json())
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
        
        if not conversation_id:
            return JsonResponse({"error": "Missing conversationId"}, status=400)

        app_id = os.getenv("SUNSHINE_APP_ID")
        headers = get_sunshine_headers()
        if not headers:
             return JsonResponse({"error": "Server configuration error"}, status=500)

        url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{app_id}/conversations/{conversation_id}/passControl"
        
        # "next" passes control to the configured next integration (usually Agent Workspace)
        payload = {
            "switchboardIntegration": "next", 
            "metadata": {"dataCapture.systemField.tags": "escalated_from_bot"}
        }

        logger.info(f"Escalating conversation {conversation_id} to next integration")
        response = requests.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            logger.info("Conversation escalated successfully.")
            return JsonResponse({"status": "escalated"})
        else:
            logger.error(f"Failed to escalate conversation: {response.status_code} - {response.text}")
            return JsonResponse({"error": "Failed to escalate", "details": response.text}, status=500)

    except Exception as e:
        logger.exception("Exception in escalate_to_agent")
        return JsonResponse({"error": str(e)}, status=500)


# Webhook endpoint
@csrf_exempt
def webhook_message(request):
    # DEBUG: Log all headers to see what is coming in
    logger.info(f"Webhook Headers: {dict(request.headers)}")

    sig = request.headers.get("X-Hub-Signature")
    body = request.body

    # Verify signature
    if not verify_signature(body, sig):
        logger.warning("Invalid webhook signature")
        return HttpResponseForbidden("Invalid signature")

    # Parse event safely
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook")
        return HttpResponseForbidden("Invalid JSON")

    conversation_id = event.get("conversation", {}).get("_id")
    app_user_id = event.get("appUser", {}).get("_id")
    messages = event.get("messages", [])
    text = messages[0].get("text") if messages else None

    logger.info(f"Webhook received: {conversation_id}, {app_user_id}, {text}")

    # ✅ Create Zendesk ticket if message exists
    ticket_response = None
    if text:
        try:
            ticket_response = create_zendesk_ticket(
                subject=f"Conversation {conversation_id}",
                description=f"User {app_user_id} said: {text}"
            )
            logger.info(f"Zendesk ticket created: {ticket_response}")
        except Exception as e:
            logger.error(f"Failed to create Zendesk ticket: {e}")

    return JsonResponse({
        "status": "ok",
        "conversation_id": conversation_id,
        "app_user_id": app_user_id,
        "text": text,
        "zendesk_ticket": ticket_response
    })
