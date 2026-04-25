from django.shortcuts import render
from django.http import JsonResponse, HttpResponseForbidden, HttpRequest, HttpResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
import json, hmac, hashlib, os, base64, logging, sys, uuid, re, time, asyncio
from typing import Optional, Dict, Any, Union, List, Set
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

def get_env_any(*names: str, default: Optional[str] = None) -> Optional[str]:
    """
    Return the first non-empty environment value from a list of possible keys.

    This keeps Zendesk field/form ID loading backward-compatible across
    different `.env` naming styles used by teammates and older deployments.
    """
    for name in names:
        if not name:
            continue
        value = os.getenv(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default

def strip_html_tags(text: str) -> str:
    """
    Remove HTML tags from text and normalize whitespace.
    
    Args:
        text (str): Text containing HTML tags
    
    Returns:
        str: Cleaned text with tags removed and whitespace normalized
    
    Examples:
        >>> strip_html_tags('<p>Hello <b>world</b></p>')
        'Hello world'
    """
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()

def is_conversation_log_entry(text: str) -> bool:
    """
    Detect if text is a conversation log entry (metadata, not actual message).
    
    Filters out system messages like timestamps, file uploads, escalation reasons,
    and other conversation metadata that shouldn't be displayed as regular messages.
    
    Args:
        text (str): Message text to check
    
    Returns:
        bool: True if text is a conversation log entry, False otherwise
    
    Patterns detected:
        - Timestamp patterns like (10:30:00)
        - File upload indicators
        - Escalation metadata
        - Sunshine conversation markers
    """
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
    """
    Convert Zendesk image URLs to proxy endpoints for authentication & CORS.
    
    Detects if URL is from Zendesk/Smooch domains and returns a proxied URL
    that goes through the bot's proxy endpoint for authenticated access.
    
    Args:
        original_url (str): Original image URL from Zendesk/Sunshine
    
    Returns:
        str: Proxied URL if from Zendesk domain, otherwise original URL
    
    Examples:
        >>> get_proxied_image_url('https://zdassets.com/image.jpg')
        '/api/image-proxy?url=https%3A%2F%2Fzdassets.com%2Fimage.jpg'
    """
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
ZENDESK_CHAT_CONVERSATION_FIELD_ID = get_env_any("ZENDESK_CHAT_CONVERSATION_FIELD_ID")
APP_RELATED_SUB_CATEGORY = get_env_any("APP_RELATED_SUB_CATEGORY")
NAME_FIELD_ID = get_env_any("NAME_FIELD_ID", "NAME", "Name")
EMAIL_ID_FIELD_ID = get_env_any("EMAIL_ID_FIELD_ID", "EMAIL_ID", "Email_ID")
FARE_AND_PAYMENT_SUBCATEGORY_FIELD_ID = get_env_any(
    "FARE_AND_PAYMENT_SUBCATEGORY_FIELD_ID",
    "FARE_AND_PAYEMT_SUBCATEGORY_FIELD_ID",
    "FARE_AND_PAYMENT_SUBCATEGORY",
    "FARE_AND_PAYEMT_SUBCATEGORY",
    "Fare_and_payemt_subcategory",
)
RIDE_ID_FIELD_ID = get_env_any("RIDE_ID_FIELD_ID", "RIDE_ID", "rideId")
DRIVER_NAME_FIELD_ID = get_env_any("DRIVER_NAME_FIELD_ID", "DRIVER_NAME", "Driver_Name")
PAYMENT_MODE_FIELD_ID = get_env_any("PAYMENT_MODE_FIELD_ID", "PAYMENT_MODE", "Payment_Mode")
CONTACT_FIELD_ID = get_env_any("CONTACT_FIELD_ID", "CONTACT", "Contact")
VEHICLE_NUMBER_FIELD_ID = get_env_any("VEHICLE_NUMBER_FIELD_ID", "VEHICLE_NUMBER", "Vehicle_Number")
VEHICLE_ISSUE_TYPE_FIELD_ID = get_env_any("VEHICLE_ISSUE_TYPE_FIELD_ID", "VEHICLE_ISSUE_TYPE", "Vehicle_Issue_Type")
ESCALATION_TO_SAFETY_TEAM_FIELD_ID = get_env_any(
    "ESCALATION_TO_SAFETY_TEAM_FIELD_ID",
    "ESCALATION_TO_SAFETY_TEAM",
    "Escalationto_Safety_Team",
)
SAFETY_ISSUE_TYPE_FIELD_ID = get_env_any("SAFETY_ISSUE_TYPE_FIELD_ID", "SAFETY_ISSUE_TYPE", "Safety_issue_type")
FARE_AND_PAYMENT_FORM_ID = get_env_any("FARE_AND_PAYMENT_FORM_ID", "FARE_PAYMENT_FORM_ID")
FIMD_A_LOST_ITEM_FORM_ID = get_env_any("FIMD_A_LOST_ITEM_FORM_ID", "FIND_A_LOST_ITEM_FORM_ID")
APP_RELATED_ISSUE_FORM_ID = get_env_any("APP_RELATED_ISSUE_FORM_ID")
VEHUICLE_AC_ISSUE_FORM_ID = get_env_any("VEHUICLE_AC_ISSUE_FORM_ID", "VEHICLE_AC_ISSUE_FORM_ID")
SAFETY_ISSUE_FORM_ID = get_env_any("SAFETY_ISSUE_FORM_ID")
SUNSHINE_APP_ID = os.getenv("SUNSHINE_APP_ID", "").strip()
SUNSHINE_API_KEY_ID = os.getenv("SUNSHINE_API_KEY_ID", "").strip()
SUNSHINE_API_KEY_SECRET = os.getenv("SUNSHINE_API_KEY_SECRET", "").strip()
SUNSHINE_API_BASE_URL = os.getenv("SUNSHINE_API_BASE_URL", "https://api.smooch.io").strip().rstrip('/')

APP_RELATED_CATEGORY_TAGS = {
    "location not found or inaccurate": "location_not_found_or_inaccurate",
    "unable to login": "unable_to_login",
    "my app is not responding": "my_app_is_not_responding",
    "others": "others",
    "other": "others",
    "location_not_found_or_inaccurate": "location_not_found_or_inaccurate",
    "unable_to_login": "unable_to_login",
    "my_app_is_not_responding": "my_app_is_not_responding",
    "others": "others",
}

FARE_AND_PAYMENT_SUBCATEGORY_TAGS = {
    # Human-readable labels (as sent by frontend or stored in issueContext)
    "multiple debits occurred": "multiple_debits_occurred",
    "multiple debits occured": "multiple_debits_occurred",      # typo variant
    "multiple debits occur": "multiple_debits_occurred",        # truncated
    "driver charged extra fare": "driver_charged_extra_fare",
    "charged higher than estimated fare": "charged_higher_than_estimated_fare",
    "higher than estimated fare": "charged_higher_than_estimated_fare",
    "cancellation charges": "cancellation_charges",
    "cancellation charge": "cancellation_charges",
}

VEHICLE_ISSUE_TYPE_TAGS = {
    # Human-readable labels
    "unclean unhygienic vehicle": "unclean/unhygienic_vehicle",
    "unclean vehicle": "unclean/unhygienic_vehicle",
    "unhygienic vehicle": "unclean/unhygienic_vehicle",
    "vehicle unsafe": "vehicle_unsafe",
    "unsafe vehicle": "vehicle_unsafe",
    "ac not turned on ac stopped working midway": "ac_not_turned_on_/_ac_stopped_working",
    "ac not turned on ac stopped working": "ac_not_turned_on_/_ac_stopped_working",
    "ac not working": "ac_not_turned_on_/_ac_stopped_working",
    "ac issue": "ac_not_turned_on_/_ac_stopped_working",
    "vehicle was different": "vehicle_was_different",
    "different vehicle": "vehicle_was_different",
}

SAFETY_ISSUE_TYPE_TAGS = {
    # Human-readable labels
    "drunk and drive": "drunk_and_drive",
    "drunk driving": "drunk_and_drive",
    "driver was rude or misbehaved": "driver_was_rude_or_misbehaved",
    "rude driver": "driver_was_rude_or_misbehaved",
    "driver misbehaved": "driver_was_rude_or_misbehaved",
    "other": "other",
    "others": "other",
    "met with an accident": "met_with_an_accident",
    "accident": "met_with_an_accident",
    "sexual harassment": "sexual_harassment",
    "sexual harrasment": "sexual_harassment",
    "sexual harresment": "sexual_harassment",
    "physical fights": "physical_fights",
    "phyiscal fights": "physical_fights",
    "physical fight": "physical_fights",
    "extra person in the vehicle": "extra_person_in_the_vehicle",
    "extra person in vehicle": "extra_person_in_the_vehicle",
    "rash driving": "rash_driving",
    "rash drive": "rash_driving",
    "vehicle broke down": "vehicle_broke_down",
    "breakdown": "vehicle_broke_down",
}

PAYMENT_MODE_TAGS = {
    "cash": "cash",
    "upi": "upi",
}

ISSUE_PATH_PREFIXES = ("App Related Issues", "Ride Related Issues")
SEEDED_TRANSCRIPT_PREFIX = "\u2063\u2063\u2063\u2063"

def normalize_issue_key(value: Any) -> str:
    text = strip_html_tags(str(value or "")).lower()
    text = text.replace("&", " and ")
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def strip_seeded_transcript_prefix(text: Any) -> str:
    value = str(text or "")
    if value.startswith(SEEDED_TRANSCRIPT_PREFIX):
        return value[len(SEEDED_TRANSCRIPT_PREFIX):]
    return value

def is_seeded_transcript_message(message: Any, text: Optional[str] = None) -> bool:
    if not isinstance(message, dict):
        return str(text or "").startswith(SEEDED_TRANSCRIPT_PREFIX)

    metadata_candidates = [message.get("metadata")]
    content = message.get("content")
    if isinstance(content, dict):
        metadata_candidates.append(content.get("metadata"))

    for metadata in metadata_candidates:
        if isinstance(metadata, dict) and metadata.get("seededTranscript"):
            return True

    actual_text = str(
        text
        if text is not None
        else message.get("text")
        or (content.get("text") if isinstance(content, dict) else "")
        or ""
    )
    return actual_text.startswith(SEEDED_TRANSCRIPT_PREFIX)

def extract_conversation_id_from_text(*sources: Any) -> Optional[str]:
    patterns = [
        r'Sunshine\s+Conversation\s*:\s*([0-9a-fA-F]{24,36})',
        r'conversation\s*id\s*[:#-]\s*([0-9a-fA-F]{24,36})',
        r'\[Sunshine\s+Conversation\s*:\s*([0-9a-fA-F]{24,36})\]',
    ]
    for source in sources:
        if not source:
            continue
        text = strip_html_tags(str(source))
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if value:
                    return value
    return None

def safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(str(value).strip())
    except Exception:
        return None

def append_custom_field(custom_fields: List[Dict[str, Any]], field_id: Any, value: Any) -> None:
    field_int = safe_int(field_id)
    if not field_int or value is None or value == "":
        return
    for field in custom_fields:
        if field.get("id") == field_int:
            field["value"] = value
            return
    custom_fields.append({"id": field_int, "value": value})


RECENT_ESCALATION_QUEUE_KEY = "recent_escalations_queue"
RECENT_ESCALATION_MATCH_WINDOW_SECONDS = 20
RECENT_ESCALATION_QUEUE_TTL_SECONDS = 900
RECENT_ESCALATION_QUEUE_MAX = 100
ROUTING_CONTEXT_CACHE_PREFIX = "routing_context_"


def enqueue_recent_escalation(escalation_data: Dict[str, Any]) -> None:
    """
    Keep a short, time-bounded queue of latest handoffs so ticket.created
    can deterministically map back to the originating conversation.
    """
    try:
        conversation_id = str(escalation_data.get("conversation_id", "")).strip()
        if not conversation_id:
            return

        entry = dict(escalation_data)
        entry["conversation_id"] = conversation_id
        entry["timestamp"] = float(entry.get("timestamp") or time.time())

        now = time.time()
        recent = cache.get(RECENT_ESCALATION_QUEUE_KEY, []) or []
        filtered: List[Dict[str, Any]] = []
        for item in recent:
            try:
                item_ts = float(item.get("timestamp") or 0)
            except Exception:
                continue
            if 0 <= (now - item_ts) <= RECENT_ESCALATION_QUEUE_TTL_SECONDS:
                filtered.append(item)

        # Keep only the latest context per conversation so stale branch selections
        # (for example previous AC selection) cannot override a newer selection.
        filtered = [
            item
            for item in filtered
            if str(item.get("conversation_id", "")).strip() != conversation_id
        ]

        filtered.append(entry)
        filtered = filtered[-RECENT_ESCALATION_QUEUE_MAX:]
        cache.set(
            RECENT_ESCALATION_QUEUE_KEY,
            filtered,
            timeout=RECENT_ESCALATION_QUEUE_TTL_SECONDS,
        )
    except Exception as e:
        logger.warning(f"enqueue_recent_escalation error: {e}")


def cache_routing_context(
    conversation_id: Optional[str],
    routing_data: Dict[str, Any],
    timeout: int = 604800,
) -> None:
    """
    Persist latest routing context for a conversation so webhook-side mapping can
    still apply correct form/custom fields even if short-lived pending cache expires.
    """
    try:
        conv_id = str(conversation_id or "").strip()
        if not conv_id:
            return
        cache.set(f"{ROUTING_CONTEXT_CACHE_PREFIX}{conv_id}", routing_data, timeout=timeout)
    except Exception as e:
        logger.warning(f"cache_routing_context error: {e}")

def get_ticket_field_option_values(field_id: Any, auth: HTTPBasicAuth) -> Optional[Set[str]]:
    field_int = safe_int(field_id)
    if not field_int or not ZENDESK_SUBDOMAIN:
        return None

    cache_key = f"zendesk_ticket_field_options_{field_int}"
    cached_options = cache.get(cache_key)
    if isinstance(cached_options, list):
        return {str(option).strip() for option in cached_options if str(option).strip()}

    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/ticket_fields/{field_int}.json"
    response = requests.get(url, auth=auth, timeout=15)
    if response.status_code != 200:
        logger.warning(
            f"Ticket field options lookup failed for field {field_int}: "
            f"{response.status_code} - {response.text}"
        )
        return None

    field_data = response.json().get("ticket_field", {})
    options = field_data.get("custom_field_options", []) or []
    option_values = sorted(
        {
            str(option.get("value", "")).strip()
            for option in options
            if isinstance(option, dict) and str(option.get("value", "")).strip()
        }
    )

    cache.set(cache_key, option_values, timeout=3600)
    return set(option_values)

def resolve_fare_subcategory_value(
    fare_field_id: Any,
    fare_value: Any,
    auth: HTTPBasicAuth,
) -> Any:
    current_value = str(fare_value or "").strip()
    if not current_value:
        return fare_value

    option_values = get_ticket_field_option_values(fare_field_id, auth)
    if not option_values:
        return fare_value

    if current_value in option_values:
        return current_value

    alias_fallbacks = {
        "multiple_debits_occurred": ["multiple_debits_occured"],
        "multiple_debits_occured": ["multiple_debits_occurred"],
        "cancellation_charges": ["cancellation_charge"],
        "cancellation_charge": ["cancellation_charges"],
    }
    for candidate in alias_fallbacks.get(current_value, []):
        if candidate in option_values:
            logger.info(
                f"Fare subcategory fallback: using alias '{candidate}' for '{current_value}'"
            )
            return candidate

    desired_norm = normalize_issue_key(current_value.replace("_", " "))
    for option_value in sorted(option_values):
        option_norm = normalize_issue_key(str(option_value).replace("_", " "))
        if option_norm == desired_norm:
            logger.info(
                f"Fare subcategory normalized fallback: '{current_value}' -> '{option_value}'"
            )
            return option_value

    logger.warning(
        "Fare subcategory value did not match available Zendesk options. "
        f"Current='{current_value}', available={sorted(option_values)}"
    )
    return fare_value


def resolve_dropdown_value(
    field_id: Any,
    desired_value: Any,
    auth: HTTPBasicAuth,
) -> Any:
    """
    Generic dropdown resolver for any Zendesk custom dropdown field.

    Fetches real option values from Zendesk (cached for 1 h) and validates
    that *desired_value* is an accepted option.  If not, attempts common
    normalisation variants before giving up and returning the original value
    (so the per-field retry in update_ticket_routing can still log the error).

    This is the single source of truth for all ride-related dropdown fields:
    - FARE_AND_PAYMENT_SUBCATEGORY
    - VEHICLE_ISSUE_TYPE
    - SAFETY_ISSUE_TYPE
    - PAYMENT_MODE
    """
    current_value = str(desired_value or "").strip()
    if not current_value:
        return desired_value

    option_values = get_ticket_field_option_values(field_id, auth)
    if not option_values:
        # Zendesk field lookup failed – pass through and let Zendesk reject it
        logger.warning(
            f"resolve_dropdown: could not fetch options for field {field_id} – "
            f"passing value '{current_value}' as-is"
        )
        return desired_value

    if current_value in option_values:
        return current_value

    # Normalisation attempts (handles typos, spaces vs underscores, etc.)
    variants = [
        current_value.replace(" ", "_"),
        current_value.replace("_", " "),
        current_value.lower(),
        current_value.lower().replace(" ", "_"),
    ]
    for variant in variants:
        if variant in option_values:
            logger.info(
                f"resolve_dropdown: field={field_id} normalised '{current_value}' -> '{variant}'"
            )
            return variant

    # Backward-compat alias handling for legacy typo tags still present in some setups.
    alias_fallbacks = {
        "sexual_harresment": ["sexual_harassment"],
        "sexual_harassment": ["sexual_harresment"],
        "phyiscal_fights": ["physical_fights"],
        "physical_fights": ["phyiscal_fights"],
    }
    for candidate in alias_fallbacks.get(current_value, []):
        if candidate in option_values:
            logger.info(
                f"resolve_dropdown: field={field_id} alias '{current_value}' -> '{candidate}'"
            )
            return candidate

    # Strong fallback for values with punctuation differences (/, -, _, spaces).
    desired_norm = normalize_issue_key(current_value.replace("_", " "))
    for option_value in sorted(option_values):
        option_norm = normalize_issue_key(str(option_value).replace("_", " "))
        if option_norm == desired_norm:
            logger.info(
                f"resolve_dropdown: field={field_id} normalized '{current_value}' -> '{option_value}'"
            )
            return option_value

    logger.warning(
        f"resolve_dropdown: field={field_id} value '{current_value}' not in Zendesk options "
        f"{sorted(option_values)}"
    )
    return desired_value

def first_non_empty(*values: Any) -> Optional[Any]:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value.strip()
        else:
            return value
    return None

def extract_issue_path_from_text(*candidates: Any) -> str:
    for candidate in candidates:
        if not candidate:
            continue
        text = str(candidate)
        match = re.search(r'Issue Path:\s*([^\r\n]+)', text, re.IGNORECASE)
        if match:
            return strip_html_tags(match.group(1)).strip()
        cleaned = strip_html_tags(text).strip()
        if any(cleaned.startswith(prefix) for prefix in ISSUE_PATH_PREFIXES):
            return cleaned
    return ""

def extract_named_value(patterns: List[str], *text_sources: Any) -> Optional[str]:
    for source in text_sources:
        if not source:
            continue
        cleaned = strip_html_tags(str(source))
        for pattern in patterns:
            match = re.search(pattern, cleaned, re.IGNORECASE | re.MULTILINE)
            if match:
                value = match.group(1).strip().strip(",.;")
                if value:
                    return value
    return None

def looks_like_email(value: Any) -> bool:
    return bool(value and re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', str(value).strip()))

def looks_like_phone(value: Any) -> bool:
    return bool(value and re.fullmatch(r'\+?[0-9][0-9\s-]{6,}', str(value).strip()))

def looks_like_uuid(value: Any) -> bool:
    return bool(value and re.fullmatch(r'[0-9a-fA-F-]{32,36}', str(value).strip()))

def build_issue_context(
    issue_context: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    title: Optional[str] = None,
    transcript: Optional[str] = None,
    app_related_category: Optional[str] = None,
    ride_related_category: Optional[str] = None,
    ride_related_subcategory: Optional[str] = None,
    ride_related_detail: Optional[str] = None
) -> Dict[str, Any]:
    context = dict(issue_context) if isinstance(issue_context, dict) else {}
    current_path = first_non_empty(context.get("currentPath"), extract_issue_path_from_text(reason, title, transcript))
    if current_path:
        context["currentPath"] = current_path
        parts = [strip_html_tags(part).strip() for part in str(current_path).split(">") if strip_html_tags(part).strip()]
        if parts and not context.get("mainCategory"):
            context["mainCategory"] = parts[0]
        if len(parts) > 1 and not context.get("category"):
            context["category"] = parts[1]
        if len(parts) > 2 and not context.get("subcategory"):
            context["subcategory"] = parts[2]
        if len(parts) > 3 and not context.get("detail"):
            context["detail"] = parts[3]
    if app_related_category and not context.get("category"):
        context["mainCategory"] = context.get("mainCategory") or "App Related Issues"
        context["category"] = app_related_category
    if ride_related_category and not context.get("category"):
        context["mainCategory"] = context.get("mainCategory") or "Ride Related Issues"
        context["category"] = ride_related_category
        if ride_related_subcategory and not context.get("subcategory"):
            context["subcategory"] = ride_related_subcategory
        if ride_related_detail and not context.get("detail"):
            context["detail"] = ride_related_detail
    return context


def extract_routing_categories_from_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    resolved_context = build_issue_context(issue_context=context)
    main_key = normalize_issue_key(resolved_context.get("mainCategory"))

    app_related_category: Optional[str] = None
    ride_related_category: Optional[str] = None
    ride_related_subcategory: Optional[str] = None
    ride_related_detail: Optional[str] = None

    if main_key.startswith("app related"):
        app_related_category = resolved_context.get("category")
    elif main_key.startswith("ride related"):
        ride_related_category = resolved_context.get("category")
        ride_related_subcategory = resolved_context.get("subcategory")
        ride_related_detail = resolved_context.get("detail")

    return {
        "issue_context": resolved_context,
        "app_related_category": app_related_category,
        "ride_related_category": ride_related_category,
        "ride_related_subcategory": ride_related_subcategory,
        "ride_related_detail": ride_related_detail,
    }

def build_ticket_routing_payload(
    conversation_id: Optional[str] = None,
    app_user_id: Optional[str] = None,
    issue_context: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    title: Optional[str] = None,
    transcript: Optional[str] = None,
    app_related_sub_category: Optional[Union[str, int]] = None,
    ride_related_category: Optional[str] = None,
    ride_related_subcategory: Optional[str] = None,
    ride_related_detail: Optional[str] = None,
) -> Dict[str, Any]:
    context = build_issue_context(
        issue_context=issue_context,
        reason=reason,
        title=title,
        transcript=transcript,
        app_related_category=str(app_related_sub_category) if app_related_sub_category else None,
        ride_related_category=ride_related_category,
        ride_related_subcategory=ride_related_subcategory,
        ride_related_detail=ride_related_detail
    )
    custom_fields: List[Dict[str, Any]] = []
    ticket_payload: Dict[str, Any] = {}

    append_custom_field(custom_fields, ZENDESK_CHAT_CONVERSATION_FIELD_ID, conversation_id)
    append_custom_field(custom_fields, NAME_FIELD_ID, context.get("name") or "Guest User")

    email_value = first_non_empty(
        context.get("email"),
        extract_named_value([r'email(?:_id)?\s*[:#-]\s*([^\s,;]+@[^\s,;]+)'], title, reason, transcript),
        app_user_id if looks_like_email(app_user_id) else None,
    )
    append_custom_field(custom_fields, EMAIL_ID_FIELD_ID, email_value)

    contact_value = first_non_empty(
        context.get("contact"),
        extract_named_value([r'contact\s*[:#-]\s*(\+?[0-9][0-9\s-]{6,})'], title, reason, transcript),
        app_user_id if looks_like_phone(app_user_id) and not looks_like_uuid(app_user_id) else None,
    )
    append_custom_field(custom_fields, CONTACT_FIELD_ID, contact_value)

    main_key = normalize_issue_key(context.get("mainCategory"))
    category_key = normalize_issue_key(context.get("category"))
    subcategory_key = normalize_issue_key(context.get("subcategory"))
    detail_key = normalize_issue_key(context.get("detail"))
    
    logger.info(f"Ticket routing - main_key={main_key}, category_key={category_key}, subcategory_key={subcategory_key}, detail_key={detail_key}")
    logger.info(f"Context: {context}")

    # Broaden main-category matching: accept "ride related" even if "issues" is missing
    is_ride_related = main_key.startswith("ride related")
    is_app_related = main_key.startswith("app related") or bool(app_related_sub_category)

    if is_app_related:
        form_id = safe_int(APP_RELATED_ISSUE_FORM_ID)
        if form_id:
            ticket_payload["ticket_form_id"] = form_id
        tag_value = str(app_related_sub_category) if app_related_sub_category else APP_RELATED_CATEGORY_TAGS.get(category_key)
        logger.info(
            f"[ROUTING] App branch: form_id={form_id} "
            f"APP_RELATED_SUB_CATEGORY field={APP_RELATED_SUB_CATEGORY} "
            f"category_key='{category_key}' tag='{tag_value}'"
        )
        append_custom_field(custom_fields, APP_RELATED_SUB_CATEGORY, tag_value)

    elif is_ride_related:
        if category_key == "fare and payment":
            form_id = safe_int(FARE_AND_PAYMENT_FORM_ID)
            if form_id:
                ticket_payload["ticket_form_id"] = form_id
            fare_tag = FARE_AND_PAYMENT_SUBCATEGORY_TAGS.get(subcategory_key)
            fare_field_id = safe_int(FARE_AND_PAYMENT_SUBCATEGORY_FIELD_ID)
            payment_tag = PAYMENT_MODE_TAGS.get(detail_key)
            logger.info(
                f"[ROUTING] Fare+Payment branch: "
                f"ticket_form_id={form_id} (env={FARE_AND_PAYMENT_FORM_ID}) | "
                f"fare_field_id={fare_field_id} (env={FARE_AND_PAYMENT_SUBCATEGORY_FIELD_ID}) | "
                f"subcategory_key='{subcategory_key}' -> fare_tag='{fare_tag}' | "
                f"payment_field_id={safe_int(PAYMENT_MODE_FIELD_ID)} (env={PAYMENT_MODE_FIELD_ID}) | "
                f"detail_key='{detail_key}' -> payment_tag='{payment_tag}'"
            )
            if fare_tag and not fare_field_id:
                logger.error(
                    "[ROUTING] FARE_AND_PAYMENT_SUBCATEGORY_FIELD_ID is not configured – "
                    "fare subcategory cannot be written to Zendesk"
                )
            append_custom_field(custom_fields, FARE_AND_PAYMENT_SUBCATEGORY_FIELD_ID, fare_tag)
            append_custom_field(custom_fields, PAYMENT_MODE_FIELD_ID, payment_tag)

        elif category_key == "find a lost item":
            form_id = safe_int(FIMD_A_LOST_ITEM_FORM_ID)
            if form_id:
                ticket_payload["ticket_form_id"] = form_id
            ride_id_val = first_non_empty(
                context.get("rideId"),
                extract_named_value([r'ride\s*id\s*[:#-]\s*([A-Za-z0-9_-]+)'], title, reason, transcript)
            )
            driver_name_val = first_non_empty(
                context.get("driverName"),
                extract_named_value([r'driver\s*name\s*[:#-]\s*([^\r\n]+)'], title, reason, transcript)
            )
            vehicle_number_val = first_non_empty(
                context.get("vehicleNumber"),
                extract_named_value([r'vehicle\s*(?:number|no)\s*[:#-]\s*([A-Za-z0-9 -]+)'], title, reason, transcript)
            )
            logger.info(
                f"[ROUTING] Lost Item branch: "
                f"ticket_form_id={form_id} (env={FIMD_A_LOST_ITEM_FORM_ID}) | "
                f"RIDE_ID field={RIDE_ID_FIELD_ID} value='{ride_id_val}' | "
                f"DRIVER_NAME field={DRIVER_NAME_FIELD_ID} value='{driver_name_val}' | "
                f"VEHICLE_NUMBER field={VEHICLE_NUMBER_FIELD_ID} value='{vehicle_number_val}'"
            )
            append_custom_field(custom_fields, RIDE_ID_FIELD_ID, ride_id_val)
            append_custom_field(custom_fields, DRIVER_NAME_FIELD_ID, driver_name_val)
            append_custom_field(custom_fields, VEHICLE_NUMBER_FIELD_ID, vehicle_number_val)

        elif category_key in ("vehicle related issue", "vehicle related") or category_key.startswith("vehicle related"):
            form_id = safe_int(VEHUICLE_AC_ISSUE_FORM_ID)
            if form_id:
                ticket_payload["ticket_form_id"] = form_id
            vehicle_tag = VEHICLE_ISSUE_TYPE_TAGS.get(subcategory_key)
            logger.info(
                f"[ROUTING] Vehicle branch: "
                f"ticket_form_id={form_id} (env={VEHUICLE_AC_ISSUE_FORM_ID}) | "
                f"VEHICLE_ISSUE_TYPE field={VEHICLE_ISSUE_TYPE_FIELD_ID} | "
                f"raw_subcategory='{context.get('subcategory')}' "
                f"subcategory_key='{subcategory_key}' -> tag='{vehicle_tag}'"
            )
            append_custom_field(custom_fields, VEHICLE_ISSUE_TYPE_FIELD_ID, vehicle_tag)

        elif category_key in ("safety related", "safety", "safety issue") or category_key.startswith("safety"):
            form_id = safe_int(SAFETY_ISSUE_FORM_ID)
            if form_id:
                ticket_payload["ticket_form_id"] = form_id
            safety_tag = SAFETY_ISSUE_TYPE_TAGS.get(subcategory_key)
            logger.info(
                f"[ROUTING] Safety branch: "
                f"ticket_form_id={form_id} (env={SAFETY_ISSUE_FORM_ID}) | "
                f"ESCALATION_TO_SAFETY_TEAM field={ESCALATION_TO_SAFETY_TEAM_FIELD_ID} (True) | "
                f"SAFETY_ISSUE_TYPE field={SAFETY_ISSUE_TYPE_FIELD_ID} | "
                f"raw_subcategory='{context.get('subcategory')}' "
                f"subcategory_key='{subcategory_key}' -> tag='{safety_tag}'"
            )
            append_custom_field(custom_fields, ESCALATION_TO_SAFETY_TEAM_FIELD_ID, True)
            append_custom_field(custom_fields, SAFETY_ISSUE_TYPE_FIELD_ID, safety_tag)

        else:
            logger.warning(
                f"[ROUTING] Ride branch: unmatched category_key='{category_key}' "
                f"(main_key='{main_key}') – no form or fields applied"
            )

    if custom_fields:
        ticket_payload["custom_fields"] = custom_fields
    return ticket_payload

def update_ticket_routing(
    ticket_id: str,
    issue_context: Optional[Dict[str, Any]] = None,
    conversation_id: Optional[str] = None,
    app_user_id: Optional[str] = None,
    reason: Optional[str] = None,
    title: Optional[str] = None,
    transcript: Optional[str] = None,
    app_related_sub_category: Optional[Union[str, int]] = None,
    ride_related_category: Optional[str] = None,
    ride_related_subcategory: Optional[str] = None,
    ride_related_detail: Optional[str] = None,
) -> bool:
    try:
        payload = build_ticket_routing_payload(
            conversation_id=conversation_id,
            app_user_id=app_user_id,
            issue_context=issue_context,
            reason=reason,
            title=title,
            transcript=transcript,
            app_related_sub_category=app_related_sub_category,
            ride_related_category=ride_related_category,
            ride_related_subcategory=ride_related_subcategory,
            ride_related_detail=ride_related_detail,
        )
        if not payload:
            return True
        url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
        auth = HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)

        form_id = payload.pop("ticket_form_id", None)
        custom_fields = payload.pop("custom_fields", None)
        succeeded = True
        fare_subcategory_field_id = safe_int(FARE_AND_PAYMENT_SUBCATEGORY_FIELD_ID)

        # ── Step 0: Write ZENDESK_CHAT_CONVERSATION_FIELD_ID FIRST ──────────────
        # This ensures the ticket is discoverable by conversation-ID search before
        # any ride-field updates run, eliminating the timing race condition.
        conv_field_id = safe_int(ZENDESK_CHAT_CONVERSATION_FIELD_ID)
        if conv_field_id and conversation_id:
            conv_field_written = False
            if custom_fields:
                for _f in custom_fields:
                    if safe_int(_f.get("id")) == conv_field_id and _f.get("value"):
                        conv_field_written = True
                        break
            if not conv_field_written:
                _conv_resp = requests.put(
                    url,
                    json={"ticket": {"custom_fields": [{"id": conv_field_id, "value": conversation_id}]}},
                    auth=auth,
                    timeout=15,
                )
                if _conv_resp.status_code != 200:
                    logger.error(
                        f"Pre-write of conversation field failed for ticket {ticket_id}: "
                        f"{_conv_resp.status_code} - {_conv_resp.text}"
                    )
        # ────────────────────────────────────────────────────────────────────────

        # ── Resolve all ride dropdown values against real Zendesk options ────
        DROPDOWN_FIELD_IDS: Set[int] = set(filter(None, [
            safe_int(FARE_AND_PAYMENT_SUBCATEGORY_FIELD_ID),
            safe_int(VEHICLE_ISSUE_TYPE_FIELD_ID),
            safe_int(SAFETY_ISSUE_TYPE_FIELD_ID),
            safe_int(PAYMENT_MODE_FIELD_ID),
            safe_int(APP_RELATED_SUB_CATEGORY),
        ]))
        if custom_fields:
            for field in custom_fields:
                fid = safe_int(field.get("id"))
                if not fid or fid not in DROPDOWN_FIELD_IDS:
                    continue
                if fid == fare_subcategory_field_id:
                    # Keep the specialised typo-aware resolver for fare
                    field["value"] = resolve_fare_subcategory_value(
                        fare_field_id=fare_subcategory_field_id,
                        fare_value=field.get("value"),
                        auth=auth,
                    )
                else:
                    field["value"] = resolve_dropdown_value(
                        field_id=fid,
                        desired_value=field.get("value"),
                        auth=auth,
                    )
        # ─────────────────────────────────────────────────────────────────────

        if form_id:
            form_response = requests.put(
                url,
                json={"ticket": {"ticket_form_id": form_id}},
                auth=auth,
                timeout=15
            )
            if form_response.status_code != 200:
                logger.error(
                    f"Ticket form update failed for {ticket_id}: "
                    f"{form_response.status_code} - {form_response.text}"
                )
                succeeded = False

        if custom_fields:
            fields_response = requests.put(
                url,
                json={"ticket": {"custom_fields": custom_fields}},
                auth=auth,
                timeout=15
            )
            if fields_response.status_code != 200:
                logger.error(
                    f"Ticket custom field update failed for {ticket_id}: "
                    f"{fields_response.status_code} - {fields_response.text}"
                )
                # Retry one field at a time so one invalid dropdown value doesn't block all fields.
                for field in custom_fields:
                    field_id = safe_int(field.get("id"))
                    if not field_id:
                        continue

                    candidate_values: List[Any] = [field.get("value")]
                    if field_id == fare_subcategory_field_id:
                        current_value = str(field.get("value") or "").strip()
                        if current_value == "multiple_debits_occurred":
                            candidate_values.append("multiple_debits_occured")
                        elif current_value == "multiple_debits_occured":
                            candidate_values.append("multiple_debits_occurred")

                    field_updated = False
                    for candidate_value in candidate_values:
                        single_field_payload = {"ticket": {"custom_fields": [{"id": field_id, "value": candidate_value}]}}
                        single_response = requests.put(
                            url,
                            json=single_field_payload,
                            auth=auth,
                            timeout=15
                        )
                        if single_response.status_code == 200:
                            field_updated = True
                            break
                        logger.error(
                            f"Ticket custom field partial update failed for {ticket_id}, field {field_id}, "
                            f"value '{candidate_value}': {single_response.status_code} - {single_response.text}"
                        )

                    if not field_updated:
                        succeeded = False

        if payload:
            extra_response = requests.put(
                url,
                json={"ticket": payload},
                auth=auth,
                timeout=15
            )
            if extra_response.status_code != 200:
                logger.error(
                    f"Ticket routing extra update failed for {ticket_id}: "
                    f"{extra_response.status_code} - {extra_response.text}"
                )
                succeeded = False

        return succeeded
    except Exception as e:
        logger.error(f"Ticket routing update error: {e}")
        return False

def build_conversation_transcript_body(title: str, transcript: Optional[str]) -> str:
    return "\n".join([
        f"Issue Path: {title}",
        "",
        "Conversation Transcript:",
        transcript or "No transcript captured."
    ])

def add_ticket_transcript_note(
    ticket_id: str,
    title: str,
    transcript: Optional[str],
    issue_context: Optional[Dict[str, Any]] = None,
    conversation_id: Optional[str] = None,
    app_user_id: Optional[str] = None,
    app_related_sub_category: Optional[Union[str, int]] = None,
) -> bool:
    try:
        payload = build_ticket_routing_payload(
            conversation_id=conversation_id,
            app_user_id=app_user_id,
            issue_context=issue_context,
            title=title,
            transcript=transcript,
            app_related_sub_category=app_related_sub_category,
        )
        payload["comment"] = {
            "body": build_conversation_transcript_body(title, transcript),
            "public": False
        }
        url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
        response = requests.put(
            url,
            json={"ticket": payload},
            auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN),
            timeout=15
        )
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Ticket transcript note error: {e}")
        return False

