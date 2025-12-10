from django.shortcuts import render
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
import json, hmac, hashlib, os
from dotenv import load_dotenv
import requests
from requests.auth import HTTPBasicAuth

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

# Sunshine Credentials
SUNSHINE_APP_ID = os.getenv("SUNSHINE_APP_ID")
SUNSHINE_API_KEY_ID = os.getenv("SUNSHINE_API_KEY_ID")
SUNSHINE_API_KEY_SECRET = os.getenv("SUNSHINE_API_KEY_SECRET")

# Index route (frontend entry point)
@csrf_exempt
def index(request):
    return render(request, 'index.html')

# Verify Sunshine webhook signature
def verify_signature(payload, signature):
    if not signature:
        return False
    if signature.startswith("sha256="):
        signature = signature.split("=", 1)[1]
    calc = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, signature)

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

def get_sunshine_auth():
    return HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)

@csrf_exempt
def init_conversation(request):
    """Initialize a conversation for a new or existing user."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    if not SUNSHINE_APP_ID:
        return JsonResponse({"error": "Server configuration error: SUNSHINE_APP_ID not set"}, status=500)

    try:
        # Create an App User
        url = f"https://api.smooch.io/v2/apps/{SUNSHINE_APP_ID}/appusers"
        # We can optionally pass a userId if we have one, otherwise Sunshine generates one
        response = requests.post(url, json={}, auth=get_sunshine_auth())
        
        if response.status_code != 201 and response.status_code != 200:
            print(f"Sunshine API Error (Create User): {response.status_code} - {response.text}")
            return JsonResponse({"error": "Failed to create user", "details": response.text}, status=500)

        user_data = response.json()
        app_user_id = user_data.get("appUser", {}).get("_id")

        # Create a Conversation (or get existing)
        # Note: Sunshine v2 automatically creates a conversation when a message is sent, 
        # but we can explicitly create one to get the ID upfront.
        conv_url = f"https://api.smooch.io/v2/apps/{SUNSHINE_APP_ID}/appusers/{app_user_id}/conversations"
        conv_response = requests.post(conv_url, json={}, auth=get_sunshine_auth())
        
        if conv_response.status_code != 201 and conv_response.status_code != 200:
            print(f"Sunshine API Error (Create Conversation): {conv_response.status_code} - {conv_response.text}")
            return JsonResponse({"error": "Failed to create conversation", "details": conv_response.text}, status=500)

        conv_data = conv_response.json()
        conversation_id = conv_data.get("conversation", {}).get("_id")

        return JsonResponse({
            "appUserId": app_user_id,
            "conversationId": conversation_id
        })
    except Exception as e:
        print(f"Exception in init_conversation: {str(e)}")
        return JsonResponse({"error": "Internal Server Error", "details": str(e)}, status=500)

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

        url = f"https://api.smooch.io/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
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
        
        response = requests.post(url, json=payload, auth=get_sunshine_auth())
        
        if response.status_code == 201:
            return JsonResponse({"status": "sent", "data": response.json()})
        else:
            print(f"Sunshine API Error (Send Message): {response.status_code} - {response.text}")
            return JsonResponse({"error": "Failed to send message", "details": response.text}, status=500)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        print(f"Exception in send_message_to_sunshine: {str(e)}")
        return JsonResponse({"error": "Internal Server Error", "details": str(e)}, status=500)


# Webhook endpoint
@csrf_exempt
def webhook_message(request):
    sig = request.headers.get("X-Hub-Signature")
    body = request.body

    # Verify signature
    if not verify_signature(body, sig):
        return HttpResponseForbidden("Invalid signature")

    # Parse event safely
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        return HttpResponseForbidden("Invalid JSON")

    conversation_id = event.get("conversation", {}).get("_id")
    app_user_id = event.get("appUser", {}).get("_id")
    messages = event.get("messages", [])
    text = messages[0].get("text") if messages else None

    print(f"Webhook received: {conversation_id}, {app_user_id}, {text}")

    # ✅ Create Zendesk ticket if message exists
    ticket_response = None
    if text:
        ticket_response = create_zendesk_ticket(
            subject=f"Conversation {conversation_id}",
            description=f"User {app_user_id} said: {text}"
        )
        print("Zendesk ticket created:", ticket_response)

    return JsonResponse({
        "status": "ok",
        "conversation_id": conversation_id,
        "app_user_id": app_user_id,
        "text": text,
        "zendesk_ticket": ticket_response
    })
