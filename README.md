# Zendesk Sunshine Conversation Bot - Complete Documentation

## 📋 Table of Contents

1. [Project Introduction](#-project-introduction)
2. [System Overview](#-system-overview)
   - [Core Components](#core-components)
   - [Data Flow](#data-flow)
3. [Technology Stack](#-technology-stack)
   - [Backend](#backend)
   - [Frontend (Chat Widget)](#frontend-chat-widget)
   - [External Services](#external-services)
4. [Architecture Diagram](#-architecture-diagram)
   - [Request-Response Flow](#request-response-flow)
5. [Zendesk Sunshine Conversations](#-zendesk-sunshine-conversations)
   - [What is Sunshine Conversations?](#what-is-sunshine-conversations)
   - [Key Concepts](#key-concepts)
6. [API Documentation](#-api-documentation)
   - [Authentication](#authentication)
   - [1. Initialize Conversation](#1-initialize-conversation)
   - [2. Send Message to Sunshine](#2-send-message-to-sunshine)
   - [3. Get Conversation Messages](#3-get-conversation-messages)
   - [4. Escalate to Agent](#4-escalate-to-agent)
   - [5. Get Full Chat History](#5-get-full-chat-history)
   - [6. Send File/Attachment](#6-send-file--attachment)
   - [7. Update Viewing Status](#7-update-viewing-status)
   - [8. Clear Unread Badge](#8-clear-unread-badge)
   - [9. Image Proxy](#9-image-proxy)
   - [10. Sunshine Webhook Handler](#10-sunshine-webhook-handler)
   - [11. Zendesk Webhook Handler](#11-zendesk-webhook-handler)
7. [WebSocket Implementation](#-websocket-implementation)
   - [Purpose](#purpose)
   - [Protocol](#protocol)
   - [Connection Flow](#connection-flow)
   - [Message Types](#message-types)
   - [Channel Layer Groups](#channel-layer-groups)
   - [Code Structure](#code-structure)
   - [Django Integration](#django-integration)
   - [Redis Channel Layer Configuration](#redis-channel-layer-configuration)
8. [Variables Reference](#-variables-reference)
   - [Conversation ID](#conversation-id)
   - [User Identifiers](#user-identifiers)
   - [App ID](#app-id)
   - [Zendesk IDs](#zendesk-ids)
   - [Webhook Security](#webhook-security)
   - [Field IDs](#field-ids)
   - [Channel Groups](#channel-groups)
9. [CSAT & Attachments](#-csat--attachments)
   - [CSAT (Customer Satisfaction)](#csat-customer-satisfaction)
   - [File Attachments](#file-attachments)
10. [Message History](#-message-history)
   - [History Sources](#history-sources)
   - [History Retrieval Flow](#history-retrieval-flow)
   - [Message Deduplication](#message-deduplication)
   - [Zendesk Conversation Log Parsing](#zendesk-conversation-log-parsing)
   - [Attachment Handling in History](#attachment-handling-in-history)
10. [Notifications System](#-notifications-system)
    - [Architecture](#architecture)
    - [SSE Endpoints](#sse-endpoints)
    - [Notification Flow](#notification-flow)
    - [Notification Structure](#notification-structure)
    - [Unread Badge Logic](#unread-badge-logic)
    - [SSE Implementation Details](#sse-implementation-details)
    - [Cache Keys Reference](#cache-keys-reference)
11. [Environment Configuration](#-environment-configuration)
    - [Required Environment Variables](#required-environment-variables)
    - [Environment Variable Details](#environment-variable-details)
    - [Configuration in settings.py](#configuration-in-settingspy)
    - [Local Development .env File](#local-development-env-file)
12. [Deployment Guide](#-deployment-guide)
    - [Local Development](#local-development)
    - [Production Deployment (Render.com)](#production-deployment-rendercom)
    - [Database Migrations](#database-migrations)
    - [Health Check](#health-check)
13. [Chat Workflows](#-chat-workflows)
    - [Others Option (Direct Escalation)](#others-option-direct-escalation)
    - [Standard Troubleshooting Flow](#standard-troubleshooting-flow)
    - [Feedback to Agent Connection](#feedback-to-agent-connection)
14. [API Quick Reference](#-api-quick-reference)
15. [Security Considerations](#-security-considerations)
    - [CSRF Protection](#csrf-protection)
    - [Signature Verification](#signature-verification)
    - [Authentication](#authentication)
    - [Rate Limiting](#rate-limiting)
    - [Data Privacy](#data-privacy)
16. [Troubleshooting](#-troubleshooting)
    - [Common Issues](#common-issues)
17. [Additional Resources](#-additional-resources)

---

## 📌 Project Introduction

This is a **Django-based Conversational Bot** that integrates with **Zendesk Sunshine Conversations** (formerly Smooch) to provide real-time chat support. The system enables:

- **Real-time messaging** between customers and support agents
- **Bot escalation** to live agents when needed
- **Bi-directional communication** between Zendesk Sunshine and Zendesk Support tickets
- **WebSocket-based live chat** with persistent connections
- **File attachments and media** support
- **Chat history** with deduplication
- **Notification system** for new messages
- **CSAT (Customer Satisfaction)** feedback collection
- **Server-Sent Events (SSE)** for real-time notifications

The bot acts as a **middleware** that bridges customer conversations in Zendesk Sunshine with support tickets in Zendesk, allowing agents to respond to customers through either platform.

---

## 🎯 System Overview

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Customer Browser                         │
│  (Chat Widget + WebSocket + SSE Notifications)              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ WebSocket (ws://)
                     │ API Requests (http://)
                     │ SSE Streams (text/event-stream)
                     ▼
┌─────────────────────────────────────────────────────────────┐
│          Django Application (Bot)                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Views (webhook handlers, API endpoints)              │   │
│  │ Consumers (WebSocket handlers)                       │   │
│  │ Cache (Redis for session & notification storage)     │   │
│  └──────────────────────────────────────────────────────┘   │
└────────┬────────────────────────────────────────────────────┘
         │
         ├──────────► Zendesk Sunshine Conversations API
         │            (Send/receive messages, escalate)
         │
         └──────────► Zendesk Support API
                      (Create tickets, update fields, webhooks)
```


---

## � Chat Workflows

### Others Option (Direct Escalation)

The "Others" category in App Related Issues provides direct agent escalation without intermediate troubleshooting steps.

**User Journey**:
```
User clicks "App Related Issues" 
    ↓
User clicks "Others"
    ↓
Message "Others" appended to chat
    ↓
Loading indicator "Please hang on..." displays
    ↓
Conversation initialized (if new)
    ↓
Escalation initiated with category = "Others"
    ↓
"Others" → "others" mapped for Zendesk custom field
    ↓
Escalation message: "Escalation Reason: Others"
                    "Category: App related issue"
    ↓
Agent joins the conversation
```

**Code Flow**:
1. `handleAppRelatedOptionClick("Others")` - Appends message, shows loading indicator
2. `createConversationAndEscalate(reason, category)` - Creates new conversation
3. `performEscalation(reason, category)` - Sends to `/api/chat/escalate` endpoint
4. Backend maps category and creates Zendesk ticket with custom field

**Key Features**:
- No text input required from user
- Direct connection to agent
- Custom field automatically set to "other" in Zendesk
- Loading indicator shows "Please hang on" with animated dots

### Data Flow

1. **Customer Message** → Chat Widget → WebSocket → Django View → Sunshine API
2. **Agent Response** → Sunshine Webhook → Django View → WebSocket → Chat Widget + SSE
3. **Escalation** → Chat Widget → Django View → Sunshine passControl → Zendesk Ticket Creation
4. **Agent Reply** → Zendesk Webhook → Django View → Sunshine API → Chat Widget + WebSocket

---

## 🛠 Technology Stack

### Backend
- **Framework**: Django 6.0
- **Real-time**: Django Channels 4.0 (WebSocket + Groups)
- **Message Broker**: Redis 7.1.0 (Channel Layer & Cache)
- **HTTP Client**: Requests 2.32.5
- **Authentication**: HTTP Basic Auth (Zendesk APIs)
- **Server**: Uvicorn 0.38.0 (ASGI)
- **Static Files**: WhiteNoise 6.11.0

### Frontend (Chat Widget)
- **Protocol**: WebSocket for bidirectional messaging
- **Notifications**: Server-Sent Events (SSE)
- **Media**: File upload & attachment display

### External Services
- **Zendesk Sunshine Conversations**: Message hub for all conversations
- **Zendesk Support**: Ticket management & agent workspace

---

## 🏗 Architecture Diagram

### Request-Response Flow

```
CUSTOMER SIDE                DJANGO BOT              ZENDESK ECOSYSTEM
─────────────                ──────────              ──────────────────

Chat Widget      ──POST──►  /api/chat/init          ──► Create User
                                                    ──► Create/Fetch Conversation
                            (Sunshine API v2)

Chat Widget      ──POST──►  /api/chat/send          ──► Post Message
                                                    ──► Sunshine API

Chat Widget      ──WS──►    ChatConsumer            ◄── WebSocket Group
                            (Channels)

Chat Widget      ──GET──►   /api/chat/messages      ◄── Fetch Message List
                                                    ◄── Sunshine API

Chat Widget      ──GET──►   /api/chat/full-history  ◄── Combined history
                                                    ◄── Sunshine + Zendesk

Chat Widget      ──POST──►  /api/chat/escalate      ──► Pass Control
                                                    ──► Create Ticket

Chat Widget      ──POST──►  /api/send-to-zendesk    ──► Upload Attachment
                                                    ──► Post File Message

Chat Widget      ──POST──►  /api/chat/viewing-status ─► Update cache
                                                    ─► Track user state

Chat Widget      ──SSE──►   /api/notifications/     ◄── Event stream
                            stream/<conv_id>        ◄── Unread badges


ZENDESK AGENT                DJANGO BOT              SUNSHINE/ZENDESK
─────────────                ──────────              ──────────────────

Sunshine Agent   ──Message──►  /hooks/sunshine/message  Process agent msgs
                                                        ──► Forward to WebSocket
                                                        ──► Update cache

Zendesk Agent    ──Ticket──►   /zendesk/webhook        Process ticket comments
Comment          Reply          (Notification)         ──► Map ticket to conversation
                                                        ──► Post to Sunshine
                                                        ──► Forward to WebSocket
```

---

## 🌟 Zendesk Sunshine Conversations

### What is Sunshine Conversations?

Zendesk Sunshine Conversations is a **unified messaging platform** that:
- Aggregates customer conversations from multiple channels (Chat, WhatsApp, Facebook, etc.)
- Provides a **single conversation interface** for support agents
- Offers **rich message support** (text, files, images, choices, actions)
- Enables **bot escalation** via Switchboard API
- Sends **webhooks** for conversation events

### Key Concepts

#### 1. **Apps**
- Each integration (bot, channel) is an "app"
- Identified by `SUNSHINE_APP_ID`
- Apps can send/receive messages via API

#### 2. **Users**
- Customers are identified as "users" in Sunshine
- Created with `externalId` (matches your user ID system)
- Can have multiple conversations
- **API**: `POST /v2/apps/{appId}/users`

#### 3. **Conversations**
- Persistent chat thread between user and business
- Type: `personal` (1:1) or `group`
- Participants include users and business agents
- **API**: `POST /v2/apps/{appId}/conversations`

#### 4. **Messages**
- Text, files, images, or interactive content
- Authors: `user`, `business`, or `bot`
- Sources: `whatsapp`, `web`, `zd:agentWorkspace`, etc.
- **API**: `POST /v2/apps/{appId}/conversations/{convId}/messages`

#### 5. **Switchboard**
- Controls which "app" (bot or agent) has active conversation
- **Pass Control**: Transfer from bot to agent
- **Release Control**: Agent ends session
- **Metadata**: Attach custom data to handoff
- **API**: `POST /v2/apps/{appId}/conversations/{convId}/passControl`

---

## 📡 API Documentation

### Authentication

All Sunshine APIs use **HTTP Basic Auth**:
```
Authorization: Basic <base64(API_KEY_ID:API_KEY_SECRET)>
```

Environment variables:
```
SUNSHINE_API_KEY_ID=your_key_id
SUNSHINE_API_KEY_SECRET=your_secret
SUNSHINE_API_BASE_URL=https://api.smooch.io
SUNSHINE_APP_ID=your_app_id
```

---

### 1. **Initialize Conversation**

**Endpoint**: `POST /api/chat/init`

**Purpose**: Create or fetch a user and conversation

**Request Body**:
```json
{
  "userId": "optional_external_id",
  "forceNew": false
}
```

**Response**:
```json
{
  "appUserId": "sunshine_user_id",
  "conversationId": "sunshine_conversation_id",
  "externalId": "external_user_id"
}
```

**What it does**:
1. Calls `POST /v2/apps/{appId}/users` to create user
2. If 409 (conflict), fetches existing user with `GET /v2/apps/{appId}/users/{externalId}`
3. Fetches existing conversations with `GET /v2/apps/{appId}/conversations?filter[userId]={userId}`
4. If no conversation exists, creates new with `POST /v2/apps/{appId}/conversations`

**Sunshine API Calls**:
- `POST /v2/apps/{appId}/users` - Create user
- `GET /v2/apps/{appId}/users/{externalId}` - Fetch user
- `GET /v2/apps/{appId}/conversations` - List conversations
- `POST /v2/apps/{appId}/conversations` - Create conversation

---

### 2. **Send Message to Sunshine**

**Endpoint**: `POST /api/chat/send`

**Purpose**: Send customer message to Sunshine

**Request Body**:
```json
{
  "appUserId": "sunshine_user_id",
  "conversationId": "conversation_id",
  "text": "Customer message text"
}
```

**Response**:
```json
{
  "status": "sent",
  "data": {
    "message": {
      "id": "msg_id",
      "text": "Customer message text",
      "author": {"type": "user", "userId": "user_id"},
      "received": "2024-01-22T10:30:00Z"
    }
  }
}
```

**What it does**:
1. Posts message to `POST /v2/apps/{appId}/conversations/{convId}/messages`
2. Saves to cache: `conversation_info_{convId}` (last message, timestamp, user)

**Sunshine API Calls**:
- `POST /v2/apps/{appId}/conversations/{convId}/messages` - Send message

---

### 3. **Get Conversation Messages**

**Endpoint**: `GET /api/chat/messages?conversationId={convId}`

**Purpose**: Fetch messages for a conversation from Sunshine

**Response**:
```json
{
  "messages": [
    {
      "id": "msg_id",
      "text": "Message text",
      "author": {
        "type": "user|business|bot",
        "displayName": "Agent Name"
      },
      "received": "2024-01-22T10:30:00Z",
      "content": {
        "type": "text|image|file",
        "choices": [],
        "actions": []
      }
    }
  ],
  "conversation": {
    "id": "conversation_id",
    "participants": [],
    "activeSwitchboardIntegration": {}
  }
}
```

**What it does**:
1. Fetches messages from `GET /v2/apps/{appId}/conversations/{convId}/messages`
2. Also fetches conversation metadata for participants

**Sunshine API Calls**:
- `GET /v2/apps/{appId}/conversations/{convId}/messages` - Fetch messages
- `GET /v2/apps/{appId}/conversations/{convId}` - Fetch conversation metadata

---

### 4. **Escalate to Agent**

**Endpoint**: `POST /api/chat/escalate`

**Purpose**: Transfer conversation from bot to live agent, creating Zendesk ticket

**Request Body**:
```json
{
  "conversationId": "conversation_id",
  "appUserId": "user_id",
  "reason": "User requested agent support",
  "appRelatedCategory": "Location Not Found or Inaccurate"
}
```

**Supported Categories**:
- `Location Not Found or Inaccurate`
- `Unable to Login`
- `My App is Not Responding`
- `Others`

**Response**:
```json
{
  "status": "escalated",
  "conversation_id": "conversation_id",
  "category": "location_not_found_or_inaccurate"
}
```

**What it does**:
1. Stores escalation metadata in cache (7-day timeout)
2. Posts escalation message to Sunshine: `Escalation Reason: {reason}\nCategory: {category}\n[Sunshine Conversation: {convId}]`
3. Calls `POST /v2/apps/{appId}/conversations/{convId}/passControl` to transfer control
4. Includes metadata:
   - `dataCapture.systemField.tags`: "escalated_from_bot"
   - `dataCapture.ticketField.{ZENDESK_CHAT_CONVERSATION_FIELD_ID}`: conversation_id
   - `dataCapture.ticketField.{APP_RELATED_SUB_CATEGORY}`: category_tag
5. Triggers Zendesk webhook which creates ticket

**Sunshine API Calls**:
- `POST /v2/apps/{appId}/conversations/{convId}/messages` - Post escalation message
- `POST /v2/apps/{appId}/conversations/{convId}/passControl` - Transfer to agent

**Zendesk Integration**:
- Creates ticket via **webhook** (agent workspace auto-creates on passControl)
- Metadata maps to Zendesk custom fields
- Conversation ID stored in ticket custom field for tracking

---

### 5. **Get Full Chat History**

**Endpoint**: `GET /api/chat/full-history?conversationId={convId}`

**Purpose**: Get complete message history from both Sunshine AND Zendesk

**Response**:
```json
{
  "messages": [
    {
      "id": "msg_id",
      "text": "Message text",
      "author": {"type": "user|agent|bot", "displayName": "Name"},
      "received": "2024-01-22T10:30:00Z",
      "messageClass": "user|agent|bot",
      "source": "sunshine|conversation_log",
      "attachments": []
    }
  ],
  "source": "combined",
  "ticket_id": "zendesk_ticket_id",
  "conversation_id": "conversation_id",
  "appUserId": "user_id"
}
```

**What it does**:
1. Fetches messages from Sunshine API
2. If conversation maps to ticket, fetches from Zendesk conversation_log
3. Deduplicates messages using fingerprints (author + timestamp + text)
4. Parses conversation_log events into message objects
5. Combines and sorts by received timestamp

**API Calls**:
- `GET /v2/apps/{appId}/conversations/{convId}/messages` - Sunshine messages
- `GET /v2/apps/{appId}/conversations/{convId}` - Get participant info
- `GET /api/v2/search.json?query=custom_field_{fieldId}:{convId}` - Find ticket
- `GET /api/v2/tickets/{ticketId}/conversation_log.json` - Zendesk history

**Deduplication Logic**:
```
Fingerprint = author_type:timestamp[:19]:text[:100].lower()
```

---

### 6. **Send File/Attachment**

**Endpoint**: `POST /api/send-to-zendesk`

**Purpose**: Upload file and send as attachment in conversation

**Request Type**: `multipart/form-data`

**Parameters**:
```
file: <binary file>
conversationId: conversation_id
appUserId: user_id
message: optional text message
```

**Response**:
```json
{
  "status": "ok"
}
```

**What it does**:
1. Posts file to `POST /v2/apps/{appId}/attachments?access=public` with `files={'source': file}`
2. Gets back `mediaUrl` from response
3. Posts file message to conversation with mediaUrl
4. If message text provided, posts separate text message

**Sunshine API Calls**:
- `POST /v2/apps/{appId}/attachments` - Upload file
- `POST /v2/apps/{appId}/conversations/{convId}/messages` - Post file message (x2)

**File Message Format**:
```json
{
  "author": {"type": "user", "userId": "user_id"},
  "content": {
    "type": "file",
    "mediaUrl": "https://api.smooch.io/...",
    "fileName": "document.pdf",
    "contentType": "application/pdf",
    "fileSize": 2048
  }
}
```

---

### 7. **Update Viewing Status**

**Endpoint**: `POST /api/chat/viewing-status`

**Purpose**: Track whether user is actively viewing the chat (for unread badges)

**Request Body**:
```json
{
  "conversationId": "conversation_id",
  "isViewing": true
}
```

**Response**:
```json
{
  "status": "updated",
  "conversationId": "conversation_id"
}
```

**What it does**:
1. Sets cache key `user_viewing_{convId}` to `True` (1-hour timeout)
2. Used by webhook to suppress notifications when user is actively reading

**Cache Operations**:
- `cache.set(f'user_viewing_{convId}', True, timeout=3600)`
- `cache.delete(f'user_viewing_{convId}')`

---

### 8. **Clear Unread Badge**

**Endpoint**: `POST /api/chat/clear-badge`

**Purpose**: Clear unread message count when user opens chat

**Request Body**:
```json
{
  "conversationId": "conversation_id"
}
```

**Response**:
```json
{
  "status": "cleared",
  "conversationId": "conversation_id"
}
```

**What it does**:
1. Deletes cache key `unread_{convId}`
2. Reset unread counter to 0

---

### 9. **Image Proxy**

**Endpoint**: `GET /api/image-proxy?url={encoded_url}`

**Purpose**: Proxy Zendesk/Sunshine images through bot for auth/CORS

**Allowed Domains**:
- `zendesk.com`
- `zdassets.com`
- `smooch.io`
- `zendesk-eu.com`

**What it does**:
1. Validates URL is from allowed domain
2. Attempts authentication with Sunshine JWT or Zendesk credentials
3. Streams image back to client

**Authentication Fallback Chain**:
- Sunshine API Key (Basic Auth)
- Sunshine JWT (Bearer token)
- Zendesk API Key (Basic Auth)

---

### 10. **Sunshine Webhook Handler**

**Endpoint**: `POST /hooks/sunshine/message`

**Purpose**: Receive webhooks from Zendesk Sunshine for conversation events

**Security**: HMAC SHA256 signature verification using `X-Hub-Signature` header

**Supported Triggers**:
- `conversation:message` - New message from user or agent
- `switchboard:passControl` - Agent took control of conversation
- `switchboard:releaseControl` - Agent ended session
- `switchboard:acceptControl` - Agent accepted transfer
- `participant:join` - Agent/user joined conversation
- `participant:leave` - Agent/user left conversation
- `conversation:read` - Messages marked as read
- `user:typing` - Agent is typing indicator

**Event Processing**:

#### conversation:message
```python
# Check if message is from agent (author.type == "business")
# If yes:
#   1. Forward to WebSocket: forward_agent_message_to_websocket()
#   2. Check if user is viewing (cache.get('user_viewing_{convId}'))
#   3. If NOT viewing, increment unread counter and send notification
#   4. Skip system messages and conversation log entries

# Check if message is from AnswerBot
# If yes:
#   1. Extract category from message text
#   2. Create Zendesk ticket
#   3. Store conversation-to-ticket mapping
```

#### switchboard:passControl
```python
# Extract metadata from event
# Find ticket_id from metadata.dataCapture.ticketField.id
# Store mapping: conversation_id <-> ticket_id (7-day cache)
# If category exists, update ticket custom field
# Mark ticket as 'active' in cache
```

#### switchboard:releaseControl
```python
# Check if ticket status is 'solved'
# If yes, post message: "The agent has ended the session"
# Clear user_viewing status
```

#### participant:join / participant:leave
```python
# Post system message: "{agentName} has joined/left the conversation"
```

#### user:typing
```python
# Forward to WebSocket: agent_typing event
```

---

### 11. **Zendesk Webhook Handler**

**Endpoint**: `POST /zendesk/webhook`

**Purpose**: Receive webhooks from Zendesk when agents reply to tickets

**Supported Formats**:
1. **Notification Format** (webhook API v3):
   ```json
   {
     "event": {
       "type": "ticket.comment_added",
       "ticket": {
         "id": 123,
         "custom_fields": [{"id": 123, "value": "conversation_id"}]
       },
       "comment": {
         "body": "Agent reply text",
         "author": {"is_staff": true, "name": "Agent Name"}
       }
     }
   }
   ```

2. **Ticket Format** (older):
   ```json
   {
     "ticket": {...},
     "comment": {"body": "...", "author": {...}}
   }
   ```

**Processing Steps**:
1. Extract ticket_id and comment_body
2. Resolve conversation_id from:
   - Cache: `ticket_{ticketId}`
   - Ticket custom field: `ZENDESK_CHAT_CONVERSATION_FIELD_ID`
   - Ticket description: `[Sunshine Conversation: {convId}]` regex
3. Post comment to Sunshine: `POST /v2/apps/{appId}/conversations/{convId}/messages`
4. Forward to WebSocket
5. Filter out:
   - Non-agent/admin comments (user comments ignored)
   - Empty comments
   - Conversation log entries
   - System messages

**Response**:
```json
{
  "status": "forwarded",
  "ticket_id": "123",
  "conversation_id": "conversation_id",
  "agent_name": "Agent Name"
}
```

---

## 🔌 WebSocket Implementation

### Purpose
Real-time bidirectional messaging between browser and server

### Protocol
**URL**: `wss://your-domain/ws/chat/{conversation_id}/`

**Handler**: Django Channels `ChatConsumer` (async WebSocket consumer)

### Zendesk WebSocket Connection Flow

The complete flow from Zendesk webhook to WebSocket connection includes signature verification and secure handshake:

#### Step 1: Zendesk Sends Webhook with Signature
```
Zendesk Sunshine Server
    ↓
POST /hooks/sunshine/message
Headers:
  - X-Hub-Signature: sha256=abcd1234...
  - Content-Type: application/json
Body: {"trigger": "conversation:message", "data": {...}}
```

#### Step 2: Backend Verifies Signature
```python
# In views.py - webhook_handler()

import hmac
import hashlib
import base64

def verify_webhook_signature(request):
    """
    Verify Zendesk Sunshine webhook signature using HMAC-SHA256
    
    Security: Ensures webhook is from Zendesk, not spoofed
    """
    # 1. Get signature from header
    signature_header = request.headers.get('X-Hub-Signature', '')
    if not signature_header:
        return False
    
    # 2. Extract algorithm and signature value
    try:
        algo, signature = signature_header.split('=')
        if algo != 'sha256':
            return False
    except ValueError:
        return False
    
    # 3. Get webhook secret from environment
    webhook_secret = os.getenv('SUNSHINE_WEBHOOK_SIGNING_SECRET')
    if not webhook_secret:
        logger.error("SUNSHINE_WEBHOOK_SIGNING_SECRET not configured")
        return False
    
    # 4. Compute expected signature
    payload = request.body  # Raw bytes
    expected_signature = hmac.new(
        webhook_secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    # 5. Compare signatures (constant-time comparison to prevent timing attacks)
    if not hmac.compare_digest(signature, expected_signature):
        logger.error(f"Invalid signature: {signature} != {expected_signature}")
        return False
    
    logger.info("✅ Webhook signature verified")
    return True

@csrf_exempt
def sunshine_webhook_handler(request):
    """Handle Zendesk Sunshine webhooks"""
    
    # STEP 1: Verify signature
    if not verify_webhook_signature(request):
        logger.error("❌ Signature verification failed")
        return JsonResponse({"error": "Invalid signature"}, status=401)
    
    # STEP 2: Parse webhook body
    try:
        data = json.loads(request.body)
        trigger_type = data.get('trigger')
        conversation_id = data.get('data', {}).get('conversationId')
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    
    # STEP 3: Process event
    if trigger_type == 'conversation:message':
        logger.info(f"📨 New message in conversation: {conversation_id}")
        process_message_event(data)
    
    # STEP 4: Return success to Zendesk
    return JsonResponse({"status": "received", "conversationId": conversation_id})
```

**Signature Verification Algorithm**:
```
1. Get X-Hub-Signature header: "sha256=abc123..."
2. Extract signature: abc123...
3. Compute HMAC-SHA256(webhook_secret, request_body)
4. Compare: constant_time_compare(signature, computed_hash)
5. If equal → Webhook is from Zendesk ✅
6. If different → Webhook is spoofed ❌
```

#### Step 3: Extract Conversation ID
```python
# From verified webhook payload
def process_webhook_event(data):
    trigger = data.get('trigger')
    conversation_id = data.get('data', {}).get('conversationId')
    app_user_id = data.get('data', {}).get('author', {}).get('userId')
    message_text = data.get('data', {}).get('content', {}).get('text', '')
    
    logger.info(f"Processing event: {trigger}")
    logger.info(f"  Conversation: {conversation_id}")
    logger.info(f"  User: {app_user_id}")
    logger.info(f"  Message: {message_text[:50]}...")
    
    return {
        'conversation_id': conversation_id,
        'user_id': app_user_id,
        'trigger': trigger
    }
```

#### Step 4: Establish WebSocket Connection
```javascript
// client-side (chat-widget.js)

function connectToWebSocket(conversationId) {
    // 1. Build WebSocket URL from conversation ID
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.host;
    const wsUrl = `${protocol}://${host}/ws/chat/${conversationId}/`;
    
    logger.info(`🔌 Connecting to WebSocket: ${wsUrl}`);
    
    // 2. Create WebSocket connection
    try {
        sunshineSocket = new WebSocket(wsUrl);
        
        sunshineSocket.onopen = function(event) {
            logger.info(`✅ WebSocket connected: ${conversationId}`);
            isWebSocketConnected = true;
            
            // 3. Send initial ping to verify connection
            sunshineSocket.send(JSON.stringify({
                type: 'ping',
                timestamp: Date.now(),
                conversationId: conversationId
            }));
        };
        
        sunshineSocket.onmessage = function(event) {
            const message = JSON.parse(event.data);
            handleWebSocketMessage(message);
        };
        
        sunshineSocket.onerror = function(error) {
            logger.error(`❌ WebSocket error: ${error.message}`);
            isWebSocketConnected = false;
        };
        
        sunshineSocket.onclose = function(event) {
            logger.info(`🔌 WebSocket closed: code=${event.code}, reason=${event.reason}`);
            isWebSocketConnected = false;
            // Attempt reconnection with exponential backoff
        };
        
    } catch (error) {
        logger.error(`WebSocket creation error: ${error.message}`);
    }
}
```

#### Step 5: Server Accepts Connection
```python
# bot_app/consumers.py

class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time chat messaging."""
    
    async def connect(self):
        """
        Handle WebSocket connection from client.
        
        Steps:
        1. Extract conversation_id from URL
        2. Accept connection
        3. Join channel group
        4. Send welcome message
        5. Start keepalive heartbeat
        """
        try:
            # STEP 1: Extract conversation ID from URL route
            # URL pattern: /ws/chat/{conversation_id}/
            self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
            self.room_group_name = f'chat_{self.conversation_id}'
            self.connected = True
            
            logger.info(f"🔗 WebSocket connecting: conversation_id={self.conversation_id}")
            
            # STEP 2: Accept WebSocket connection
            await self.accept()
            logger.info(f"✅ WebSocket ACCEPTED: {self.conversation_id}")
            
            # STEP 3: Join channel layer group
            # (enables broadcasting to all clients in this conversation)
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            logger.info(f"✅ Joined group: {self.room_group_name}")
            
            # STEP 4: Send welcome message to client
            await self.send(text_data=json.dumps({
                'type': 'connection_established',
                'message': f'Connected to conversation {self.conversation_id}',
                'conversation_id': self.conversation_id,
                'group_name': self.room_group_name
            }))
            logger.info(f"✅ Sent welcome message")
            
            # STEP 5: Start keepalive heartbeat task
            self.keepalive_task = asyncio.create_task(self.send_keepalive())
            logger.info(f"✅ Started keepalive task")
            
        except Exception as e:
            logger.error(f"Connection error: {e}", exc_info=True)
            try:
                await self.accept()
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': str(e)
                }))
            except Exception:
                pass
```

#### Step 6: Send and Receive Messages
```python
# When Zendesk webhook arrives with agent message

def forward_agent_message_to_websocket(conversation_id, message_data):
    """
    Forward agent message from Zendesk to all WebSocket clients.
    
    Flow:
    1. Webhook received (already signature-verified)
    2. Extract message data
    3. Format for WebSocket
    4. Broadcast to all clients in conversation group
    """
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    
    channel_layer = get_channel_layer()
    group_name = f'chat_{conversation_id}'
    
    # Format message for WebSocket
    websocket_message = {
        'type': 'agent_message',  # Matches handler method name
        'payload': {
            'id': message_data.get('id'),
            'author': {
                'type': 'business',
                'displayName': message_data.get('author', {}).get('displayName'),
                'role': 'agent'
            },
            'content': {
                'type': 'text',
                'text': message_data.get('text')
            },
            'received': message_data.get('received'),  # Zendesk timestamp
            'conversationId': conversation_id
        }
    }
    
    # Send to channel group
    # This calls send_webhook_message() on all consumers in the group
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            'type': 'send_webhook_message',  # Calls send_webhook_message handler
            'message': websocket_message
        }
    )
    
    logger.info(f"📤 Sent agent message to {group_name}")
```

#### Step 7: Client Receives Real-Time Message
```javascript
// Continued from connectToWebSocket()

function handleWebSocketMessage(message) {
    const messageType = message.type;
    
    logger.info(`📥 WebSocket message received: ${messageType}`);
    
    switch(messageType) {
        case 'connection_established':
            logger.info(`✅ ${message.message}`);
            isWebSocketConnected = true;
            break;
        
        case 'agent_message':
            // Agent sent a message - display it immediately
            logger.info(`Agent message: ${message.payload.content.text}`);
            displayMessage(message.payload);
            removeLoadingIndicator();
            break;
        
        case 'pong':
            // Server acknowledged our ping
            logger.debug(`Server pong received`);
            break;
        
        case 'keepalive':
            // Server heartbeat - connection still alive
            logger.debug(`Server keepalive received`);
            break;
        
        case 'error':
            logger.error(`Server error: ${message.message}`);
            appendMessage(message.message, 'system-message');
            break;
        
        default:
            logger.warning(`Unknown message type: ${messageType}`);
    }
}
```

#### Complete Connection Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                    ZENDESK SUNSHINE SERVER                   │
│                    (Agent sends message)                      │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       │ POST /hooks/sunshine/message
                       │ Headers: X-Hub-Signature: sha256=...
                       │ Body: {trigger, data, ...}
                       ▼
┌──────────────────────────────────────────────────────────────┐
│              DJANGO BACKEND WEBHOOK HANDLER                  │
│                                                              │
│  1. Verify signature (HMAC-SHA256)                          │
│  2. Extract conversation_id from payload                    │
│  3. Parse message data                                      │
│  4. Call forward_agent_message_to_websocket()              │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       │ channel_layer.group_send()
                       │ Group: chat_{conversation_id}
                       ▼
┌──────────────────────────────────────────────────────────────┐
│         DJANGO CHANNELS - CHAT CONSUMER                      │
│                                                              │
│  send_webhook_message() handler triggered                  │
│  {type: 'agent_message', payload: {...}}                   │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       │ WebSocket frame
                       │ (real-time, instant delivery)
                       ▼
┌──────────────────────────────────────────────────────────────┐
│              BROWSER - CHAT WIDGET                           │
│                                                              │
│  WebSocket.onmessage() triggered                           │
│  Display agent message in chat bubble                       │
│  Remove loading indicator                                   │
└──────────────────────────────────────────────────────────────┘
```

### Security Checklist

✅ **Signature Verification**
- All Zendesk webhooks must be signature-verified
- Use HMAC-SHA256 with webhook secret
- Compare signatures using constant-time comparison (`hmac.compare_digest`)
- Reject unsigned or invalid webhooks (return 401)

✅ **WebSocket Security**
- Use WSS (WebSocket Secure) in production (wss://, not ws://)
- Verify conversation_id is valid (prevent arbitrary conversation access)
- Validate all client messages before processing
- Implement message size limits
- Add rate limiting per conversation

✅ **Authentication**
- Conversation must be created via authenticated `/api/chat/init` first
- WebSocket URL includes conversation_id (acts as weak authentication)
- Consider adding JWT token for stronger security

✅ **Data Protection**
- All messages transmitted over WSS (encrypted in transit)
- Cache stores message metadata only (no sensitive data)
- Timestamp from Zendesk prevents tampering

---

### Connection Flow

```
1. Browser connects: ws://localhost:8000/ws/chat/{conversation_id}/
2. ChatConsumer.connect() triggered
   - Extract conversation_id from URL
   - Join channel layer group: f'chat_{conversation_id}'
   - Accept connection
   - Send welcome message
   - Start keepalive task (ping every 25 seconds)
3. WebSocket connection established
```

### Message Types

#### 1. **ping/pong** (Heartbeat)
Client sends periodically to keep connection alive:
```json
{
  "type": "ping",
  "timestamp": 1234567890
}
```

Server responds:
```json
{
  "type": "pong",
  "timestamp": 1234567890,
  "conversation_id": "conv_id"
}
```

#### 2. **echo** (Test)
Client:
```json
{
  "type": "echo",
  "message": "test message"
}
```

Server:
```json
{
  "type": "echo_response",
  "message": "test message",
  "received_at": 1234567890,
  "conversation_id": "conv_id"
}
```

#### 3. **agent_message** (From Webhook)
Sent when Sunshine webhook receives agent message:
```json
{
  "type": "agent_message",
  "payload": {
    "id": "msg_id",
    "author": {
      "type": "business",
      "displayName": "Agent Name",
      "role": "agent"
    },
    "content": {
      "type": "text",
      "text": "Agent response"
    },
    "received": "2024-01-22T10:30:00Z",
    "source": "zendesk",
    "conversationId": "conv_id",
    "choices": [],
    "actions": []
  }
}
```

**Timestamp Details**:
- `received` field contains **ISO 8601 timestamp** from Zendesk Sunshine API
- This is the actual message received time from Zendesk, NOT server-generated
- Frontend uses this timestamp to create daily message separators (one per calendar day)
- If `received` is null/missing, no timestamp separator is shown
- **No fallback to server time**: Ensures consistency across all clients and page refreshes
- Used for both real-time messages (WebSocket) and historical messages (when reopening chat)

#### 4. **agent_typing** (Typing Indicator)
When agent starts typing:
```json
{
  "type": "agent_typing",
  "payload": {
    "conversationId": "conv_id",
    "isTyping": true,
    "agentName": "Agent Name"
  }
}
```

#### 5. **keepalive** (Server -> Client)
Sent every 25 seconds:
```json
{
  "type": "keepalive",
  "timestamp": 1234567890
}
```

#### 6. **connection_established** (Server -> Client)
On successful connect:
```json
{
  "type": "connection_established",
  "message": "Connected to conversation conv_id",
  "conversation_id": "conv_id",
  "group_name": "chat_conv_id"
}
```

### Channel Layer Groups

**Group Name**: `chat_{conversation_id}`

**Broadcasting Method**: `async_to_sync(channel_layer.group_send)(group_name, {...})`

**Handler Method**: `send_webhook_message(event)` on consumer

### Code Structure

```python
class ChatConsumer(AsyncWebsocketConsumer):
    
    async def connect(self):
        # 1. Extract conversation_id from URL route
        # 2. Create group_name = f'chat_{conversation_id}'
        # 3. Accept connection
        # 4. Join group
        # 5. Send welcome message
        # 6. Start keepalive task
    
    async def disconnect(self, close_code):
        # 1. Mark as disconnected
        # 2. Cancel keepalive task
        # 3. Leave group
    
    async def receive(self, text_data):
        # Handle incoming messages from client
        # Support: ping, pong, echo, test_agent_message
    
    async def send_webhook_message(self, event):
        # Handler for group_send messages
        # Receives: {'type': 'send_webhook_message', 'message': {...}}
        # Sends to client via WebSocket
    
    async def send_keepalive(self):
        # Task: Sends keepalive every 25 seconds
```

### Django Integration

In `views.py`, when webhook receives agent message:

```python
def forward_agent_message_to_websocket(conversation_id, message_text, agent_name):
    channel_layer = get_channel_layer()
    group_name = f'chat_{conversation_id}'
    
    websocket_message = {
        'type': 'agent_message',
        'payload': {...}
    }
    
    # Queue message to all clients in group
    async_to_sync(channel_layer.group_send)(
        group_name, 
        {'type': 'send_webhook_message', 'message': websocket_message}
    )
```

### Redis Channel Layer Configuration

```python
# settings.py
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [os.environ.get("REDIS_URL")],  # redis://localhost:6379
        },
    },
}
```

**Purpose**: Enables group messaging across multiple server instances

---

## � Variables Reference

This section explains all key identifiers used throughout the system, where they come from, and how to get them.

### Conversation ID

**Names/Aliases**: `conversation_id`, `conversationId`, `convId`

**What it is**:
- Unique identifier for a customer-bot conversation in Zendesk Sunshine Conversations
- Set by Zendesk when conversation is created
- Persists across agent transfers and multiple sessions
- Format: UUID string (e.g., `550e8400-e29b-41d4-a716-446655440000`)

**How to get it**:

**Option 1: From `POST /api/chat/init` response** ✅ Recommended
```python
# Client sends POST /api/chat/init
response = {
    "appUserId": "sunshine_user_id",
    "conversationId": "550e8400-e29b-41d4-a716-446655440000",  # ← HERE
    "externalId": "your_external_id"
}

# Store this in browser localStorage/sessionStorage
localStorage.setItem('conversationId', response.conversationId);
```

**Option 2: From Zendesk Sunshine API**
```python
# Backend can fetch existing conversations
GET /v2/apps/{appId}/conversations?filter[userId]={userId}

# Response includes:
{
  "conversations": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",  # ← conversation_id
      "participants": [...],
      "lastUpdatedAt": "2024-01-22T10:30:00Z"
    }
  ]
}
```

**Option 3: From Zendesk Webhook**
```python
# When agent replies via Zendesk ticket
# Ticket contains mapping to conversation_id in custom field

ticket = {
    "id": 123,
    "custom_fields": [
        {
            "id": ZENDESK_CHAT_CONVERSATION_FIELD_ID,
            "value": "550e8400-e29b-41d4-a716-446655440000"  # ← conversation_id
        }
    ]
}
```

**Where it's used**:
- WebSocket URL: `wss://domain/ws/chat/{conversation_id}/`
- All Sunshine API calls: `/v2/apps/{appId}/conversations/{conversation_id}/...`
- Cache keys: `notification_{conversation_id}`, `unread_{conversation_id}`
- Ticket custom field mapping for tracking

---

### User Identifiers

There are **three different user IDs** - understanding the distinction is critical:

#### 1. `externalId` / `userId`

**What it is**:
- Your internal user ID from your system
- Identifies who the customer is in YOUR application
- Example: username, account ID, email, etc.
- Non-sensitive, can be a display name

**How to get it**:
- From your application's authentication system
- Usually the currently logged-in user's ID
- Pass it to `/api/chat/init` when initializing conversation
- Example:
  ```python
  POST /api/chat/init
  {
    "userId": "user_12345",  # ← YOUR internal ID
    "forceNew": false
  }
  ```

**What happens**:
1. Backend stores `externalId: "user_12345"` in Sunshine
2. Used to fetch existing conversations for this user
3. Maps your system's user to Sunshine user

**Where it's used**:
- Retrieving user's conversation history
- Linking conversations back to your database records
- Unread notification tracking per user

---

#### 2. `appUserId` / `sunshine_user_id`

**What it is**:
- Zendesk Sunshine's internal user ID
- Automatically generated by Zendesk when user is first created
- Different from your `externalId`
- Only relevant in Sunshine API calls

**How to get it**:

**Option A: From init response**
```python
POST /api/chat/init
Response: {
    "appUserId": "5e8f8400-e29b-41d4-a716-446655440000",  # ← Sunshine user ID
    "conversationId": "550e8400-e29b-41d4-a716-446655440000",
    "externalId": "user_12345"
}
```

**Option B: From Sunshine API**
```python
# Backend creates user and gets back appUserId
POST /v2/apps/{appId}/users
{
  "externalId": "user_12345"
}

Response: {
    "user": {
        "id": "5e8f8400-e29b-41d4-a716-446655440000",  # ← appUserId
        "externalId": "user_12345",
        "conversationStarted": false,
        "lastSeenAt": null
    }
}
```

**Relationship**:
```
YOUR SYSTEM          ZENDESK SUNSHINE
─────────────        ────────────────
externalId ◄────────► appUserId
user_12345 ◄────────► 5e8f8400-e29b...
```

**Where it's used**:
- Sunshine API calls that fetch user details
- Creating conversations for specific users
- Updating user metadata

---

#### 3. How to Store These in Frontend

```javascript
// After successful init
const initResponse = {
    "appUserId": "5e8f8400-e29b-41d4-a716-446655440000",
    "conversationId": "550e8400-e29b-41d4-a716-446655440000",
    "externalId": "user_12345"
};

// Store in browser
sessionStorage.setItem('appUserId', initResponse.appUserId);
sessionStorage.setItem('conversationId', initResponse.conversationId);
sessionStorage.setItem('externalId', initResponse.externalId);

// Use in subsequent API calls
const conversationId = sessionStorage.getItem('conversationId');
fetch(`/api/chat/send`, {
    method: 'POST',
    body: JSON.stringify({
        appUserId: sessionStorage.getItem('appUserId'),
        conversationId: conversationId,
        text: "User message"
    })
});

// Use in WebSocket connection
const wsUrl = `wss://${host}/ws/chat/${conversationId}/`;
```

---

### App ID

**Names/Aliases**: `appId`, `SUNSHINE_APP_ID`, `app_id`

**What it is**:
- Zendesk Sunshine's identification for your bot instance
- Given by Zendesk when you set up Sunshine Conversations
- Unique across all Zendesk organizations
- Format: UUID string

**How to get it**:
1. Log in to **Zendesk Admin Panel**
2. Navigate to **Channels > Smooth/Smooch** (or Sunshine Conversations)
3. Copy the **App ID** from settings
4. Alternatively, check your environment variables:
   ```bash
   echo $SUNSHINE_APP_ID
   ```

**Example**:
```
App ID: 550e8400-e29b-41d4-a716-446655440000
```

**Where it's used**:
- Every Sunshine API call: `GET /v2/apps/{appId}/...`
- Environment variable: `SUNSHINE_APP_ID=...`
- Never sent to frontend (backend-only)

**In code**:
```python
# bot_app/views.py
app_id = os.getenv('SUNSHINE_APP_ID')

# All Sunshine API calls
response = requests.get(
    f'https://api.smooch.io/v2/apps/{app_id}/conversations/{conversation_id}/messages',
    auth=(api_key_id, api_key_secret)
)
```

---

### Zendesk IDs

#### Ticket ID

**Names/Aliases**: `ticketId`, `ticket_id`, `zendesk_ticket_id`

**What it is**:
- Zendesk Support's ticket ID
- Numeric identifier (e.g., `123`, `456789`)
- Created when customer escalates from chat
- Links a Sunshine conversation to a support ticket

**How to get it**:

**Option 1: From Zendesk Webhook**
```python
POST /zendesk/webhook
{
  "event": {
    "ticket": {
      "id": 123456,  # ← ticket_id
      "status": "open",
      "created_at": "2024-01-22T10:30:00Z"
    }
  }
}
```

**Option 2: From Backend Search**
```python
# Backend searches for ticket by conversation_id
response = requests.get(
    f'https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/search.json',
    auth=(email, api_token),
    params={
        'query': f'custom_field_id:{ZENDESK_CHAT_CONVERSATION_FIELD_ID} {conversation_id}'
    }
)

ticket_id = response['results'][0]['id']  # ← ticket_id
```

**Mapping Flow**:
```
Sunshine Conversation                 Zendesk Ticket
─────────────────────                 ──────────────
550e8400-e29b...          ◄────────►  123456
(conversation_id)                     (ticket_id)

Stored in mapping:
cache.set(f'ticket_{ticket_id}', conversation_id)
cache.set(f'conversation_{conversation_id}', ticket_id)
```

**Where it's used**:
- Finding associated Zendesk ticket when agent replies
- Pulling full conversation history from Zendesk
- Creating CSAT ticket fields
- Tracking escalations

---

### Webhook Security

#### Webhook Secret

**Names/Aliases**: `SUNSHINE_WEBHOOK_SIGNING_SECRET`, `webhook_secret`, `signing_secret`

**What it is**:
- Secret key provided by Zendesk for webhook signature verification
- Used to prove webhook is actually from Zendesk
- Prevents attackers from spoofing webhooks

**How to get it**:
1. Log in to **Zendesk Admin Panel**
2. Navigate to **Channels > Integrations > Webhooks**
3. Find your bot's webhook configuration
4. Copy the **Signing Secret**
5. Set as environment variable:
   ```bash
   export SUNSHINE_WEBHOOK_SIGNING_SECRET="your_secret_here"
   ```

**Example**:
```
Signing Secret: abcdef123456789xyz
```

**How it's used** (Signature Verification):
```python
# bot_app/views.py
import hmac
import hashlib

def verify_webhook_signature(request):
    """Verify Zendesk webhook is authentic"""
    
    # 1. Get signature from header
    signature_header = request.headers.get('X-Hub-Signature', '')
    # Format: "sha256=abc123..."
    
    # 2. Get webhook secret
    webhook_secret = os.getenv('SUNSHINE_WEBHOOK_SIGNING_SECRET')
    
    # 3. Compute expected signature
    algo, signature = signature_header.split('=')
    expected = hmac.new(
        webhook_secret.encode(),
        request.body,
        hashlib.sha256
    ).hexdigest()
    
    # 4. Compare (constant-time to prevent timing attacks)
    if not hmac.compare_digest(signature, expected):
        return False  # ❌ Invalid signature
    
    return True  # ✅ Valid signature
```

---

### Field IDs

#### ZENDESK_CHAT_CONVERSATION_FIELD_ID

**What it is**:
- Zendesk ticket custom field ID for storing `conversation_id`
- Numeric ID (e.g., `12345678`)
- Allows mapping tickets back to Sunshine conversations

**How to get it**:
1. In **Zendesk Admin Panel**, go to **Manage > Tickets > Fields**
2. Find or create a custom field named "Chat Conversation ID"
3. Field type: **Text**
4. In field settings, note the **Field ID** number
5. Set environment variable:
   ```bash
   export ZENDESK_CHAT_CONVERSATION_FIELD_ID=12345678
   ```

**Example mapping**:
```
Field Name: Chat Conversation ID
Field ID: 12345678
Field Value: 550e8400-e29b-41d4-a716-446655440000  (conversation_id)
```

**How it's used**:
```python
# When escalating, store conversation_id in ticket field
ticket_custom_fields = [
    {
        "id": ZENDESK_CHAT_CONVERSATION_FIELD_ID,  # 12345678
        "value": conversation_id  # 550e8400-e29b...
    }
]
```

---

#### APP_RELATED_SUB_CATEGORY

**What it is**:
- Zendesk ticket custom field ID for category/reason of escalation
- Numeric ID (e.g., `87654321`)
- Stores category: "location_not_found_or_inaccurate", "unable_to_login", etc.

**How to get it**:
1. In **Zendesk Admin Panel**, go to **Manage > Tickets > Fields**
2. Find or create custom field named "App Related Sub Category"
3. Field type: **Dropdown** (recommended) or **Text**
4. Note the **Field ID**
5. Set environment variable:
   ```bash
   export APP_RELATED_SUB_CATEGORY=87654321
   ```

**Example mapping**:
```
Field Name: App Related Sub Category
Field ID: 87654321
Field Values:
  - location_not_found_or_inaccurate
  - unable_to_login
  - my_app_is_not_responding
  - others
```

**How it's used**:
```python
# When escalating, store category in ticket field
category_mapping = {
    "Location Not Found or Inaccurate": "location_not_found_or_inaccurate",
    "Unable to Login": "unable_to_login",
    "My App is Not Responding": "my_app_is_not_responding",
    "Others": "others"
}

ticket_custom_fields = [
    {
        "id": APP_RELATED_SUB_CATEGORY,  # 87654321
        "value": category_mapping[selected_category]
    }
]
```

---

### Channel Groups

#### Room Group Name

**Names/Aliases**: `group_name`, `room_group_name`, `channel_group`, `chat_{conversation_id}`

**What it is**:
- Django Channels group identifier for WebSocket broadcasting
- Specific to one conversation
- Allows multiple clients to receive real-time updates for same conversation
- Format: `chat_{conversation_id}`

**How it's created?**:
```python
# In ChatConsumer.connect()
conversation_id = self.scope['url_route']['kwargs']['conversation_id']
self.room_group_name = f'chat_{conversation_id}'

# Join the group
await self.channel_layer.group_add(
    self.room_group_name,  # "chat_550e8400-e29b..."
    self.channel_name      # Unique consumer instance ID
)
```

**Example**:
```
Conversation ID: 550e8400-e29b-41d4-a716-446655440000
Room Group Name: chat_550e8400-e29b-41d4-a716-446655440000
```

**How it's used**:
When agent sends message in Zendesk, backend broadcasts to all clients in conversation:
```python
# When webhook receives agent message
channel_layer = get_channel_layer()
group_name = f'chat_{conversation_id}'

# Send to all consumers in this group
async_to_sync(channel_layer.group_send)(
    group_name,  # "chat_550e8400-e29b..."
    {
        'type': 'send_webhook_message',  # Calls send_webhook_message() handler
        'message': agent_message
    }
)
```

**Multiple clients scenario**:
```
Customer has chat open in 2 browser tabs
            │
            ├─ Tab 1 → WebSocket client 1 → consumer 1
            └─ Tab 2 → WebSocket client 2 → consumer 2
            
Both join same group: chat_550e8400-e29b...

When agent sends message:
    Agent message → Zendesk webhook → Backend
                                       │
                                       └─ broadcast to chat_550e8400-e29b...
                                          │
                                          ├─ consumer 1 → WebSocket → Tab 1
                                          └─ consumer 2 → WebSocket → Tab 2

Result: Both tabs show agent message instantly
```

---

### Quick Reference Table

| Variable | Example | Where to Get | Backend/Frontend |
|----------|---------|--------------|-----------------|
| `conversationId` | `550e8400...` | POST `/api/chat/init` response | Both |
| `appUserId` | `5e8f8400...` | POST `/api/chat/init` response | Both |
| `externalId` | `user_12345` | Your auth system | Both |
| `appId` | `550e8400...` | Zendesk admin panel | Backend only |
| `ticketId` | `123456` | Zendesk webhook | Backend only |
| `webhook_secret` | `abcdef123...` | Zendesk admin panel | Backend only |
| `ZENDESK_CHAT_CONVERSATION_FIELD_ID` | `12345678` | Zendesk admin panel | Backend only |
| `APP_RELATED_SUB_CATEGORY` | `87654321` | Zendesk admin panel | Backend only |
| `room_group_name` | `chat_550e8400...` | Generated from conversationId | Backend only |

---

## �📧 CSAT & Attachments

### CSAT (Customer Satisfaction)

The system supports CSAT through Zendesk-controlled surveys delivered as interactive messages:

#### Integration Points:
1. **Zendesk Ticket Custom Fields**
   - `APP_RELATED_SUB_CATEGORY` - Category feedback
   - `ZENDESK_CHAT_CONVERSATION_FIELD_ID` - Conversation mapping

2. **Message Choices** (Interactive)
   - Sunshine messages can include `choices` array
   - Used for CSAT rating options
   - Example:
     ```json
     {
       "type": "text",
       "text": "How satisfied are you?",
       "choices": [
         {"label": "Very Satisfied", "value": "5"},
         {"label": "Satisfied", "value": "4"},
         {"label": "Neutral", "value": "3"}
       ]
     }
     ```

3. **Sunshine Actions**
   - Messages can include `actions` array
   - Triggered by user interaction
   - Can be mapped to feedback submission

#### Display Order (Fixed)
When agent sends CSAT survey with choices/actions, the display order is:
1. **"Messaging session ended"** announcement (gray, centered)
2. **CSAT Question + Rating Buttons** in single bubble (question text + interactive choices)

This order is consistent whether:
- Chat is open (WebSocket, real-time)
- Chat is closed/reopened (message history)

**Implementation**:
- Text message is NOT displayed separately if it has choices/actions
- `appendChoicesMessage()` handles displaying question + buttons together
- Prevents duplicate question text and maintains clean UI

#### CSAT Webview Link Integration:
The system supports **Zendesk CSAT surveys** delivered as webview iframes:

1. **Webview Message Structure**
   - Messages can include `choices` with `type: "webview"`
   - Each choice contains a `uri` pointing to the survey
   - Example:
     ```json
     {
       "type": "text",
       "text": "Please rate your experience",
       "choices": [
         {
           "type": "webview",
           "label": "Take Survey",
           "uri": "https://zendesk.com/apps/csat/survey?id=abc123&token=xyz"
         }
       ]
     }
     ```

2. **Webview Rendering**
   - Survey displays in an embedded **iframe** (600px height)
   - Loads with full permissions: `geolocation, microphone, camera, payment, usb, magnetometer, gyroscope, accelerometer`
   - Renders in chat bubble below message choices
   - HTTPS required for Zendesk survey URLs

3. **Typical CSAT Survey URI Format**
   ```
   https://zendesk.com/apps/csat/survey?conversationId={id}&contactId={contact_id}&token={auth_token}
   ```

4. **Frontend Implementation**
   - Chat widget automatically detects webview choices
   - When webview link clicked, `appendWebviewSurvey()` embeds iframe
   - Survey runs in isolated iframe context (security boundary)
   - User responses submitted directly to Zendesk CSAT backend
   - No bot-side response handling required

5. **Configuration in Zendesk**
   - CSAT survey URI generated in **Zendesk Admin Panel**
   - Settings > Routing > Message Routing
   - Assign survey to conversation via Sunshine API
   - URI includes authentication token for security

#### CSAT Button State Persistence:
The code includes CSAT button state tracking via cache:
```python
# When CSAT button clicked
cache.set(f'csat_clicked_{conversation_id}', True, timeout=604800)  # 7 days

# On page refresh, check state
is_csat_clicked = cache.get(f'csat_clicked_{conversation_id}', False)
if is_csat_clicked:
    # Disable CSAT button in frontend
    pass
```

### File Attachments

#### Upload Process:
1. **User selects file** in chat widget
2. **POST /api/send-to-zendesk**
   - File uploaded to `POST /v2/apps/{appId}/attachments`
   - Returns `mediaUrl`
   - Creates message with file content type
3. **Message stored** in Sunshine
4. **Webhook notified**, forwarded to chat

#### Supported File Types:
- Documents: PDF, DOC, DOCX, XLS, TXT, etc.
- Images: JPG, PNG, GIF, WebP, HEIC
- Media: MP3, MP4, etc.

#### File Message Structure:
```json
{
  "author": {
    "type": "user",
    "userId": "user_id"
  },
  "content": {
    "type": "file",
    "mediaUrl": "https://api.smooch.io/v2/apps/123/attachments/file_id",
    "fileName": "document.pdf",
    "contentType": "application/pdf",
    "fileSize": 2048
  }
}
```

#### Image Handling:
- Images automatically detected by extension
- Proxied through `/api/image-proxy` for authentication
- Loaded in `<img>` tags in chat
- CORS/auth handled by bot

#### Conversation Log Integration:
Files from Zendesk tickets stored in `attachments` array:
```python
parsed_attachments.append({
    "url": proxied_url,
    "type": "image|file",
    "fileName": "document.pdf",
    "contentType": "application/pdf",
    "size": 2048
})
```

---

## 📜 Message History

### History Sources

The system maintains history from **two sources**:

#### 1. **Sunshine Conversations**
- Live conversation messages
- Real-time updates
- Latest message history
- API: `GET /v2/apps/{appId}/conversations/{convId}/messages`

#### 2. **Zendesk Conversation Log**
- Historical messages from agent interactions
- Comments on resolved tickets
- Full audit trail
- API: `GET /api/v2/tickets/{ticketId}/conversation_log.json`

### History Retrieval Flow

```
GET /api/chat/full-history?conversationId=xyz
    ├─ Fetch Sunshine messages
    │  └ GET /v2/apps/{appId}/conversations/{convId}/messages
    │
    ├─ Find Zendesk ticket mapping
    │  ├─ Check cache: ticket_{convId}
    │  └─ Search: custom_field_{fieldId}:{convId}
    │
    ├─ Fetch Zendesk conversation_log (if ticket exists)
    │  └ GET /api/v2/tickets/{ticketId}/conversation_log.json
    │
    └─ Deduplicate & combine
       ├─ Calculate fingerprints for each message
       ├─ Remove duplicates
       └─ Sort by timestamp
```

### Message Deduplication

**Fingerprint Formula**:
```
author_type:timestamp[:19]:text[:100].lower()
```

**Logic**:
1. Extract author type (normalized to: user, agent, bot)
2. Take timestamp up to second precision (from Zendesk API)
3. Take first 100 characters of message text (lowercased)
4. If same fingerprint exists, skip duplicate

**Example**:
```
Message 1 (Sunshine): "Hello" from Agent at 10:30:00
Message 2 (Zendesk): "Hello" from Agent at 10:30:00
Fingerprint: "agent:2024-01-22T10:30:00:hello"
Result: Only one message shown
```

### Daily Timestamp Separators

**Implementation**:
- One timestamp separator per calendar day (not per time gap)
- Format: "February 2, 2026 at 10:58 AM"
- Separators only shown when calendar day changes

**How It Works**:
1. Each message includes `received` timestamp from Zendesk API
2. Frontend compares current message date with `lastMessageDate`
3. If different calendar day: insert separator
4. Separator styled with light gray background, rounded edges, centered text
5. No individual timestamps under messages (clean UI)

**Timestamp Validation**:
- Validates timestamp is valid ISO 8601 date before using
- Checks: `isNaN(messageDate.getTime())` to ensure parseable
- If invalid: No separator shown, message still displayed
- Applied to all message types: text, images, files, choices

**Consistency Across Scenarios**:
- **Real-time messages** (WebSocket): Uses `received` from Zendesk webhook
- **Message history** (reopening chat): Uses `received` from Zendesk API
- **Result**: Same timestamps shown whether message arrives live or loaded from history

### Zendesk Conversation Log Parsing

**Event Types Parsed**:
- `Messaging::ConversationMessage`
- `Comment`

**Ignored Events**:
- System messages ("Connecting to agent")
- Empty messages
- Conversation metadata entries

**Field Mapping**:
```python
{
  "id": event["id"],
  "text": strip_html_tags(event["content"]["text"]),
  "author": {
    "type": normalize(event["author"]["type"]),
    "displayName": event["author"]["display_name"]
  },
  "received": event["created_at"],
  "messageClass": "user|agent|bot",
  "source": "conversation_log",
  "attachments": []  # Parsed from event attachments
}
```

### Attachment Handling in History

**Image Detection**:
```python
image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic']

# Check: file extension OR URL patterns OR content-type
is_image = (
    any(ext in filename.lower() for ext in image_extensions) or
    'image' in url_decoded.lower() or
    'whatsapp' in url_decoded.lower() or
    content_type.startswith('image/')
)
```

**Proxying**:
- Zendesk image URLs proxied through `/api/image-proxy`
- Adds authentication headers
- Returns image with correct content-type

---

## 🔔 Notifications System

### Architecture

The system uses **two notification channels**:

#### 1. **Server-Sent Events (SSE)**
- Persistent HTTP connection
- Real-time event streaming
- Text-based protocol
- No browser reconnection logic needed

#### 2. **Cache-based Storage**
- Redis cache for notification queue
- Notifications stored per conversation
- Global notification queue for cross-conversation updates
- Timeout: 30-60 seconds

### SSE Endpoints

#### A. **Per-Conversation Stream**
**URL**: `GET /api/notifications/stream/{conversation_id}`

**Purpose**: Subscribe to notifications for specific conversation

**Response Type**: `text/event-stream`

**Events Sent**:
```
event: connected
data: {"type": "connected", "conversationId": "conv_id"}

event: new_message
data: {
  "type": "new_message",
  "conversationId": "conv_id",
  "agentName": "Agent Name",
  "messagePreview": "First 100 chars...",
  "unreadCount": 3,
  "timestamp": "2024-01-22T10:30:00Z",
  "isInteractive": false,
  "choices": [],
  "actions": []
}

: keepalive
```

#### B. **Global Notification Stream**
**URL**: `GET /api/notifications/stream/global`

**Purpose**: Subscribe to all conversations' notifications

**Response Type**: `text/event-stream`

**Events Sent**:
```
event: connected
data: {"type": "connected", "scope": "global"}

event: new_message
data: {
  ...same as per-conversation...
}

: keepalive
```

### Notification Flow

```
1. Agent sends message in Sunshine
              ↓
2. Sunshine webhook: POST /hooks/sunshine/message
              ↓
3. process_message_event() processes the event
   - Check if author_type == "business"
   - Check if user is NOT currently viewing (cache.get('user_viewing_{convId}'))
   - If yes:
       └─ Increment unread counter
       └─ Call send_notification_to_client()
              ↓
4. send_notification_to_client(conversation_id, message_data)
   - Store in cache: notification_{convId} (30-second timeout)
   - Add to global queue: global_notification (60-second timeout)
              ↓
5. Browser-side SSE listener receives event
              ↓
6. Update unread badge
   └─ Close chat = show red badge with count
   └─ Open chat = badge disappears
```

### Notification Structure

**Data Stored** in cache:
```python
{
  'type': 'new_message',
  'conversationId': 'conv_id',
  'agentName': 'Agent Name',
  'messagePreview': 'text[:100]',
  'unreadCount': 3,
  'timestamp': 'ISO8601',
  'isInteractive': False,
  'choices': [...],      # If message has choices
  'actions': [...]       # If message has actions
}
```

### Unread Badge Logic

**When incremented**:
1. User not viewing chat window
2. Agent sends message
3. Unread count incremented: `cache.incr(f'unread_{convId}')`

**When decremented**:
1. User opens chat window
2. `POST /api/chat/clear-badge` called
3. `cache.delete(f'unread_{convId}')`

**Suppression Conditions**:
```python
is_user_viewing = cache.get(f'user_viewing_{conversation_id}', False)
if not is_user_viewing:
    # Send notification and increment unread
```

### SSE Implementation Details

**Generator Pattern** (Async):
```python
async def notification_stream_generator(conversation_id):
    # 1. Yield initial connection event
    yield f"event: connected\ndata: {{...}}\n\n"
    
    # 2. Loop for 300 seconds (5 minutes)
    while current_time - start_time < 300:
        # Check cache for new notifications
        notification = cache.get(f'notification_{conversation_id}')
        if notification:
            yield f"event: new_message\ndata: {json.dumps(notification)}\n\n"
            cache.delete(notification_key)
        
        # Send keepalive every 30 seconds
        if current_time - last_keepalive >= 30:
            yield ": keepalive\n\n"
        
        await asyncio.sleep(0.1)
```

**Browser-side Listener**:
```javascript
const eventSource = new EventSource(`/api/notifications/stream/${conversationId}`);

eventSource.addEventListener('new_message', (e) => {
  const data = JSON.parse(e.data);
  updateUnreadBadge(data.unreadCount);
  showNotification(data);
});

eventSource.addEventListener('keepalive', (e) => {
  // Connection still alive
});

eventSource.addEventListener('error', (e) => {
  if (e.readyState === EventSource.CLOSED) {
    // Reconnect with exponential backoff
  }
});
```

### Cache Keys Reference

| Key | Purpose | Timeout | Usage |
|-----|---------|---------|-------|
| `notification_{convId}` | Current notification | 30s | SSE streaming |
| `global_notification` | All conversation queue | 60s | Global SSE |
| `unread_{convId}` | Unread message count | 604800s | Badge display |
| `user_viewing_{convId}` | User is viewing chat | 3600s | Suppress notifications |
| `conversation_info_{convId}` | Last message metadata | 604800s | Chat state |
| `pending_escalation_{convId}` | Escalation request | 300s | Ticket mapping |
| `category_{convId}` | Category selection | 3600s | Ticket category |
| `ticket_status_{ticketId}` | Ticket active state | 86400s | Agent session tracking |
| `conversation_{convId}` | Conv->Ticket mapping | 604800s | Bidirectional lookup |
| `ticket_{ticketId}` | Ticket->Conv mapping | 604800s | Bidirectional lookup |
| `csat_clicked_{convId}` | CSAT button state | 604800s | Button disable on refresh |

---

## ⚙️ Environment Configuration

### Required Environment Variables

```bash
# Zendesk Sunshine Configuration
SUNSHINE_APP_ID=your_sunshine_app_id
SUNSHINE_API_KEY_ID=your_api_key_id
SUNSHINE_API_KEY_SECRET=your_api_key_secret
SUNSHINE_API_BASE_URL=https://api.smooch.io  # or EU: https://api-eu.smooch.io
SUNSHINE_WEBHOOK_SIGNING_SECRET=your_webhook_secret  # For signature verification

# Zendesk Support Configuration
ZENDESK_SUBDOMAIN=your_subdomain  # E.g., "mycompany"
ZENDESK_EMAIL=your_email@company.com
ZENDESK_API_TOKEN=your_api_token

# Zendesk Custom Fields
ZENDESK_CHAT_CONVERSATION_FIELD_ID=12345  # Field ID for storing conversation_id
APP_RELATED_SUB_CATEGORY=67890              # Field ID for category/tag

# Redis Configuration
REDIS_URL=redis://localhost:6379  # Format: redis://host:port

# Django Settings
DEBUG=False  # Set to False in production
SECRET_KEY=your_django_secret_key
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
```

### Environment Variable Details

#### SUNSHINE_APP_ID
- **Source**: Zendesk Sunshine Conversations dashboard
- **Format**: UUID string (e.g., `550e8400-e29b-41d4-a716-446655440000`)
- **Used in**: All Sunshine API calls as `{appId}` parameter

#### SUNSHINE_API_KEY_ID & SUNSHINE_API_KEY_SECRET
- **Source**: Sunshine API credentials
- **Format**: Long alphanumeric strings
- **Used in**: HTTP Basic Auth: `Authorization: Basic base64(id:secret)`
- **Scopes**: Must have access to apps, users, conversations, messages, attachments

#### SUNSHINE_WEBHOOK_SIGNING_SECRET
- **Source**: Sunshine webhook settings
- **Format**: Long alphanumeric string
- **Used in**: HMAC SHA256 signature verification
- **Verification**:
  ```python
  hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
  ```

#### ZENDESK_SUBDOMAIN
- **Example**: If your Zendesk URL is `mycompany.zendesk.com`, value is `mycompany`
- **Used in**: Building API URLs: `https://{SUBDOMAIN}.zendesk.com/api/v2/...`

#### ZENDESK_EMAIL & ZENDESK_API_TOKEN
- **Source**: Zendesk admin panel
- **Email**: Admin user email
- **Token**: Personally generated (Settings → Apps & integrations → API)
- **Used in**: HTTP Basic Auth: `Authorization: Basic base64(email/token:token)`

#### ZENDESK_CHAT_CONVERSATION_FIELD_ID
- **Type**: Zendesk custom field ID (integer)
- **Purpose**: Store Sunshine conversation_id in Zendesk tickets
- **Configuration**:
  1. Go to Zendesk admin → Tickets → Custom fields
  2. Create field named "Sunshine Conversation ID"
  3. Copy the field ID (shown in URL)
  4. Set value in environment

#### APP_RELATED_SUB_CATEGORY
- **Type**: Zendesk custom field ID (integer)
- **Purpose**: Store escalation category (Location, Login, Responding, etc.)
- **Values**: `location_not_found_or_inaccurate`, `unable_to_login`, `my_app_is_not_responding`, `others`

#### REDIS_URL
- **Format**: `redis://[:password@]host:port[/database]`
- **Examples**:
  - Local: `redis://localhost:6379`
  - With password: `redis://:mypassword@localhost:6379`
  - Different database: `redis://localhost:6379/1`
  - Render.com: `redis://default:password@host:port`

### Configuration in settings.py

```python
import os
from dotenv import load_dotenv

load_dotenv()

# Sunshine Configuration
SUNSHINE_APP_ID = os.getenv("SUNSHINE_APP_ID", "").strip()
SUNSHINE_API_KEY_ID = os.getenv("SUNSHINE_API_KEY_ID", "").strip()
SUNSHINE_API_KEY_SECRET = os.getenv("SUNSHINE_API_KEY_SECRET", "").strip()
SUNSHINE_API_BASE_URL = os.getenv("SUNSHINE_API_BASE_URL", "https://api.smooch.io").strip().rstrip('/')

# Zendesk Configuration
ZENDESK_SUBDOMAIN = os.getenv("ZENDESK_SUBDOMAIN")
ZENDESK_EMAIL = os.getenv("ZENDESK_EMAIL")
ZENDESK_API_TOKEN = os.getenv("ZENDESK_API_TOKEN")
ZENDESK_CHAT_CONVERSATION_FIELD_ID = os.getenv("ZENDESK_CHAT_CONVERSATION_FIELD_ID")
APP_RELATED_SUB_CATEGORY = os.getenv("APP_RELATED_SUB_CATEGORY")

# Redis & Cache
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            "hosts": [REDIS_URL],
        },
    },
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_URL + '/0',
    }
}
```

### Local Development .env File

Create `.env` in project root:

```
# Sunshine
SUNSHINE_APP_ID=550e8400-e29b-41d4-a716-446655440000
SUNSHINE_API_KEY_ID=abc123def456
SUNSHINE_API_KEY_SECRET=secret789xyz
SUNSHINE_API_BASE_URL=https://api.smooch.io
SUNSHINE_WEBHOOK_SIGNING_SECRET=webhook_secret_123

# Zendesk
ZENDESK_SUBDOMAIN=mycompany
ZENDESK_EMAIL=admin@mycompany.com
ZENDESK_API_TOKEN=your_api_token_here
ZENDESK_CHAT_CONVERSATION_FIELD_ID=20123456
APP_RELATED_SUB_CATEGORY=20123457

# Redis
REDIS_URL=redis://localhost:6379

# Django
DEBUG=True
SECRET_KEY=django-insecure-...
ALLOWED_HOSTS=localhost,127.0.0.1
```

---

---

## ⏰ Timestamp System Architecture

### Zendesk-Only Timestamp Sourcing

The system uses **only timestamps provided by Zendesk APIs**. No server-generated fallbacks.

#### Timestamp Sources (Priority Order):

1. **Primary**: `message.received` from Zendesk Sunshine API
   - Available on all Sunshine messages
   - ISO 8601 format: `"2024-01-22T10:30:00Z"`
   - Timezone: UTC

2. **Secondary**: `message.timestamp` from Zendesk Support API
   - Available in Zendesk ticket conversation logs
   - Format: `"2024-01-22T10:30:00Z"`
   - Timezone: UTC

3. **No Fallback**: `datetime.now()` removed
   - Previous: Server would generate timestamp if Zendesk data missing
   - Now: If timestamp unavailable, message shows without separator
   - Prevents timezone mismatches and stale data issues

#### Why Zendesk-Only?

| Issue | With Server Fallback | With Zendesk-Only |
|-------|----------------------|-------------------|
| **Timezone Mismatch** | Different times on different clients | Consistent across all clients |
| **Page Refresh** | Old conversation shows current date | Shows actual date/time |
| **Multi-Server** | Each server shows different time | Same time regardless of server |
| **Historical Accuracy** | Stale when reopened | Always shows actual message time |

#### Implementation Across Components:

**Backend (views.py)**:
```python
def forward_agent_message_to_websocket(..., received_timestamp=None):
    # Pass Zendesk's received timestamp to WebSocket
    websocket_message['payload']['received'] = received_timestamp
    # Only include timestamp if from Zendesk - no server-generated times
```

**Backend (consumers.py)**:
```python
# Don't add fallback timestamp
# Use only Zendesk-provided 'received' timestamp
# If message doesn't have 'received' from Zendesk, it will be null on frontend
```

**Frontend (chat-widget.js)**:
```javascript
// Validate timestamp is valid date before using
if (timestamp) {
    try {
        messageDate = new Date(timestamp);
        // Check if valid date object
        if (isNaN(messageDate.getTime())) {
            messageDate = null;  // Invalid - no separator
        }
    } catch (e) {
        messageDate = null;  // Parse error - no separator
    }
}
// Only show separator if we have valid Zendesk timestamp
if (messageDate && shouldAddDaySeparator(messageDate)) {
    appendDaySeparator(messageDate);
}
```

#### Cache Implications:

Cache stores Zendesk-provided timestamps:
```python
# When storing conversation info
cache.set(
    f'conversation_info_{convId}',
    {'timestamp': message.get('received')},  # From Zendesk
    timeout=604800  # 7 days
)
```

---

## 🚀 Deployment Guide

### Local Development

#### 1. Setup Virtual Environment
```bash
python -m venv botenv
source botenv/Scripts/activate  # Windows: botenv\Scripts\activate
```

#### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

#### 3. Create .env File
```bash
cp .env.example .env
# Edit .env with your credentials
```

#### 4. Run Redis
```bash
# Using Docker
docker run -d -p 6379:6379 redis:latest

# Or using Windows Subsystem for Linux
redis-server

OR 

use Render redis server
```

#### 5. Start Django Development Server
```bash
# Terminal 1: Run ASGI server (for WebSockets) on Render
uvicorn Bot.asgi:application --host 0.0.0.0 --port 8000
```

#### 6. Configure Webhooks
In Zendesk:
- **Sunshine**: Set webhook URL to `/hooks/sunshine/message`
- **Zendesk**: Set webhook URL to `/zendesk/webhook`

### Production Deployment (Render.com)

#### 1. Push to GitHub
```bash
git add .
git commit -m "Deployment ready"
git push origin main
```

#### 2. Create New Service on Render
- Connect GitHub repository
- Service name: `zendesk-sunshine-bot`
- Environment: `Python 3.11`
- Build command: `pip install -r requirements.txt && python manage.py collectstatic --noinput`
- Start command: `uvicorn Bot.asgi:application --host 0.0.0.0 --port $PORT`

#### 3. Set Environment Variables
```
SUNSHINE_APP_ID=...
SUNSHINE_API_KEY_ID=...
SUNSHINE_API_KEY_SECRET=...
SUNSHINE_WEBHOOK_SIGNING_SECRET=...
ZENDESK_SUBDOMAIN=...
ZENDESK_EMAIL=...
ZENDESK_API_TOKEN=...
ZENDESK_CHAT_CONVERSATION_FIELD_ID=...
APP_RELATED_SUB_CATEGORY=...
REDIS_URL=redis://your-redis-url
DEBUG=False
```

#### 4. Setup Redis
- Create Redis instance on Render
- Copy the internal Redis URL
- Set `REDIS_URL` in environment variables

#### 5. Configure Webhooks
In Zendesk:
- **Sunshine**: `https://your-render-url/hooks/sunshine/message`
- **Zendesk**: `https://your-render-url/zendesk/webhook`

### Database Migrations
```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

### Health Check
```bash
curl https://your-domain/api/chat/init -X POST -H "Content-Type: application/json" -d '{}'
```

---

## 📝 API Quick Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/chat/init` | POST | Create/fetch user and conversation |
| `/api/chat/send` | POST | Send message from user |
| `/api/chat/messages` | GET | Get conversation messages |
| `/api/chat/full-history` | GET | Get complete history (Sunshine + Zendesk) |
| `/api/chat/escalate` | POST | Escalate to agent |
| `/api/send-to-zendesk` | POST | Upload file/attachment |
| `/api/chat/viewing-status` | POST | Track user viewing state |
| `/api/chat/clear-badge` | POST | Clear unread badge |
| `/api/image-proxy` | GET | Proxy Zendesk images |
| `/hooks/sunshine/message` | POST | Sunshine webhook (agent messages) |
| `/zendesk/webhook` | POST | Zendesk webhook (ticket comments) |
| `/api/notifications/stream/global` | GET | SSE: Global notifications |
| `/api/notifications/stream/{convId}` | GET | SSE: Per-conversation notifications |
| `/ws/chat/{convId}/` | WebSocket | Real-time messaging |

---

## 🔐 Security Considerations

### CSRF Protection
- All endpoints use `@csrf_exempt` (webhooks require signature verification instead)
- Production: Consider CSRF tokens for browser requests

### Signature Verification
```python
# Sunshine webhook
hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()

# Zendesk: no verification (relies on Zendesk IP whitelist)
```

### Authentication
- HTTP Basic Auth for API calls
- No session-based auth (stateless)
- API credentials stored in environment variables only

### Rate Limiting
- None implemented (add in production)
- Consider: Zendesk rate limits (100 requests/minute)
- Consider: Sunshine rate limits (check documentation)

### Data Privacy
- Cache doesn't store sensitive data (only IDs and metadata)
- Messages passed through webhook must be HTTPS
- File URLs proxied for secure download

---

## 🐛 Troubleshooting

### Common Issues

#### 1. WebSocket Connection Fails
**Problem**: `WebSocket connection failed`

**Causes**:
- Redis not running
- Channel layer misconfigured
- ASGI server not running

**Solution**:
```bash
# Check Redis
redis-cli ping  # Should return PONG

# Check ASGI server
ps aux | grep uvicorn

# Restart
uvicorn Bot.asgi:application --host 0.0.0.0 --port 8000
```

#### 2. Signature Verification Failed
**Problem**: `Invalid signature` on Sunshine webhook

**Causes**:
- Wrong webhook secret
- Webhook modified by proxy
- Base64 encoding issue

**Solution**:
```python
# Test signature
import hmac, hashlib

payload = request.body
secret = os.getenv("SUNSHINE_WEBHOOK_SIGNING_SECRET")
expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
received = request.headers.get("X-Hub-Signature").split("=")[1]
print(f"Expected: {expected}")
print(f"Received: {received}")
```

#### 3. Messages Not Appearing in Chat
**Problem**: Agent messages not showing in conversation

**Causes**:
- Webhook not configured
- Conversation ID mismatch
- Cache issue

**Solution**:
1. Check Sunshine webhook is set and receiving requests
2. Verify conversation_id in logs
3. Clear cache: `redis-cli FLUSHALL`
4. Check WebSocket group: `f'chat_{conversation_id}'`

#### 4. Zendesk Ticket Not Creating
**Problem**: Escalation doesn't create ticket

**Causes**:
- Agent workspace not configured
- Custom field IDs wrong
- passControl metadata malformed

**Solution**:
1. Test in Zendesk Agent Workspace
2. Verify custom field IDs in Zendesk admin
3. Check logs for passControl response
4. Ensure agent workspace integration active

---

## 📚 Additional Resources

- [Zendesk Sunshine API Docs](https://developer.zendesk.com/documentation/)
- [Django Channels Documentation](https://channels.readthedocs.io/)
- [Redis Documentation](https://redis.io/docs/)
- [WebSocket Protocol RFC 6455](https://tools.ietf.org/html/rfc6455)
- [Server-Sent Events MDN](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)

---
**Last Updated**: February 2, 2026
**Version**: 1.2
**Author**: Ashad Shaikh