def create_sunshine_conversation_for_user(app_user_id: str) -> Optional[str]:
    try:
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        conv_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations"
        conv_payload = {"type": "personal", "participants": [{"userId": app_user_id}]}
        conv_response = requests.post(conv_url, json=conv_payload, auth=auth, timeout=15)
        if conv_response.status_code in [200, 201]:
            return conv_response.json().get("conversation", {}).get("id")
        logger.error(f"Failed to create Sunshine conversation: {conv_response.status_code} - {conv_response.text}")
        return None
    except Exception as e:
        logger.error(f"Sunshine conversation create error: {e}")
        return None

def normalize_transcript_entries(entries: Any) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    if not isinstance(entries, list):
        return normalized
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        speaker = strip_html_tags(str(entry.get("speaker", "") or "")).strip() or "Bot"
        text = str(entry.get("text", "") or "")
        text = text.replace('\u00a0', ' ').replace('\r', '')
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        if not text:
            continue
        normalized.append({"speaker": speaker, "text": text})
    return normalized

def sync_transcript_entries_to_sunshine(
    conversation_id: str,
    app_user_id: str,
    transcript_entries: List[Dict[str, str]]
) -> bool:
    if not transcript_entries:
        return True
    try:
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        msg_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
        for entry in transcript_entries:
            speaker = normalize_issue_key(entry.get("speaker"))
            text = entry.get("text", "")
            if not text:
                continue
            if speaker == "user":
                author = {"type": "user", "userId": app_user_id}
            elif speaker == "system":
                author = {"type": "business", "displayName": "System"}
            else:
                author = {"type": "business", "displayName": "Yatri Bandhu"}
            payload = {
                "author": author,
                "content": {"type": "text", "text": f"{SEEDED_TRANSCRIPT_PREFIX}{text}"},
                "metadata": {"seededTranscript": True}
            }
            response = requests.post(msg_url, json=payload, auth=auth, timeout=15)
            if response.status_code not in [200, 201]:
                logger.error(f"Transcript sync failed for {conversation_id}: {response.status_code} - {response.text}")
                return False
        return True
    except Exception as e:
        logger.error(f"Transcript sync error: {e}")
        return False

