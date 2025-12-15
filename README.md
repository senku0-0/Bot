# Yatri Bandhu Chat Bot

This project is a custom chat widget integrated with **Zendesk** and **Sunshine Conversations** (formerly Smooch). It allows users to interact with a bot, escalate issues to human agents, and manage support tickets directly from a web interface.

**Live Demo:** [https://bot-neqq.onrender.com/](https://bot-neqq.onrender.com/)

---

## 🛠 Technologies & Concepts

### 1. Zendesk
**Zendesk** is the customer service platform used by agents to manage support tickets.
*   **Role in Project:** It acts as the "backend" for support agents. When a user escalates a chat, a ticket is created in Zendesk. Agents reply from the Zendesk dashboard, and their replies appear in the chat widget.
*   **Key Features Used:** Ticket Fields (for categorization), CSAT (Customer Satisfaction Surveys), and Agent Workspace.

### 2. Sunshine Conversations (Smooch)
**Sunshine Conversations** is the messaging middleware that connects our custom chat widget to Zendesk.
*   **Role in Project:** It handles the real-time messaging API. It sits between our Django backend and Zendesk.
*   **Key Features Used:**
    *   **Messaging API:** Sending/receiving text, images, and files.
    *   **Webhooks:** Notifying our backend of events (messages, agent joins, etc.).
    *   **User Management:** Creating and tracking users (`appUserId` vs `externalId`).

### 3. Switchboard
The **Switchboard** is a feature of Sunshine Conversations that manages "who is in control" of the conversation.
*   **Role in Project:** It prevents the bot from interfering when a human agent is talking.
*   **Flow:**
    *   **Bot Control:** Initially, the bot (our backend) listens to messages and creates tickets.
    *   **Pass Control:** When the user clicks "Connect to Agent", we call the `passControl` API to hand the conversation over to the `next` integration (Zendesk).
    *   **Release Control:** When the agent solves the ticket, Zendesk releases control back to the bot.

### 4. Webhooks
Webhooks are real-time notifications sent by Sunshine Conversations to our Django backend (`/hooks/sunshine/message`).

**Active Webhook Triggers:**

| Trigger Name | Use Case | Meaning |
| :--- | :--- | :--- |
| `conversation:message` | **User Messages** | Fired when a user sends a message. We use this to create tickets in Zendesk if the bot is in control. |
| `postback` | **Button Clicks** | Fired when a user clicks a button or star rating. We map 5-star ratings to Zendesk's scale (e.g., 5="Very satisfied", 1="Very unsatisfied"). |
| `switchboard:passControl` | **Escalation** | Fired when control moves from Bot to Zendesk. Confirms the user is now waiting for an agent. |
| `switchboard:releaseControl` | **Session End** | Fired when the agent ends the chat (Solves ticket). We use this to notify the user "Session Ended". |
| `participant:join` | **Agent Joined** | Fired when an agent enters the chat. We use this to show "Agent connected" in the UI. |
| `conversation:read` | **Agent Read** | Fired when an agent opens the ticket. We use this as a faster "Agent connected" signal. |

---

##   Workflow Diagram

1.  **Initialization**:
    *   User opens the chat widget.
    *   Frontend calls `/api/chat/init` to create/retrieve a Sunshine User (`appUserId`).

2.  **Bot Interaction**:
    *   User selects options (e.g., "App Related Issues").
    *   Bot replies with predefined steps.
    *   If User types a message, it is sent to Sunshine.
    *   **Webhook** (`conversation:message`) triggers, and Django creates a ticket in Zendesk.

3.  **Escalation (Handover)**:
    *   User clicks "Connect to Agent".
    *   Frontend calls `/api/chat/escalate` with the `category` and `subCategory`.
    *   Django calls Sunshine `passControl` API.
    *   **Switchboard** moves control from `bot` to `zendesk`.
    *   Zendesk Ticket is updated with the specific issue tags.

4.  **Live Chat**:
    *   Agent accepts the chat in Zendesk Agent Workspace.
    *   Agent replies are sent via Sunshine to the widget.
    *   User replies are sent directly to Zendesk (bypassing the bot logic).

5.  **Resolution & Feedback**:
    *   Agent marks ticket as **Solved**.
    *   Zendesk triggers the **CSAT Survey**.
    *   Widget receives the survey as a message with options.
    *   Widget renders the **5-Star Rating** UI.
    *   User clicks a star -> Rating is sent back to Zendesk.

---

##  🚀 Setup Instructions

### Prerequisites
*   Python 3.8+
*   Django
*   Zendesk Account (with Sunshine Conversations enabled)

### 1. Clone & Install
```bash
git clone <repository-url>
cd Bot
python -m venv botenv
source botenv/bin/activate  # or botenv\Scripts\activate on Windows
pip install django requests python-dotenv
```

### 2. Environment Variables
Create a `.env` file in the root directory with the following credentials:

```ini
# Sunshine Conversations Credentials
SUNSHINE_APP_ID=your_app_id
SUNSHINE_API_KEY_ID=your_key_id
SUNSHINE_API_KEY_SECRET=your_key_secret
SUNSHINE_WEBHOOK_SIGNING_SECRET=your_webhook_secret
SUNSHINE_API_BASE_URL=https://api.smooch.io

# Zendesk Credentials (for Ticket API)
ZENDESK_SUBDOMAIN=your_subdomain
ZENDESK_EMAIL=your_email
ZENDESK_API_TOKEN=your_api_token
```

### 3. Run the Server
```bash
python manage.py migrate
python manage.py runserver
```
Access the widget at `http://localhost:8000`.

### 4. Webhook Configuration
1.  Go to the **Sunshine Conversations Dashboard**.
2.  Create a new **Webhook**.
3.  Set the Target URL to `https://your-domain.com/hooks/sunshine/message`.
4.  Select the **Triggers** listed in the table above (v2 API).

---

## 🌍 Production Deployment

To deploy this project to production (e.g., Render, Heroku, AWS), you need to serve static files efficiently and use a production-grade ASGI server.

### 1. Install Dependencies
Install `whitenoise` for static files and `uvicorn` for the ASGI server.

```bash
pip install whitenoise uvicorn
pip freeze > requirements.txt
```

### 2. Configure WhiteNoise
In `Bot/settings.py`, add WhiteNoise to the `MIDDLEWARE` list. It must be placed **after** `SecurityMiddleware`.

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', # Add this line
    # ... other middleware
]
```

Also, configure static file storage in `Bot/settings.py`:

```python
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
```

### 3. Run with Uvicorn
In production, do not use `python manage.py runserver`. Instead, use `uvicorn`:

```bash
uvicorn Bot.asgi:application --host 0.0.0.0 --port 10000
```
*(Replace `Bot` with your project name if different)*

---

## 📂 Project Structure

*   `bot_app/views.py`: Core logic for Webhooks, API endpoints, and Zendesk integration.
*   `static/js/chat-widget.js`: Frontend logic (UI, Polling, File Uploads, CSAT rendering).
*   `static/css/chat-widget.css`: Styling for the chat interface.
*   `templates/index.html`: Main entry point for the widget.
