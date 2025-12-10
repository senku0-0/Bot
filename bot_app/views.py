from django.shortcuts import render
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
import json, hmac, hashlib, os

@csrf_exempt
def index(request):
    return render(request, 'index.html')

SECRET = os.getenv("SUNSHINE_WEBHOOK_SIGNING_SECRET")

def verify_signature(payload, signature):
    calc = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, signature or "")

@csrf_exempt
def webhook_message(request):
    sig = request.headers.get("X-Hub-Signature")
    body = request.body

    # Verify signature
    if not verify_signature(body, sig):
        return HttpResponseForbidden()

    # Parse event
    event = json.loads(body)
    conversation_id = event["conversation"]["_id"]
    app_user_id = event["appUser"]["_id"]
    text = event["messages"][0]["text"]

    # For now, just log/return the data
    print(f"Webhook received: {conversation_id}, {app_user_id}, {text}")

    return JsonResponse({"status": "ok"})