def build_pass_control_metadata(
    conversation_id: str,
    app_user_id: Optional[str],
    issue_context: Optional[Dict[str, Any]],
    reason: Optional[str],
    app_related_sub_category: Optional[Union[str, int]] = None,
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "dataCapture.systemField.tags": "escalated_from_bot",
        "dataCapture.systemField.requester.name": "Guest User"
    }
    routing_payload = build_ticket_routing_payload(
        conversation_id=conversation_id,
        app_user_id=app_user_id,
        issue_context=issue_context,
        reason=reason,
        app_related_sub_category=app_related_sub_category,
    )
    for field in routing_payload.get("custom_fields", []):
        field_id = field.get("id")
        field_value = field.get("value")
        if field_id and field_value not in (None, ""):
            metadata[f"dataCapture.ticketField.{field_id}"] = field_value
    return metadata

def silently_pass_conversation_to_agent(
    conversation_id: str,
    app_user_id: Optional[str],
    reason: Optional[str],
    issue_context: Optional[Dict[str, Any]],
    app_related_category: Optional[str],
) -> bool:
    try:
        context = build_issue_context(
            issue_context=issue_context,
            reason=reason,
            app_related_category=app_related_category,
        )

        main_key = normalize_issue_key(context.get("mainCategory"))
        ride_related_category = None
        ride_related_subcategory = None
        ride_related_detail = None
        if main_key.startswith("ride related"):
            ride_related_category = context.get("category")
            ride_related_subcategory = context.get("subcategory")
            ride_related_detail = context.get("detail")

        pending_data = {
            "conversation_id": conversation_id,
            "app_user_id": app_user_id,
            "reason": reason,
            "app_related_category": app_related_category,
            "ride_related_category": ride_related_category,
            "ride_related_subcategory": ride_related_subcategory,
            "ride_related_detail": ride_related_detail,
            "issue_context": context,
            "timestamp": datetime.now().isoformat(),
        }
        cache.set(f'pending_escalation_{conversation_id}', pending_data, timeout=900)
        cache_routing_context(conversation_id, pending_data)
        if app_related_category:
            cache.set(f'category_{conversation_id}', app_related_category, timeout=3600)
        if ride_related_category:
            cache.set(f'ride_category_{conversation_id}', ride_related_category, timeout=3600)

        enqueue_recent_escalation(
            {
                "conversation_id": conversation_id,
                "app_user_id": app_user_id,
                "reason": reason,
                "app_related_category": app_related_category,
                "ride_related_category": ride_related_category,
                "ride_related_subcategory": ride_related_subcategory,
                "ride_related_detail": ride_related_detail,
                "issue_context": context,
                "timestamp": time.time(),
            }
        )

        metadata = build_pass_control_metadata(
            conversation_id=conversation_id,
            app_user_id=app_user_id,
            issue_context=context,
            reason=reason,
            app_related_sub_category=APP_RELATED_CATEGORY_TAGS.get(normalize_issue_key(app_related_category)) if app_related_category else None,
        )

        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        pass_control_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/passControl"
        pass_control_payload = {"switchboardIntegration": "next", "metadata": metadata}
        response = requests.post(pass_control_url, json=pass_control_payload, auth=auth, timeout=15)
        if response.status_code != 200:
            logger.error(f"Silent passControl failed: {response.status_code} - {response.text}")
            return False
        return True
    except Exception as e:
        logger.error(f"Silent passControl error: {e}")
        return False

def resolve_ticket_id_for_conversation(
    conversation_id: str,
    timeout_seconds: float = 30.0,
    poll_interval: float = 1.0,
) -> Optional[str]:
    """
    Resolve the Zendesk ticket linked to a Sunshine conversation.

    Polls with exponential back-off (1 s -> 2 s -> 4 s -> 8 s cap).
    timeout_seconds raised to 30 s to handle slow Zendesk propagation.

    Search order:
      1. Cache hit  (set by store_conversation_ticket_mapping)
      2. Zendesk field-based search  (custom_field_<ID>:<conv_id>)
      3. Full-text fallback search   (type:ticket "<conv_id>")
    """
    try:
        cached_ticket_id = cache.get(f'conversation_{conversation_id}')
        if cached_ticket_id:
            logger.info(
                f"resolve_ticket: cache hit conversation={conversation_id} ticket={cached_ticket_id}"
            )
            return str(cached_ticket_id)

        if not all([ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN]):
            logger.error("resolve_ticket: missing Zendesk credentials")
            return None

        search_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/search.json"
        fallback_query = f'type:ticket "{conversation_id}"'
        auth = HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
        deadline = time.time() + max(timeout_seconds, 0)
        attempt = 0

        while True:
            attempt += 1
            # Primary: field-based search (only when field ID is configured)
            if ZENDESK_CHAT_CONVERSATION_FIELD_ID:
                search_query = (
                    f"custom_field_{ZENDESK_CHAT_CONVERSATION_FIELD_ID}:{conversation_id}"
                )
                response = requests.get(
                    search_url, params={"query": search_query}, auth=auth, timeout=15
                )
                logger.info(
                    f"resolve_ticket attempt={attempt} field_search status={response.status_code} "
                    f"conv={conversation_id}"
                )
                if response.status_code == 200:
                    for result in (response.json().get("results", []) or []):
                        ticket_id = str(result.get("id", "")).strip()
                        if ticket_id:
                            logger.info(f"resolve_ticket: found ticket={ticket_id} via field search")
                            store_conversation_ticket_mapping(conversation_id, ticket_id)
                            return ticket_id

            # Fallback: full-text search
            fallback_response = requests.get(
                search_url, params={"query": fallback_query}, auth=auth, timeout=15
            )
            if fallback_response.status_code == 200:
                for result in (fallback_response.json().get("results", []) or []):
                    if str(result.get("result_type", "ticket")).lower() != "ticket":
                        continue
                    ticket_id = str(result.get("id", "")).strip()
                    if ticket_id:
                        logger.info(f"resolve_ticket: found ticket={ticket_id} via fallback search")
                        store_conversation_ticket_mapping(conversation_id, ticket_id)
                        return ticket_id

            if time.time() >= deadline:
                logger.warning(
                    f"resolve_ticket: timed out after {attempt} attempts "
                    f"for conversation={conversation_id}"
                )
                break
            # Exponential back-off: 1 s -> 2 s -> 4 s -> 8 s cap
            sleep_time = min(poll_interval * (2 ** (attempt - 1)), 8.0)
            time.sleep(sleep_time)

        return None
    except Exception as e:
        logger.exception(f"resolve_ticket_id_for_conversation error: {e}")
        return None

def apply_ticket_routing_after_handoff(
    conversation_id: str,
    app_user_id: Optional[str],
    reason: Optional[str],
    issue_context: Optional[Dict[str, Any]],
    app_related_category: Optional[str] = None,
    ride_related_category: Optional[str] = None,
    ride_related_subcategory: Optional[str] = None,
    ride_related_detail: Optional[str] = None,
    title: Optional[str] = None,
    transcript: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve the Zendesk ticket created by Sunshine handoff and apply the
    mapped form/custom fields immediately, instead of waiting only on webhooks.
    """
    ticket_id = resolve_ticket_id_for_conversation(conversation_id)
    if not ticket_id:
        logger.warning(
            f"apply_ticket_routing_after_handoff: could not resolve ticket for "
            f"conversation={conversation_id}"
        )
        return {"ticket_id": None, "routing_updated": False}

    # Guarantee the conversation-field is written even before routing fields,
    # so any subsequent webhook or search can always find this ticket.
    conv_field_ok = set_ticket_conversation_field(ticket_id, conversation_id)
    logger.info(
        f"apply_ticket_routing_after_handoff: ticket={ticket_id} conv_field_written={conv_field_ok}"
    )

    routing_updated = update_ticket_routing(
        ticket_id,
        issue_context=issue_context,
        conversation_id=conversation_id,
        app_user_id=app_user_id,
        reason=reason,
        title=title,
        transcript=transcript,
        app_related_sub_category=APP_RELATED_CATEGORY_TAGS.get(normalize_issue_key(app_related_category)) if app_related_category else None,
        ride_related_category=ride_related_category,
        ride_related_subcategory=ride_related_subcategory,
        ride_related_detail=ride_related_detail,
    )
    if routing_updated:
        cache.set(f'ticket_status_{ticket_id}', 'active', timeout=86400)
    return {"ticket_id": ticket_id, "routing_updated": routing_updated}

def set_ticket_conversation_field(ticket_id: str, conversation_id: str) -> bool:
    """
    Persist the Sunshine conversation ID onto the Zendesk ticket so later
    webhook routing and searches can always find the same ticket.
    """
    try:
        field_id = safe_int(ZENDESK_CHAT_CONVERSATION_FIELD_ID)
        if not field_id or not ticket_id or not conversation_id:
            return False

        url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}.json"
        response = requests.put(
            url,
            json={"ticket": {"custom_fields": [{"id": field_id, "value": conversation_id}]}},
            auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN),
            timeout=15
        )
        return response.status_code == 200
    except Exception as e:
        logger.error(f"set_ticket_conversation_field error: {e}")
        return False

def forward_agent_message_to_websocket(conversation_id: str, message_text: str, agent_name: str = "Agent", choices: list = None, actions: list = None, received_timestamp: str = None) -> bool:
    """
    Send agent message to WebSocket clients via Django Channels group.
    
    Creates a WebSocket message with agent content and broadcasts it to all
    clients subscribed to the conversation's channel group.
    
    Args:
        conversation_id (str): Conversation ID to send message to
        message_text (str): Message content from agent
        agent_name (str): Display name of the agent (default: "Agent")
        choices (list, optional): CSAT/survey choice options if applicable
        actions (list, optional): Interactive actions/buttons if applicable
        received_timestamp (str, optional): ISO timestamp from Zendesk API when message was received
    
    Returns:
        bool: True if message sent successfully, False otherwise
    
    Raises:
        Silently logs exceptions and returns False
    """
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
                # Use Zendesk's received timestamp if available
                'received': received_timestamp,
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
    """
    Store bidirectional mapping between conversation and support ticket.
    
    Creates cached entries linking Sunshine conversation ID to Zendesk ticket ID
    and vice versa for quick lookup without database queries.
    
    Args:
        conversation_id (str): Zendesk Sunshine conversation ID
        ticket_id (str): Zendesk support ticket ID
    
    Returns:
        bool: True if mapping stored successfully, False on error
    """
    try:
        cache.set(f'conversation_{conversation_id}', ticket_id, timeout=604800)
        cache.set(f'ticket_{ticket_id}', conversation_id, timeout=604800)
        return True
    except Exception as e:
        logger.error(f"Failed to store mapping: {e}")
        return False

def update_user_viewing_status(conversation_id: str, is_viewing: bool) -> bool:
    """
    Track whether user is currently viewing the conversation.
    
    Stores or clears the viewing status flag in cache to indicate if user
    is actively reading the chat. Used to prevent unnecessary notifications.
    
    Args:
        conversation_id (str): Conversation ID to track
        is_viewing (bool): True if user is viewing, False to clear status
    
    Returns:
        bool: True if status updated successfully, False on error
    """
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
    """
    Cache conversation metadata for quick retrieval.
    
    Stores conversation information including last message, timestamp, and user ID
    in Redis cache with 7-day expiration for efficient conversation lookup.
    
    Args:
        conversation_id (str): Conversation ID to cache
        message_text (str): Latest message in conversation (first 100 chars stored)
        user_id (str): ID of user in conversation
    
    Returns:
        None
    """
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
    """
    Render main chat widget HTML template.
    
    Serves the index.html template with Sunshine App ID and debug settings
    injected as context variables for client-side initialization.
    
    Args:
        request (HttpRequest): Django HTTP request object
    
    Returns:
        HttpResponse: Rendered HTML template with chat widget
    """
    from django.conf import settings
    context = {'SUNSHINE_APP_ID': SUNSHINE_APP_ID, 'debug': settings.DEBUG}
    return render(request, 'index.html', context)

def verify_signature(payload: bytes, signature: str) -> bool:
    """
    Verify webhook authenticity using HMAC SHA256 signature.
    
    Compares the provided webhook signature with a calculated signature based on
    the payload and the Sunshine webhook signing secret. Uses constant-time
    comparison to prevent timing attacks.
    
    Args:
        payload (bytes): Raw webhook payload as bytes
        signature (str): Signature from webhook header (may include 'sha256=' prefix)
    
    Returns:
        bool: True if signature is valid, False otherwise
    
    Note:
        Requires SUNSHINE_WEBHOOK_SIGNING_SECRET environment variable
    """
    if not signature:
        return False
    if signature.startswith("sha256="):
        signature = signature.split("=", 1)[1]
    if not SECRET:
        logger.error("SUNSHINE_WEBHOOK_SIGNING_SECRET missing")
        return False
    calc = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, signature)

def create_zendesk_ticket(
    subject: str,
    description: str,
    conversation_id: Optional[str] = None,
    app_related_sub_category: Optional[Union[str, int]] = None,
    ticket_context: Optional[Dict[str, Any]] = None,
    app_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a support ticket in Zendesk and link to conversation.
    
    Creates a new support ticket with optional form and custom-field mappings.
    Stores the conversation-ticket mapping in cache for quick lookup.
    
    Args:
        subject (str): Ticket subject line
        description (str): Detailed ticket description/body
        conversation_id (str, optional): Sunshine conversation ID to link
        app_related_sub_category (str or int, optional): Category value for custom field
    
    Returns:
        Dict[str, Any]: API response containing created ticket data
    
    Raises:
        Logs all exceptions but doesn't raise; returns response dict with error info
    
    Note:
        Requires ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN environment variables
    """
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets.json"
    ticket = {"subject": subject, "comment": {"body": description}}
    ticket.update(
        build_ticket_routing_payload(
            conversation_id=conversation_id,
            app_user_id=app_user_id,
            issue_context=ticket_context,
            title=subject,
            transcript=description,
            app_related_sub_category=app_related_sub_category,
        )
    )

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
    """
    Obtain JWT access token from Zendesk Sunshine API using OAuth2 client credentials.
    
    Authenticates with Sunshine API to get a bearer token for subsequent API calls.
    Token is returned fresh each time (no caching) to ensure validity.
    
    Returns:
        Optional[str]: Access token string if successful, None if authentication fails
    
    Note:
        Requires SUNSHINE_API_KEY_ID and SUNSHINE_API_KEY_SECRET environment variables
    """
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
    """
    Initialize a new conversation or retrieve existing one.
    
    Creates a Sunshine user and associated conversation, or fetches an existing one.
    Supports forcing creation of a new conversation even if one exists.
    
    Request body (POST):
        - userId (str, optional): External user ID. Generated as UUID if not provided
        - forceNew (bool, optional): Force creation of new conversation (default: False)
    
    Returns:
        JsonResponse: {
            "appUserId": str,          # Sunshine app user ID
            "conversationId": str,     # Sunshine conversation ID
            "externalId": str          # External user ID used
        }
    
    Status codes:
        - 200: Success
        - 405: Method not allowed (non-POST)
        - 500: Missing SUNSHINE_APP_ID or internal errors
    """
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
    """
    Retrieve all messages in a Sunshine conversation.
    
    Fetches message history from Sunshine API including conversation metadata.
    
    Query parameters:
        - conversationId (str, required): Sunshine conversation ID
    
    Returns:
        JsonResponse: {
            "messages": [...],      # Array of message objects
            "conversation": {...}   # Conversation metadata
        }
    
    Status codes:
        - 200: Success
        - 400: Missing conversationId
        - 405: Method not allowed (non-GET)
        - 500: API errors
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
    """
    Send a user message to a Sunshine conversation.
    
    Posts a new message from the user to the conversation thread.
    Updates conversation cache on successful send.
    
    Request body (POST):
        - appUserId (str, required): Sunshine user ID
        - conversationId (str, required): Sunshine conversation ID
        - text (str, required): Message text to send
    
    Returns:
        JsonResponse: {"status": "sent", "data": {...}} on success
    
    Status codes:
        - 200: Message sent successfully
        - 400: Missing required fields or invalid JSON
        - 405: Method not allowed (non-POST)
        - 500: API or internal errors
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
    """
    Hand off conversation to a human agent and create Zendesk ticket.
    
    Escalates a conversation from the bot to an available agent. Sends an escalation
    message to the conversation, stores metadata in cache, and uses Sunshine's
    switchboard to pass control to the next available agent. Also creates a 
    corresponding Zendesk support ticket for tracking.
    
    Request body (POST):
        - conversationId (str, required): Sunshine conversation ID
        - appUserId (str, optional): Sunshine user ID
        - reason (str, optional): Escalation reason (default: "User requested agent support")
        - appRelatedCategory (str, optional): App category like "Location Not Found", "Unable to Login"
        - issueContext (dict, optional): Nested context with category, subcategory, detail:
            - For ride issues: {"mainCategory": "Ride Related Issues", "category": "Fare and Payment", 
              "subcategory": "Driver charged extra fare", "detail": "Cash"}
            - For app issues: {"mainCategory": "App Related Issues", "category": "Location Not Found"}
    
    Returns:
        JsonResponse: {"status": "escalated", "conversation_id": str, "category": str, 
                      "ticket_id": str, "routing_updated": bool}
    
    Status codes:
        - 200: Escalation successful
        - 400: Missing conversationId
        - 405: Method not allowed (non-POST)
        - 500: Escalation failed
    
    Categories supported:
        App: Location Not Found, Unable to Login, My App is Not Responding, Others
        Ride: Fare and Payment, Find a Lost Item, Vehicle Related, Safety Related
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        conversation_id = data.get("conversationId")
        app_user_id = data.get("appUserId")
        reason = data.get("reason", "User requested agent support")
        app_related_category = data.get("appRelatedCategory")
        issue_context = data.get("issueContext", {})
        
        # Extract ride parameters from top level or from issueContext
        ride_related_category = data.get("rideRelatedCategory") or issue_context.get("category")
        ride_related_subcategory = data.get("rideRelatedSubcategory") or issue_context.get("subcategory")
        ride_related_detail = data.get("rideRelatedDetail") or issue_context.get("detail")
        
        # For app issues, check issueContext as well
        if not app_related_category and issue_context.get("mainCategory") == "App Related Issues":
            app_related_category = issue_context.get("category")
        
        context = build_issue_context(
            issue_context=issue_context,
            reason=reason,
            app_related_category=app_related_category,
            ride_related_category=ride_related_category,
            ride_related_subcategory=ride_related_subcategory,
            ride_related_detail=ride_related_detail
        )
        
        if not conversation_id:
            return JsonResponse({"error": "Missing conversationId"}, status=400)

        if app_related_category:
            cache.set(f'category_{conversation_id}', app_related_category, timeout=3600)
        if ride_related_category:
            cache.set(f'ride_category_{conversation_id}', ride_related_category, timeout=3600)

        pending_data = {
            'conversation_id': conversation_id,
            'app_user_id': app_user_id,
            'reason': reason,
            'app_related_category': app_related_category,
            'ride_related_category': ride_related_category,
            'ride_related_subcategory': ride_related_subcategory,
            'ride_related_detail': ride_related_detail,
            'issue_context': context,
            'timestamp': datetime.now().isoformat()
        }
        cache.set(f'pending_escalation_{conversation_id}', pending_data, timeout=900)
        cache_routing_context(conversation_id, pending_data)

        app_id = SUNSHINE_APP_ID
        auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
        metadata = {"dataCapture.systemField.tags": "escalated_from_bot", "dataCapture.systemField.requester.name": "Guest User"}

        routing_payload = build_ticket_routing_payload(
            conversation_id=conversation_id,
            app_user_id=app_user_id,
            issue_context=issue_context,
            reason=reason,
            app_related_sub_category=APP_RELATED_CATEGORY_TAGS.get(normalize_issue_key(app_related_category)) if app_related_category else None,
            ride_related_category=ride_related_category,
            ride_related_subcategory=ride_related_subcategory,
            ride_related_detail=ride_related_detail,
        )
        for field in routing_payload.get("custom_fields", []):
            field_id = field.get("id")
            field_value = field.get("value")
            if field_id and field_value not in (None, ""):
                metadata[f"dataCapture.ticketField.{field_id}"] = field_value

        if app_user_id:
            msg_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{app_id}/conversations/{conversation_id}/messages"
            escalation_message = f"Escalation Reason: {reason}\n[Sunshine Conversation: {conversation_id}]"
            
            # Format category with proper display name
            if app_related_category:
                escalation_message += f"\nCategory: App related issue"
            
            msg_payload = {"author": {"type": "user", "userId": app_user_id}, "content": {"type": "text", "text": escalation_message}}
            msg_response = requests.post(msg_url, json=msg_payload, auth=auth)
            
            if msg_response.status_code in [200, 201]:
                time.sleep(0.5)

        # Queue before passControl so fast ticket.created events can map correctly.
        enqueue_recent_escalation({
            'conversation_id': conversation_id,
            'app_user_id': app_user_id,
            'reason': reason,
            'app_related_category': app_related_category,
            'ride_related_category': ride_related_category,
            'ride_related_subcategory': ride_related_subcategory,
            'ride_related_detail': ride_related_detail,
            'issue_context': context,
            'timestamp': time.time(),
        })

        pass_control_url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{app_id}/conversations/{conversation_id}/passControl"
        pass_control_payload = {"switchboardIntegration": "next", "metadata": metadata}
        pc_response = requests.post(pass_control_url, json=pass_control_payload, auth=auth)
        
        if pc_response.status_code != 200:
            return JsonResponse({"error": "Failed to escalate", "details": pc_response.text}, status=pc_response.status_code)

        routing_result = apply_ticket_routing_after_handoff(
            conversation_id=conversation_id,
            app_user_id=app_user_id,
            reason=reason,
            issue_context=context,
            app_related_category=app_related_category,
            ride_related_category=ride_related_category,
            ride_related_subcategory=ride_related_subcategory,
            ride_related_detail=ride_related_detail,
            title=reason,
        )

        return JsonResponse({
            "status": "escalated",
            "conversation_id": conversation_id,
            "category": app_related_category,
            "ticket_id": routing_result.get("ticket_id"),
            "routing_updated": routing_result.get("routing_updated", False),
        })
    except Exception as e:
        logger.exception("escalate_to_agent error")
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def create_conversation_ticket(request: HttpRequest) -> JsonResponse:
    """
    Silently escalate the current Sunshine conversation to Zendesk via
    passControl so the same conversation becomes the single ticket source.

    Request body (POST):
        - conversationId (str, required): Source Sunshine conversation ID
        - appUserId (str, required): Sunshine user ID
        - title (str, optional): Ticket subject/title
        - transcript (str, optional): Full conversation transcript from top to bottom
        - transcriptEntries (list, optional): Structured transcript entries
        - appRelatedCategory (str, optional): App-related category for custom field mapping

    Returns:
        JsonResponse: {"status": "created" | "existing", "conversation_id": str}
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
        source_conversation_id = str(data.get("conversationId", "")).strip()
        title = strip_html_tags(str(data.get("title", "Support Request"))).strip() or "Support Request"
        transcript = str(data.get("transcript", "")).strip()
        transcript_entries = normalize_transcript_entries(data.get("transcriptEntries"))
        seed_transcript = bool(data.get("seedTranscript"))
        if not transcript and transcript_entries:
            transcript = "\n\n".join(
                f"{entry.get('speaker', 'Bot')}: {entry.get('text', '')}"
                for entry in transcript_entries
                if entry.get("text")
            ).strip()
        app_user_id = str(data.get("appUserId", "")).strip() or None
        app_related_category = data.get("appRelatedCategory")
        issue_context = build_issue_context(
            issue_context=data.get("issueContext"),
            title=title,
            transcript=transcript,
            app_related_category=app_related_category
        )
        routing_parts = extract_routing_categories_from_context(issue_context)
        issue_context = routing_parts.get("issue_context") or issue_context
        app_related_category = app_related_category or routing_parts.get("app_related_category")
        ride_related_category = routing_parts.get("ride_related_category")
        ride_related_subcategory = routing_parts.get("ride_related_subcategory")
        ride_related_detail = routing_parts.get("ride_related_detail")

        main_key = normalize_issue_key((issue_context or {}).get("mainCategory"))
        ride_category_key = normalize_issue_key(ride_related_category or (issue_context or {}).get("category"))
        is_vehicle_related_flow = (
            main_key.startswith("ride related")
            and (
                ride_category_key in ("vehicle related issue", "vehicle related")
                or ride_category_key.startswith("vehicle related")
            )
        )
        should_seed_transcript = seed_transcript or is_vehicle_related_flow

        if not source_conversation_id:
            return JsonResponse({"error": "Missing conversationId"}, status=400)
        if not app_user_id:
            return JsonResponse({"error": "Missing appUserId"}, status=400)

        pending_data = {
            "conversation_id": source_conversation_id,
            "app_user_id": app_user_id,
            "reason": title,
            "app_related_category": app_related_category,
            "ride_related_category": ride_related_category,
            "ride_related_subcategory": ride_related_subcategory,
            "ride_related_detail": ride_related_detail,
            "issue_context": issue_context,
            "timestamp": datetime.now().isoformat(),
        }
        cache.set(f'pending_escalation_{source_conversation_id}', pending_data, timeout=900)
        cache_routing_context(source_conversation_id, pending_data)
        if app_related_category:
            cache.set(f'category_{source_conversation_id}', app_related_category, timeout=3600)
        if ride_related_category:
            cache.set(f'ride_category_{source_conversation_id}', ride_related_category, timeout=3600)
        enqueue_recent_escalation({
            "conversation_id": source_conversation_id,
            "app_user_id": app_user_id,
            "reason": title,
            "app_related_category": app_related_category,
            "ride_related_category": ride_related_category,
            "ride_related_subcategory": ride_related_subcategory,
            "ride_related_detail": ride_related_detail,
            "issue_context": issue_context,
            "timestamp": time.time(),
        })

        existing_handoff_conversation_id = cache.get(f'csat_handoff_{source_conversation_id}')
        if existing_handoff_conversation_id:
            routing_result = apply_ticket_routing_after_handoff(
                conversation_id=source_conversation_id,
                app_user_id=app_user_id,
                reason=title,
                issue_context=issue_context,
                app_related_category=app_related_category,
                ride_related_category=ride_related_category,
                ride_related_subcategory=ride_related_subcategory,
                ride_related_detail=ride_related_detail,
                title=title,
                transcript=transcript,
            )
            return JsonResponse({
                "status": "existing",
                "conversation_id": existing_handoff_conversation_id,
                "source_conversation_id": source_conversation_id,
                "appUserId": app_user_id,
                "ticket_id": routing_result.get("ticket_id"),
                "routing_updated": routing_result.get("routing_updated", False),
            })

        existing_ticket_id = resolve_ticket_id_for_conversation(source_conversation_id)
        if not existing_ticket_id:
            if should_seed_transcript and transcript_entries:
                sync_transcript_entries_to_sunshine(
                    source_conversation_id,
                    app_user_id,
                    transcript_entries
                )
            passed = silently_pass_conversation_to_agent(
                conversation_id=source_conversation_id,
                app_user_id=app_user_id,
                reason=title,
                issue_context=issue_context,
                app_related_category=app_related_category
            )
            if not passed:
                return JsonResponse({"error": "Failed to hand off Sunshine conversation"}, status=500)

        cache.set(f'csat_handoff_{source_conversation_id}', source_conversation_id, timeout=604800)

        routing_result = apply_ticket_routing_after_handoff(
            conversation_id=source_conversation_id,
            app_user_id=app_user_id,
            reason=title,
            issue_context=issue_context,
            app_related_category=app_related_category,
            ride_related_category=ride_related_category,
            ride_related_subcategory=ride_related_subcategory,
            ride_related_detail=ride_related_detail,
            title=title,
            transcript=transcript,
        )

        return JsonResponse({
            "status": "created",
            "conversation_id": source_conversation_id,
            "source_conversation_id": source_conversation_id,
            "appUserId": app_user_id,
            "ticket_id": routing_result.get("ticket_id"),
            "routing_updated": routing_result.get("routing_updated", False),
        })
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.exception("create_conversation_ticket error")
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
def webhook_message(request: HttpRequest) -> Union[JsonResponse, HttpResponseForbidden]:
    """
    Main webhook endpoint for Zendesk Sunshine Conversations events.
    
    Routes incoming webhook events to appropriate handler functions based on event
    trigger type. Validates webhook signature for security. Supports both single
    event and batch (events array) payloads.
    
    Supported triggers:
        - conversation:message: New message in conversation
        - switchboard:passControl: Agent taking over conversation
        - switchboard:releaseControl: Agent ending conversation
        - switchboard:acceptControl: Agent accepting control
        - participant:join: Participant joining conversation
        - participant:leave: Participant leaving conversation
        - conversation:read: Conversation marked as read
        - user:typing: Typing indicator from agent
    
    Query headers:
        - X-Hub-Signature or x-hub-signature: HMAC SHA256 signature
        - X-Api-Key: Optional API key to bypass signature in debug mode
    
    Returns:
        Union[JsonResponse, HttpResponseForbidden]:
            - JsonResponse: {"status": "received"} if valid
            - HttpResponseForbidden: If signature invalid or JSON parse error
    """
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
    """
    Handle agent taking control of conversation via switchboard passControl event.
    
    Extracts ticket ID from webhook metadata, stores conversation-ticket mapping,
    updates custom fields if category is available, and marks ticket as active
    in cache for tracking.
    
    Args:
        event_data (Dict[str, Any]): Switchboard:passControl webhook event payload
    
    Returns:
        None
    
    Side effects:
        - Stores/updates conversation-ticket mapping in cache
        - Updates Zendesk ticket custom field with app category
        - Sets ticket status to 'active' in cache
    """
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
            issue_context = None
            app_user_id = None
            if pending_data:
                app_related_category = pending_data.get('app_related_category')
                issue_context = pending_data.get('issue_context')
                app_user_id = pending_data.get('app_user_id')
            store_conversation_ticket_mapping(conversation_id, ticket_id)
            update_ticket_routing(
                ticket_id,
                issue_context=issue_context,
                conversation_id=conversation_id,
                app_user_id=app_user_id,
                reason=pending_data.get('reason') if pending_data else None,
                app_related_sub_category=APP_RELATED_CATEGORY_TAGS.get(normalize_issue_key(app_related_category)) if app_related_category else None,
            )
            cache.set(f'ticket_status_{ticket_id}', 'active', timeout=86400)

def update_ticket_custom_field(ticket_id: str, category: str) -> bool:
    """
    Update Zendesk ticket custom field with application category.
    
    Maps user-friendly category names to internal category codes and updates
    the corresponding Zendesk custom field via API.
    
    Args:
        ticket_id (str): Zendesk ticket ID to update
        category (str): Category name to set
    
    Returns:
        bool: True if update successful (HTTP 200), False otherwise
    
    Category mappings:
        - Location Not Found or Inaccurate -> location_not_found_or_inaccurate
        - Unable to Login -> unable_to_login
        - My App is Not Responding -> my_app_is_not_responding
        - Others -> others
    
    Note:
        Requires APP_RELATED_SUB_CATEGORY environment variable with custom field ID
    """
    tag_value = APP_RELATED_CATEGORY_TAGS.get(normalize_issue_key(category), "others")
    return update_ticket_routing(
        ticket_id,
        issue_context={"mainCategory": "App Related Issues", "category": category},
        app_related_sub_category=tag_value,
    )

def handle_user_typing(event_data: Dict[str, Any]) -> None:
    """
    Forward agent typing indicator to WebSocket clients.
    
    Detects when an agent is typing and broadcasts a typing indicator event
    to all connected WebSocket clients in the conversation.
    
    Args:
        event_data (Dict[str, Any]): user:typing webhook event payload
    
    Returns:
        None
    
    Side effects:
        - Broadcasts agent_typing message to conversation WebSocket group
    """
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
    """
    Send confirmation message when agent accepts conversation.
    
    Posts a system message confirming that an agent has accepted the escalation
    and will be responding shortly.
    
    Args:
        event_data (Dict[str, Any]): switchboard:acceptControl webhook event payload
    
    Returns:
        None
    
    Side effects:
        - Posts system message to Sunshine conversation
    """
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
    """
    Notify user when agent reads messages.
    
    Detects when an agent reads/views the conversation and sends a system message
    confirming the agent connection.
    
    Args:
        event_data (Dict[str, Any]): conversation:read webhook event payload
    
    Returns:
        None
    
    Side effects:
        - Posts "An agent connected" system message to conversation
    """
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
    """
    Notify user when agent joins conversation.
    
    Detects when an agent participant joins the conversation and sends a system
    message with the agent's name to inform the user.
    
    Args:
        event_data (Dict[str, Any]): participant:join webhook event payload
    
    Returns:
        None
    
    Side effects:
        - Posts "[Agent Name] has joined the conversation" system message
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
            try:
                auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
                url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                payload = {"author": {"type": "business", "displayName": "System"}, "content": {"type": "text", "text": f"{agent_name} has joined the conversation"}}
                requests.post(url, json=payload, auth=auth)
            except Exception as e:
                logger.error(f"Join notification error: {e}")

def handle_participant_leave(event_data: Dict[str, Any]) -> None:
    """
    Notify user when agent leaves conversation.
    
    Detects when an agent participant leaves the conversation and sends a system
    message with the agent's name to inform the user of disconnection.
    
    Args:
        event_data (Dict[str, Any]): participant:leave webhook event payload
    
    Returns:
        None
    
    Side effects:
        - Posts "[Agent Name] has left the conversation" system message
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
            try:
                auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
                url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
                payload = {"author": {"type": "business", "displayName": "System"}, "content": {"type": "text", "text": f"{agent_name} has left the conversation"}}
                requests.post(url, json=payload, auth=auth)
            except Exception as e:
                logger.error(f"Leave notification error: {e}")

def process_message_event(event_data: Dict[str, Any]) -> None:
    """
    Process and route incoming messages from Sunshine conversations.
    
    Determines message source (agent, user, or bot) and handles accordingly:
    - Agent messages: Forward to WebSocket, send notifications, trigger CSAT if needed
    - Bot messages: Extract category and auto-create Zendesk tickets
    - System/Log entries: Ignore
    
    Handles unread badge tracking and notification delivery for agent messages
    when user is not actively viewing the conversation.
    
    Args:
        event_data (Dict[str, Any]): conversation:message webhook event payload
    
    Returns:
        None
    
    Side effects:
        - Forwards agent messages to WebSocket clients
        - Updates unread message counter in cache
        - Sends notifications via SSE
        - Creates Zendesk tickets for bot responses with category extraction
    """
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
        if is_seeded_transcript_message(message, text):
            return
        text = strip_seeded_transcript_prefix(text)
        
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
                    'choices': choices if choices else None,
                    'actions': actions if actions else None,
                    'isInteractive': bool(choices or actions)
                })
            
            if is_conversation_log_entry(text):
                return
            # Pass the Zendesk received timestamp from the message
            received_ts = message.get('received')
            forward_agent_message_to_websocket(conversation_id, text, agent_name, choices=choices, actions=actions, received_timestamp=received_ts)
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
                existing_ticket_id = cache.get(f'conversation_{conversation_id}')
                if app_related_tag and not existing_ticket_id:
                    create_zendesk_ticket(
                        subject=f"Conversation {conversation_id}",
                        description=f"User {app_user_id} said: {text}",
                        conversation_id=conversation_id,
                        app_related_sub_category=app_related_tag,
                        ticket_context=build_issue_context(reason=text, app_related_category=app_related_tag),
                        app_user_id=app_user_id,
                    )
            except Exception as e:
                logger.error(f"Failed to create ticket: {e}")
    except Exception as e:
        logger.exception(f"process_message_event error: {e}")

@csrf_exempt
def update_viewing_status(request: HttpRequest) -> JsonResponse:
    """
    Update whether user is actively viewing conversation.
    
    Sets or clears the user viewing flag to control notification delivery.
    When user is viewing, unread badges and notifications are not sent.
    
    Request body (POST):
        - conversationId (str, required): Conversation ID
        - isViewing (bool, required): True if user is viewing, False otherwise
    
    Returns:
        JsonResponse: {"status": "updated", "conversationId": str}
    
    Status codes:
        - 200: Success
        - 400: Missing conversationId
        - 405: Method not allowed (non-POST)
        - 500: Internal errors
    """
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
    """
    Clear unread message counter for conversation.
    
    Resets the unread badge count to zero when user views messages.
    
    Request body (POST):
        - conversationId (str, required): Conversation ID
    
    Returns:
        JsonResponse: {"status": "cleared", "conversationId": str}
    
    Status codes:
        - 200: Success
        - 400: Missing conversationId
        - 405: Method not allowed (non-POST)
        - 500: Internal errors
    """
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
    """
    Upload file attachment and optional text message to conversation.
    
    Handles multipart file uploads by posting to Sunshine attachments endpoint,
    then adds file message and optional text message to conversation.
    Includes retry logic for transient failures.
    
    Request (multipart POST):
        - file (File, required): File to upload
        - conversationId (str, required): Sunshine conversation ID
        - appUserId (str, required): Sunshine user ID
        - message (str, optional): Additional text message to send
    
    Returns:
        JsonResponse: {"status": "ok"} on success
    
    Status codes:
        - 200: File and messages sent successfully
        - 400: Missing required fields
        - 405: Method not allowed (non-POST)
        - 500: File upload or messaging errors
    
    Side effects:
        - Uploads file to Sunshine storage
        - Posts file message to conversation
        - Posts text message if provided
    """
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
    """
    Handle agent ending conversation session.
    
    Detects when agent ends session and optionally sends goodbye message.
    Checks ticket status to determine if session was marked as resolved.
    
    Args:
        event_data (Dict[str, Any]): switchboard:releaseControl webhook event payload
        show_to_user (bool): Whether to send message to user (default: False)
    
    Returns:
        None
    
    Side effects:
        - Posts goodbye message if ticket is marked as 'solved'
        - Logs any errors without raising
    """
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
    """
    Main webhook endpoint for Zendesk Support events.
    
    Routes incoming Zendesk webhooks to appropriate handlers based on payload format:
    - Notification format (event field): handle_notification_webhook()
    - Ticket comment format (ticket + comment): handle_ticket_comment_webhook()
    - Events format (events array): handle_event_webhook()
    
    Detects ticket ID from various payload formats for routing.
    
    Request body (POST):
        JSON webhook payload from Zendesk
    
    Returns:
        JsonResponse: Status of webhook processing
    
    Status codes:
        - 200: Webhook processed or ignored safely
        - 400: Invalid JSON format
        - 405: Method not allowed (non-POST)
        - 500: Processing errors
    """
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
    """
    Process ticket comment webhook in standard format.
    
    Extracts agent/admin comments from Zendesk tickets and forwards to linked
    Sunshine conversation via WebSocket and API. Filters out conversation log
    entries and non-agent comments.
    
    Args:
        data (Dict[str, Any]): Zendesk ticket comment webhook payload with 'ticket' and 'comment' fields
    
    Returns:
        JsonResponse with status indicating processing result:
            - "forwarded": Comment successfully sent to conversation
            - "no_ticket_id": Ticket ID not found in payload
            - "ignored_non_agent": Comment from non-agent/admin user
            - "ignored_empty": Comment has no body text
            - "ignored_conversation_log": Detected as log entry, not user message
            - "no_conversation_mapping": No Sunshine conversation found for ticket
            - "forward_failed": API error sending to Sunshine
    
    Status codes:
        - 200: Processed (any outcome)
        - 400: Missing ticket ID
        - 500: Forward failed
    """
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
    """
    Process Zendesk webhook in events array format.
    
    Iterates through events array looking for 'Comment' type events.
    Extracts comment text and forwards to linked Sunshine conversation.
    Filters conversation log entries.
    
    Args:
        data (Dict[str, Any]): Zendesk events format webhook with 'events' array
    
    Returns:
        JsonResponse: {"status": "processed_events"}
    
    Status codes:
        - 200: Events processed (even if no matching events found)
        - 500: Error during processing
    """
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
    """
    Process Zendesk webhook notification event (ticket.created, ticket.comment_added, or ticket.solved).
    
    Handles three scenarios:
    1. ticket.created: Finds linked Sunshine conversation and applies mapped form/custom fields
    2. ticket.comment_added: Extracts agent comment, finds linked Sunshine conversation,
       and forwards message to conversation chat
    3. ticket.solved: Sends session end message to user
    
    Searches for conversation ID in multiple locations:
    - Custom field value (ZENDESK_CHAT_CONVERSATION_FIELD_ID)
    - Ticket description and webhook payload text patterns
    - Pending escalation cache with timestamp matching
    
    Args:
        data (Dict[str, Any]): Zendesk notification webhook payload
    
    Returns:
        JsonResponse with detailed status:
            - "mapping_stored": Conversation mapped and tracked
            - "ticket_updated": Custom field updated with category
            - "no_conversation_found": Ticket created but no conversation found
            - "ignored_user_comment": Non-staff comment, ignored
            - "ignored_conversation_log": Log entry, not user comment
            - "ticket_solved_processed": Ticket solved event processed
            - "processed_notification": Event processed
    
    Status codes:
        - 200: Processed (any outcome)
        - 500: Error during processing
    """
    try:
        event_type = data.get('type', '')
        event_data = data.get('event', {})

        if 'ticket.created' in event_type:
            ticket_id = None
            if 'ticket' in event_data:
                ticket_id = str(event_data['ticket'].get('id', ''))
            elif 'ticket_id' in event_data:
                ticket_id = str(event_data['ticket_id'])
            if not ticket_id:
                ticket_id = extract_ticket_id_from_data(data)
            if not ticket_id:
                return JsonResponse({"status": "no_ticket_id_in_created"})

            # Prefer a direct conversation lookup from the created ticket itself.
            # If this succeeds, it is more reliable than queue heuristics.
            direct_conversation_id = resolve_conversation_id_for_ticket(ticket_id)
            if not direct_conversation_id:
                # Zendesk may apply custom fields slightly after ticket.created; retry briefly.
                for attempt in range(1, 4):
                    time.sleep(1.0)
                    direct_conversation_id = resolve_conversation_id_for_ticket(ticket_id)
                    if direct_conversation_id:
                        logger.info(
                            f"ticket.created direct mapping resolved on retry={attempt} "
                            f"conversation={direct_conversation_id} ticket={ticket_id}"
                        )
                        break
            if direct_conversation_id:
                logger.info(
                    f"ticket.created direct mapping conversation={direct_conversation_id} ticket={ticket_id}"
                )
                result = update_ticket_routing_from_conversation_mapping(ticket_id)
                if result.get("status") == "ticket_updated":
                    conversation_id = result.get("conversation_id")
                    if conversation_id:
                        cache.delete(f'pending_escalation_{conversation_id}')
                return JsonResponse(result)

            recent_escalations = cache.get(RECENT_ESCALATION_QUEUE_KEY, []) or []
            ticket_created_at = time.time()
            found_escalation = None
            valid_escalations: List[Dict[str, Any]] = []

            for escalation in recent_escalations:
                try:
                    conv_id = str(escalation.get('conversation_id', '')).strip()
                    ts = float(escalation.get('timestamp') or 0)
                except Exception:
                    continue
                if not conv_id:
                    continue
                age = ticket_created_at - ts
                if 0 <= age <= RECENT_ESCALATION_QUEUE_TTL_SECONDS:
                    valid_escalations.append(escalation)

            for escalation in reversed(valid_escalations):
                conversation_id = str(escalation.get('conversation_id', '')).strip()
                ts = float(escalation.get('timestamp') or 0)
                age = ticket_created_at - ts
                if not conversation_id:
                    continue
                if age < 0 or age > RECENT_ESCALATION_MATCH_WINDOW_SECONDS:
                    continue
                found_escalation = escalation
                break

            if found_escalation:
                conversation_id = str(found_escalation.get('conversation_id', '')).strip()
                cache.set(f'conversation_{conversation_id}', ticket_id, timeout=86400)
                cache.set(f'ticket_{ticket_id}', conversation_id, timeout=86400)
                cache.set(f'pending_escalation_{conversation_id}', found_escalation, timeout=3600)
                cache_routing_context(conversation_id, found_escalation)
                valid_escalations = [e for e in valid_escalations if e is not found_escalation]
                logger.info(
                    f"ticket.created matched queue conversation={conversation_id} ticket={ticket_id}"
                )
            else:
                logger.info(f"ticket.created had no queue match for ticket={ticket_id}")

            cache.set(
                RECENT_ESCALATION_QUEUE_KEY,
                valid_escalations[-RECENT_ESCALATION_QUEUE_MAX:],
                timeout=RECENT_ESCALATION_QUEUE_TTL_SECONDS,
            )

            result = update_ticket_routing_from_conversation_mapping(ticket_id)
            if result.get("status") == "ticket_updated":
                conversation_id = result.get("conversation_id")
                if conversation_id:
                    cache.delete(f'pending_escalation_{conversation_id}')
            return JsonResponse(result)

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

            routing_result = update_ticket_routing_from_conversation_mapping(ticket_id)
            conversation_id = routing_result.get("conversation_id")
            if not conversation_id:
                return JsonResponse(routing_result)

            agent_name = "Support Agent"
            try:
                if isinstance(comment_author, dict):
                    agent_name = (
                        comment_author.get('name')
                        or comment_author.get('display_name')
                        or comment_author.get('email')
                        or agent_name
                    )
            except Exception:
                pass

            auth = HTTPBasicAuth(SUNSHINE_API_KEY_ID, SUNSHINE_API_KEY_SECRET)
            url = f"{SUNSHINE_API_BASE_URL}/v2/apps/{SUNSHINE_APP_ID}/conversations/{conversation_id}/messages"
            payload = {
                "author": {"type": "business", "displayName": agent_name},
                "content": {"type": "text", "text": comment_body}
            }
            response = requests.post(url, json=payload, auth=auth, timeout=15)
            if response.status_code in [200, 201]:
                forward_agent_message_to_websocket(conversation_id, comment_body, agent_name)
                return JsonResponse({
                    "status": "forwarded",
                    "ticket_id": ticket_id,
                    "conversation_id": conversation_id,
                    "agent_name": agent_name,
                    "routing_status": routing_result.get("status"),
                })
            return JsonResponse({
                "status": "routing_updated_but_forward_failed",
                "ticket_id": ticket_id,
                "conversation_id": conversation_id,
                "error": response.text,
            })

        if 'ticket.solved' in event_type:
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
                payload = {
                    "author": {"type": "business", "displayName": "System"},
                    "content": {"type": "text", "text": "The agent has ended the session. Type a message to start a new ticket."}
                }
                requests.post(url, json=payload, auth=auth)
            return JsonResponse({"status": "ticket_solved_processed", "ticket_id": ticket_id})

        return JsonResponse({"status": "processed_notification"})
    except Exception as e:
        logger.exception(f"handle_notification_webhook error: {e}")
        return JsonResponse({"error": str(e)}, status=500)


def extract_ticket_id_from_data(data: Dict[str, Any]) -> Optional[str]:
    """
    Extract ticket ID from various Zendesk webhook payload formats.

    Attempts extraction in order of preference:
    1. Direct ticket object id
    2. ticket_id in event data
    3. detail.id
    4. events[].ticket_id
    5. JSON string regex pattern matching
    """
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


@csrf_exempt
def cancellation_charges_waive_off(request: HttpRequest) -> JsonResponse:
    """
    Evaluate cancellation-waiver reason and persist ride context so the later
    create-ticket flow has deterministic data for routing.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    conversation_id = str(data.get("conversationId", "")).strip()
    app_user_id = str(data.get("appUserId", "")).strip() or None
    reason = strip_html_tags(str(data.get("reason", ""))).strip()
    normalized_reason = normalize_issue_key(reason)

    approved_reasons = {
        "driver not moving",
        "driver asked to cancel",
        "could not connect with driver",
        "driver was impolite",
    }
    waived_off = normalized_reason in approved_reasons

    current_path = "Ride Related Issues > Fare and Payment > Cancellation Charges"
    if reason:
        current_path = f"{current_path} > {reason}"

    issue_context = build_issue_context(
        issue_context={
            "mainCategory": "Ride Related Issues",
            "category": "Fare and Payment",
            "subcategory": "Cancellation Charges",
            "detail": reason,
            "currentPath": current_path,
        },
        reason=reason,
        ride_related_category="Fare and Payment",
        ride_related_subcategory="Cancellation Charges",
        ride_related_detail=reason,
    )

    if conversation_id:
        existing_pending = cache.get(f'pending_escalation_{conversation_id}') or {}
        existing_pending.update(
            {
                "conversation_id": conversation_id,
                "app_user_id": app_user_id,
                "reason": reason or existing_pending.get("reason") or "Cancellation Charges",
                "app_related_category": None,
                "ride_related_category": "Fare and Payment",
                "ride_related_subcategory": "Cancellation Charges",
                "ride_related_detail": reason,
                "issue_context": issue_context,
                "timestamp": datetime.now().isoformat(),
            }
        )
        cache.set(f'pending_escalation_{conversation_id}', existing_pending, timeout=900)
        cache_routing_context(conversation_id, existing_pending)
        cache.set(f'ride_category_{conversation_id}', "Fare and Payment", timeout=3600)
        enqueue_recent_escalation(
            {
                "conversation_id": conversation_id,
                "app_user_id": app_user_id,
                "reason": reason,
                "app_related_category": None,
                "ride_related_category": "Fare and Payment",
                "ride_related_subcategory": "Cancellation Charges",
                "ride_related_detail": reason,
                "issue_context": issue_context,
                "timestamp": time.time(),
            }
        )

    logger.info(
        f"Cancellation waive-off evaluated conv={conversation_id or 'n/a'} "
        f"reason='{reason}' waived={waived_off}"
    )
    return JsonResponse({"waivedOffSuccess": waived_off, "reason": reason})

def resolve_conversation_id_for_ticket(ticket_id: str) -> Optional[str]:
    """
    Look up Sunshine conversation ID for a Zendesk ticket.
    
    Searches in order:
    1. Cache lookup (fast path)
    2. Zendesk API custom field (ZENDESK_CHAT_CONVERSATION_FIELD_ID)
    
    Stores successful lookup in cache for future queries.
    
    Args:
        ticket_id (str): Zendesk ticket ID
    
    Returns:
        Optional[str]: Sunshine conversation ID if found, None otherwise
    
    Note:
        Requires Zendesk API credentials and custom field configuration
    """
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

        # Fallback 1: parse conversation id from ticket subject/description text.
        from_ticket_text = extract_conversation_id_from_text(
            ticket_obj.get('subject'),
            ticket_obj.get('description'),
            ticket_obj.get('raw_subject')
        )
        if from_ticket_text:
            store_conversation_ticket_mapping(from_ticket_text, str(ticket_id))
            return from_ticket_text

        # Fallback 2: parse from ticket comments where we include "[Sunshine Conversation: ...]".
        comments_url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/tickets/{ticket_id}/comments.json"
        comments_resp = requests.get(
            comments_url,
            auth=HTTPBasicAuth(f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN),
            timeout=10
        )
        if comments_resp.status_code == 200:
            comments = comments_resp.json().get('comments', []) or []
            for comment in comments:
                from_comment = extract_conversation_id_from_text(
                    comment.get('body'),
                    comment.get('plain_body'),
                    comment.get('html_body')
                )
                if from_comment:
                    store_conversation_ticket_mapping(from_comment, str(ticket_id))
                    return from_comment

        return None
    except Exception as e:
        logger.exception(f"resolve_conversation_id_for_ticket error: {e}")
        return None

def update_ticket_routing_from_conversation_mapping(ticket_id: str) -> Dict[str, Any]:
    """
    Resolve a ticket back to its Sunshine conversation using the shared
    ZENDESK_CHAT_CONVERSATION_FIELD_ID custom field, then apply the correct
    Zendesk form and custom-field mapping for the stored issue context.
    """
    conversation_id = resolve_conversation_id_for_ticket(ticket_id)

    if not conversation_id:
        return {
            "status": "no_conversation_found",
            "ticket_id": ticket_id,
            "message": "Ticket created but no conversation mapping found",
        }

    set_ticket_conversation_field(ticket_id, conversation_id)
    store_conversation_ticket_mapping(conversation_id, ticket_id)
    pending_data = cache.get(f'pending_escalation_{conversation_id}')
    cached_routing_context = cache.get(f'{ROUTING_CONTEXT_CACHE_PREFIX}{conversation_id}') or {}
    app_related_category = None
    ride_related_category = None
    ride_related_subcategory = None
    ride_related_detail = None
    issue_context = None
    app_user_id = None

    if pending_data:
        app_related_category = pending_data.get('app_related_category')
        ride_related_category = pending_data.get('ride_related_category')
        ride_related_subcategory = pending_data.get('ride_related_subcategory')
        ride_related_detail = pending_data.get('ride_related_detail')
        issue_context = pending_data.get('issue_context')
        app_user_id = pending_data.get('app_user_id')
    else:
        app_related_category = cache.get(f'category_{conversation_id}')
        ride_related_category = cache.get(f'ride_category_{conversation_id}')

    if cached_routing_context:
        app_related_category = app_related_category or cached_routing_context.get('app_related_category')
        ride_related_category = ride_related_category or cached_routing_context.get('ride_related_category')
        ride_related_subcategory = ride_related_subcategory or cached_routing_context.get('ride_related_subcategory')
        ride_related_detail = ride_related_detail or cached_routing_context.get('ride_related_detail')
        issue_context = issue_context or cached_routing_context.get('issue_context')
        app_user_id = app_user_id or cached_routing_context.get('app_user_id')

    if not issue_context:
        issue_context = build_issue_context(
            issue_context=None,
            app_related_category=app_related_category,
            ride_related_category=ride_related_category,
            ride_related_subcategory=ride_related_subcategory,
            ride_related_detail=ride_related_detail,
        )

    success = update_ticket_routing(
        ticket_id,
        issue_context=issue_context,
        conversation_id=conversation_id,
        app_user_id=app_user_id,
        reason=pending_data.get('reason') if pending_data else None,
        app_related_sub_category=APP_RELATED_CATEGORY_TAGS.get(normalize_issue_key(app_related_category)) if app_related_category else None,
        ride_related_category=ride_related_category,
        ride_related_subcategory=ride_related_subcategory,
        ride_related_detail=ride_related_detail,
    )
    if success:
        cache.set(f'ticket_status_{ticket_id}', 'active', timeout=86400)
        return {
            "status": "ticket_updated",
            "ticket_id": ticket_id,
            "conversation_id": conversation_id,
            "app_related_category": app_related_category,
            "message": "Ticket routing updated successfully",
        }

    return {
        "status": "mapping_stored_but_update_failed",
        "ticket_id": ticket_id,
        "conversation_id": conversation_id,
        "app_related_category": app_related_category,
        "error": "update_ticket_routing returned False",
    }

@csrf_exempt
def get_full_chat_history(request: HttpRequest) -> JsonResponse:
    """
    Retrieve combined message history from Sunshine and Zendesk.
    
    Fetches messages from two sources and deduplicates using message fingerprints
    (author type, timestamp, text content):
    1. Sunshine API: Direct conversation messages
    2. Zendesk: Conversation log via associated ticket
    
    Deduplicates messages to prevent showing duplicates from both sources.
    Sorts by timestamp and includes attachments with proxy URLs for images.
    Falls back to Sunshine-only if Zendesk fetch fails.
    
    Query parameters:
        - conversationId (str, required): Sunshine conversation ID
    
    Returns:
        JsonResponse: {
            "messages": [...],              # Deduplicated, sorted message array
            "source": "combined" | "error",
            "ticket_id": str,               # Associated Zendesk ticket if found
            "conversation_id": str,
            "appUserId": str                # Participant user ID if found
        }
    
    Status codes:
        - 200: History retrieved successfully
        - 400: Missing conversationId
        - 405: Method not allowed (non-GET)
    """
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
    """
    Parse Zendesk conversation log event into standardized message format.
    
    Converts Zendesk event format to Sunshine-compatible message structure.
    Handles text, images, files, choices, and actions. Filters out system messages
    and conversation metadata. Supports multiple author type formats.
    
    Args:
        event (Dict[str, Any]): Zendesk conversation log event
    
    Returns:
        Optional[Dict[str, Any]]: Standardized message dict or None if filtered
    
    Message format:
        {
            "id": str,
            "text": str,
            "author": {"type": str, "displayName": str},
            "received": str,  # ISO timestamp
            "messageClass": str,  # "user" | "agent" | "bot"
            "source": "conversation_log",
            "attachments": [...],  # Optional
            "choices": [...],      # Optional
            "actions": [...]       # Optional
        }
    
    Filtered messages:
        - Non-text/image/file events
        - System-authored messages
        - "Connecting to agent" messages
        - Conversation metadata patterns
    """
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
        if is_seeded_transcript_message(event, text):
            return None
        text = strip_seeded_transcript_prefix(text)
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
    """
    Fetch messages from Sunshine Conversations API.
    
    Retrieves message history for a conversation and converts to standardized format.
    Detects message sources (user vs agent vs bot) and filters conversation log entries.
    Handles inline images and file attachments with proxy URLs.
    
    Args:
        conversation_id (str): Sunshine conversation ID
    
    Returns:
        List[Dict[str, Any]]: Array of message objects in standard format
    
    Returns empty list on error (logged but not raised).
    """
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
            if is_seeded_transcript_message(msg, text):
                continue
            text = strip_seeded_transcript_prefix(text)
            
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
    """
    Fallback message retrieval from Sunshine when full history fails.
    
    Returns Sunshine messages without Zendesk conversation log integration.
    Used when get_full_chat_history encounters errors.
    
    Args:
        conversation_id (str): Sunshine conversation ID
    
    Returns:
        JsonResponse: {
            "messages": [...],
            "source": "sunshine_fallback" | "error",
            "conversation_id": str,
            "error": str  # Only if error occurred
        }
    
    Status codes:
        - 200: Success or graceful error handling
    """
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
            if is_seeded_transcript_message(msg, text):
                continue
            text = strip_seeded_transcript_prefix(text)
            
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
    """
    Proxy Zendesk/Sunshine images with authentication.
    
    Fetches images from Zendesk domains and returns with proper CORS headers.
    Attempts multiple authentication methods for different Zendesk image sources:
    1. Sunshine API auth (for sc/attachments URLs)
    2. Sunshine JWT token
    3. No auth (public images)
    4. Zendesk API auth
    
    Query parameters:
        - url (str, required): Image URL from Zendesk domain
    
    Returns:
        HttpResponse: Image data with appropriate Content-Type
    
    Status codes:
        - 200: Image retrieved successfully
        - 400: Missing URL parameter
        - 403: Non-Zendesk URL provided (security)
        - 500: Image fetch failed
    
    Allowed domains:
        - zendesk.com
        - smooch.io
        - zdassets.com
        - zendesk-eu.com
    """
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
    """
    Async generator for global server-sent events stream.
    
    Streams notifications about new messages from any conversation to all connected
    clients. Maintains 5-minute timeout with 30-second keepalive pings.
    Yields only notifications from conversations with unread messages.
    
    Yields:
        str: SSE formatted event lines
        - "event: connected": Stream established
        - "event: new_message": New message notification with unread count
        - ": keepalive": Periodic heartbeat
    
    Example event format:
        event: new_message
        data: {"type": "new_message", "conversationId": "...", "agentName": "..."}
    """
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
    """
    HTTP endpoint for global server-sent events (SSE) stream.
    
    Establishes a persistent streaming connection that broadcasts new message
    notifications to all connected clients. Used for real-time updates across
    the entire conversation list. Sets appropriate headers for SSE compatibility
    and disables buffering.
    
    Args:
        request (HttpRequest): Incoming HTTP request
    
    Returns:
        HttpResponse: StreamingHttpResponse with SSE headers and generator stream
        - Status 200: Connection established successfully
        - Status 500: Error initializing stream
    
    Response Headers:
        - Cache-Control: no-cache
        - Connection: keep-alive
        - X-Accel-Buffering: no (disables nginx buffering)
        - Content-Type: text/event-stream
    
    Yields (via generator):
        - "event: connected" on stream start
        - "event: new_message" when new messages arrive with unread count > 0
        - ": keepalive" pings every 30 seconds
    
    Example JavaScript client:
        const eventSource = new EventSource('/notification_stream/');
        eventSource.addEventListener('new_message', (event) => {
            const data = JSON.parse(event.data);
            console.log('New message:', data);
        });
    """
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
    """
    Async generator for per-conversation server-sent events stream.
    
    Streams notifications specific to a single conversation. Monitors Redis cache
    for notifications targeting this conversation and yields them as SSE events.
    Automatically clears processed notifications from cache. Maintains 5-minute
    timeout with 30-second keepalive pings.
    
    Args:
        conversation_id (str): Sunshine Conversations conversation ID to monitor
    
    Yields:
        str: SSE formatted event lines
        - "event: connected": Stream established with conversation ID
        - "event: new_message": New message available for this conversation
        - ": keepalive": Periodic heartbeat every 30 seconds
        - "event: error": Error during streaming
    
    Cache interaction:
        - Polls: notification_{conversation_id} every 100ms
        - Deletes: Notification after yielding (prevents duplicates)
        - Timeout: Individual notifications expire after 30 seconds
    
    Example event format:
        event: new_message
        data: {"type": "message", "conversationId": "...", "text": "..."}
    """
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
    """
    HTTP endpoint for per-conversation server-sent events (SSE) stream.
    
    Establishes a persistent streaming connection for notifications specific to
    a single conversation. Clients subscribe to this endpoint using their
    conversation ID to receive real-time updates. Sets appropriate headers for
    SSE compatibility and disables buffering.
    
    Args:
        request (HttpRequest): Incoming HTTP request
        conversation_id (str): Sunshine Conversations conversation ID to monitor
    
    Returns:
        HttpResponse: StreamingHttpResponse with SSE headers and generator stream
        - Status 200: Connection established successfully
        - Status 500: Error initializing stream
    
    Response Headers:
        - Cache-Control: no-cache
        - Connection: keep-alive
        - X-Accel-Buffering: no (disables nginx buffering)
        - Content-Type: text/event-stream
    
    URL Pattern:
        GET /notification_stream/{conversation_id}/
    
    Decorators:
        @csrf_exempt: Allows streaming without CSRF token (SSE best practice)
    
    Yields (via generator):
        - "event: connected" on stream start with conversation ID
        - "event: new_message" when new messages arrive
        - ": keepalive" pings every 30 seconds
        - "event: error" on stream exceptions
    
    Example JavaScript client:
        const eventSource = new EventSource(
            `/notification_stream/{conversationId}/`
        );
        eventSource.addEventListener('new_message', (event) => {
            const data = JSON.parse(event.data);
            console.log('Message:', data.text);
        });
    """
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
    """
    Cache-based notification delivery to connected SSE clients.
    
    Stores notification data in Redis cache for immediate delivery to
    conversation-specific SSE streams. Also maintains a global notification
    queue (limited to 100 most recent) for global stream distribution.
    Notifications auto-expire after 30 seconds.
    
    Args:
        conversation_id (str): Sunshine Conversations conversation ID
        message_data (Dict[str, Any]): Notification payload
            - type (str): Event type ("message", "typing", "join", etc.)
            - text (str): Message content
            - author (dict): Message author info
            - timestamp (str): ISO format timestamp
            - conversationId (str): Conversation ID
            - unreadCount (int, optional): Unread message count
    
    Side Effects:
        - Sets key: notification_{conversation_id} with 30-second TTL
        - Updates: global_notification queue (kept to 100 items)
        - Sets key: global_notification with 60-second TTL
        - Logs errors but does not raise exceptions
    
    Cache TTL Strategy:
        - Per-conversation notification: 30 seconds (allows SSE polling)
        - Global queue: 60 seconds (longer retention for global stream)
        - Max global queue size: 100 notifications (prevents memory bloat)
    
    Usage:
        Called by webhook handlers after processing Sunshine events
        before message reaches clients via SSE streams.
    
    Example:
        send_notification_to_client(
            'conv-id-123',
            {
                'type': 'message',
                'text': 'Hello',
                'author': {'type': 'agent', 'displayName': 'John'},
                'conversationId': 'conv-id-123',
                'unreadCount': 5
            }
        )
    """
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
