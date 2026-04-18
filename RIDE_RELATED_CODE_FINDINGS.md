# Ride Related Issues - Code Locations & Implementation

## Overview
The bot application handles ride-related issues through a combination of frontend decision trees (JavaScript) and backend ticket routing (Python/Django). The system detects ride issue categories, extracts ride parameters, and routes them through the Zendesk ticketing system.

---

## 1. BACKEND CODE (bot_app/views.py)

### 1.1 Function: `escalate_to_agent()`
**Location:** [bot_app/views.py](bot_app/views.py#L1259) - Line 1259

**Purpose:** Main escalation endpoint that receives ride-related issue data from the frontend and passes control to a human agent.

**Ride Parameters Extracted:**
```python
ride_related_category = data.get("rideRelatedCategory")
ride_related_subcategory = data.get("rideRelatedSubcategory")
ride_related_detail = data.get("rideRelatedDetail")
```

**Implementation Details:**
- Extracts all three ride parameters from request JSON
- Creates a `pending_data` cache entry with all ride parameters (line 1330-1337)
- Stores ride category separately in cache for quick lookup (line 1323)
- Calls `build_issue_context()` with ride parameters (line 1315-1320)
- Calls `build_ticket_routing_payload()` with ride parameters (line 1341-1347)
- Passes control to agent via Sunshine switchboard API
- Returns JSON response with ticket_id and routing_updated status

**Request Payload Example:**
```json
{
  "conversationId": "...",
  "appUserId": "...",
  "reason": "...",
  "rideRelatedCategory": "Fare and Payment",
  "rideRelatedSubcategory": "Driver charged extra fare",
  "rideRelatedDetail": "Cash",
  "issueContext": { ... }
}
```

---

### 1.2 Function: `build_issue_context()`
**Location:** [bot_app/views.py](bot_app/views.py#L275) - Line 275

**Purpose:** Builds a standardized issue context dictionary from ride parameters.

**Ride Parameters Accepted:**
```python
ride_related_category: Optional[str] = None,
ride_related_subcategory: Optional[str] = None,
ride_related_detail: Optional[str] = None
```

**Logic:**
- Lines 305-311: When `ride_related_category` is provided and category is not already set:
  - Sets `mainCategory` = "Ride Related Issues"
  - Sets `category` = `ride_related_category`
  - Sets `subcategory` = `ride_related_subcategory` (if provided)
  - Sets `detail` = `ride_related_detail` (if provided)

**Supported Ride Categories:**
- "Fare and Payment"
- "Find a lost item"
- "Vehicle related issue"
- "Safety related"

---

### 1.3 Function: `build_ticket_routing_payload()`
**Location:** [bot_app/views.py](bot_app/views.py#L314) - Line 314

**Purpose:** Builds the Zendesk ticket payload with form IDs and custom fields based on ride issue category.

**Ride Parameters Accepted:**
```python
ride_related_category: Optional[str] = None,
ride_related_subcategory: Optional[str] = None,
ride_related_detail: Optional[str] = None,
```

**Ride Issue Handling Logic:**

#### A. **Fare and Payment Issues** (Line 368-380)
```python
if category_key == "fare and payment":
    form_id = safe_int(FARE_AND_PAYMENT_FORM_ID)
    if form_id:
        ticket_payload["ticket_form_id"] = form_id
    append_custom_field(
        custom_fields,
        FARE_AND_PAYMENT_SUBCATEGORY_FIELD_ID,
        FARE_AND_PAYMENT_SUBCATEGORY_TAGS.get(subcategory_key)
    )
    append_custom_field(
        custom_fields,
        PAYMENT_MODE_FIELD_ID,
        PAYMENT_MODE_TAGS.get(detail_key)
    )
```
- **Subcategories:** Multiple Debits, Driver charged extra fare, Charged higher than estimated fare, Cancellation Charges
- **Details (Payment Mode):** Cash, UPI
- **Custom Fields Set:**
  - `FARE_AND_PAYMENT_SUBCATEGORY_FIELD_ID` → subcategory tag
  - `PAYMENT_MODE_FIELD_ID` → payment mode tag

#### B. **Find a Lost Item Issues** (Line 382-408)
```python
elif category_key == "find a lost item":
    form_id = safe_int(FIMD_A_LOST_ITEM_FORM_ID)
    if form_id:
        ticket_payload["ticket_form_id"] = form_id
    append_custom_field(custom_fields, RIDE_ID_FIELD_ID, ...)
    append_custom_field(custom_fields, DRIVER_NAME_FIELD_ID, ...)
    append_custom_field(custom_fields, VEHICLE_NUMBER_FIELD_ID, ...)
```
- **Custom Fields Set:**
  - `RIDE_ID_FIELD_ID` → ride ID from context or extracted from transcript
  - `DRIVER_NAME_FIELD_ID` → driver name from context or extracted from transcript
  - `VEHICLE_NUMBER_FIELD_ID` → vehicle number from context or extracted from transcript

#### C. **Vehicle Related Issues** (Line 410-417)
```python
elif category_key == "vehicle related issue":
    form_id = safe_int(VEHUICLE_AC_ISSUE_FORM_ID)
    if form_id:
        ticket_payload["ticket_form_id"] = form_id
    append_custom_field(
        custom_fields,
        VEHICLE_ISSUE_TYPE_FIELD_ID,
        VEHICLE_ISSUE_TYPE_TAGS.get(subcategory_key)
    )
```
- **Subcategories:** Unclean/unhygienic vehicle, Vehicle unsafe, AC not turned on / AC stopped working, Vehicle was different
- **Custom Fields Set:**
  - `VEHICLE_ISSUE_TYPE_FIELD_ID` → vehicle issue type tag

#### D. **Safety Related Issues** (Line 419-427)
```python
elif category_key == "safety related":
    form_id = safe_int(SAFETY_ISSUE_FORM_ID)
    if form_id:
        ticket_payload["ticket_form_id"] = form_id
    append_custom_field(custom_fields, ESCALATION_TO_SAFETY_TEAM_FIELD_ID, True)
    append_custom_field(
        custom_fields,
        SAFETY_ISSUE_TYPE_FIELD_ID,
        SAFETY_ISSUE_TYPE_TAGS.get(subcategory_key)
    )
```
- **Subcategories:** Drunk and drive, Driver was rude/misbehaved, Met with accident, Sexual harassment, Physical fights, Extra person in vehicle, Rash driving, Vehicle broke down
- **Custom Fields Set:**
  - `ESCALATION_TO_SAFETY_TEAM_FIELD_ID` → True (escalates to safety team)
  - `SAFETY_ISSUE_TYPE_FIELD_ID` → safety issue type tag

---

### 1.4 Environment Variables for Ride Issue Forms
**Location:** [bot_app/views.py](bot_app/views.py#L115-L150)

```python
FARE_AND_PAYMENT_FORM_ID = get_env_any("FARE_AND_PAYMENT_FORM_ID", "FARE_PAYMENT_FORM_ID")
FIMD_A_LOST_ITEM_FORM_ID = get_env_any("FIMD_A_LOST_ITEM_FORM_ID", "FIND_A_LOST_ITEM_FORM_ID")
VEHUICLE_AC_ISSUE_FORM_ID = get_env_any("VEHUICLE_AC_ISSUE_FORM_ID", "VEHICLE_AC_ISSUE_FORM_ID")
SAFETY_ISSUE_FORM_ID = get_env_any("SAFETY_ISSUE_FORM_ID")

# Custom field IDs
FARE_AND_PAYMENT_SUBCATEGORY_FIELD_ID = get_env_any("FARE_AND_PAYMENT_SUBCATEGORY_FIELD_ID", ...)
RIDE_ID_FIELD_ID = get_env_any("RIDE_ID_FIELD_ID", "RIDE_ID", "rideId")
DRIVER_NAME_FIELD_ID = get_env_any("DRIVER_NAME_FIELD_ID", "DRIVER_NAME", "Driver_Name")
PAYMENT_MODE_FIELD_ID = get_env_any("PAYMENT_MODE_FIELD_ID", "PAYMENT_MODE", "Payment_Mode")
VEHICLE_NUMBER_FIELD_ID = get_env_any("VEHICLE_NUMBER_FIELD_ID", "VEHICLE_NUMBER", "Vehicle_Number")
VEHICLE_ISSUE_TYPE_FIELD_ID = get_env_any("VEHICLE_ISSUE_TYPE_FIELD_ID", "VEHICLE_ISSUE_TYPE", "Vehicle_Issue_Type")
ESCALATION_TO_SAFETY_TEAM_FIELD_ID = get_env_any("ESCALATION_TO_SAFETY_TEAM_FIELD_ID", ...)
SAFETY_ISSUE_TYPE_FIELD_ID = get_env_any("SAFETY_ISSUE_TYPE_FIELD_ID", "SAFETY_ISSUE_TYPE", "Safety_issue_type")
```

---

### 1.5 Ride Issue Tag Mappings
**Location:** [bot_app/views.py](bot_app/views.py#L178-L242)

#### Fare & Payment Subcategory Tags:
```python
FARE_AND_PAYMENT_SUBCATEGORY_TAGS = {
    "multiple debits occurred": "multiple_debits_occured",
    "driver charged extra fare": "driver_charged_extra_fare",
    "charged higher than estimated fare": "charged_higher_than_estimated_fare",
    "cancellation charges": "cancellation_charges",
}
```

#### Vehicle Issue Type Tags:
```python
VEHICLE_ISSUE_TYPE_TAGS = {
    "unclean unhygienic vehicle": "unclean/unhygienic_vehicle",
    "vehicle unsafe": "vehicle_unsafe",
    "ac not turned on ac stopped working midway": "ac_not_turned_on_/_ac_stopped_working",
    "vehicle was different": "vehicle_was_different",
}
```

#### Safety Issue Type Tags:
```python
SAFETY_ISSUE_TYPE_TAGS = {
    "drunk and drive": "drunk_and_drive",
    "driver was rude or misbehaved": "driver_was_rude_or_misbehaved",
    "other": "other",
    "met with an accident": "met_with_an_accident",
    "sexual harassment": "sexual_harresment",
    "physical fights": "phyiscal_fights",
    "extra person in the vehicle": "extra_person_in_the_vehicle",
    "rash driving": "rash_driving",
    "vehicle broke down": "vehicle_broke_down",
}
```

#### Payment Mode Tags:
```python
PAYMENT_MODE_TAGS = {
    "cash": "cash",
    "upi": "upi",
}
```

---

## 2. FRONTEND CODE (static/js/chat-widget.js)

### 2.1 Ride Related Options Variable
**Location:** [static/js/chat-widget.js](static/js/chat-widget.js#L41)

```javascript
let rideRelatedOptions = [];  // Line 41
```
Stores the available ride category options (loaded from backend flow config).

---

### 2.2 Function: `showRideRelatedOptions()`
**Location:** [static/js/chat-widget.js](static/js/chat-widget.js#L1511) - Line 1511

**Purpose:** Displays the main ride issue category options to the user.

**Default Options:**
```javascript
const options = rideRelatedOptions.length > 0 ? rideRelatedOptions : [
    "Fare and Payment",
    "Find a lost item",
    "Vehicle related issue",
    "Safety related"
];
```

**Flow:**
1. Displayed when user selects "Ride Related Issues" from main menu
2. Calls `appendOptions()` with `handleRideRelatedOptionClick` handler
3. Each option click updates flowState and navigates to subcategory selection

---

### 2.3 Function: `handleRideRelatedOptionClick()`
**Location:** [static/js/chat-widget.js](static/js/chat-widget.js#L1521) - Line 1521

**Purpose:** Routes user to appropriate subcategory handler based on selected ride category.

**Flow State Updates:**
```javascript
updateFlowState({
    category: option,        // e.g., "Fare and Payment"
    subcategory: null,
    detail: null
});
```

**Routing Logic:**
- **"Fare and Payment"** → `showFarePaymentOptions()`
- **"Find a lost item"** → `handleLostItemFlow()`
- **"Vehicle related issue"** → `showVehicleRelatedOptions()`
- **"Safety related"** → `showSafetyRelatedOptions()`

---

### 2.4 Function: `handleFarePaymentOptionClick()`
**Location:** [static/js/chat-widget.js](static/js/chat-widget.js#L1577) - Line 1577

**Purpose:** Handles "Fare and Payment" subcategory selection.

**Subcategories Handled:**
- **"Multiple Debits occurred"** → Shows form modal for comments + screenshots
- **"Driver charged extra fare"** → Routes to payment mode selection
- **"Charged higher than estimated fare"** → Shows fare breakdown explanation
- **"Cancellation Charges"** → Routes to cancellation options

**Flow State Updates:**
```javascript
updateFlowState({
    subcategory: option,  // e.g., "Driver charged extra fare"
    detail: null
});
```

---

### 2.5 Function: `handlePaymentModeClick()`
**Location:** [static/js/chat-widget.js](static/js/chat-widget.js#L1669) - Line 1669

**Purpose:** Handles payment mode selection for "Driver charged extra fare" issues.

**Options:**
- **"Cash"** → Shows verification confirmation dialog
- **"UPI"** → Shows form modal for comments + screenshots

**Flow State Updates:**
```javascript
updateFlowState({ detail: option });  // e.g., detail: "Cash" or "UPI"
```

---

### 2.6 Escalation Points - Flow State to Request Mapping
**Location:** [static/js/chat-widget.js](static/js/chat-widget.js#L2321-2355)

When escalating to agent, the frontend collects ride data from flowState:

```javascript
function connectToAgentDirect({ optionLabel = null, forceNewConversation = false } = {}) {
    const agentReason = getCurrentFlowPath() || lastContext;
    const appCategory = flowState.mainCategory === "App Related Issues"
        ? (flowState.category || window.lastAppRelatedCategory)
        : null;

    // ... escalation logic
}

function performEscalation(reason, category) {
    fetch('/api/chat/escalate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            conversationId: conversationId,
            appUserId: appUserId,
            reason: reason || lastContext,
            appRelatedCategory: category || window.lastAppRelatedCategory,
            issueContext: {
                mainCategory: flowState.mainCategory,
                category: flowState.category,           // e.g., "Fare and Payment"
                subcategory: flowState.subcategory,     // e.g., "Driver charged extra fare"
                detail: flowState.detail,               // e.g., "Cash"
                currentPath: getCurrentFlowPath() || lastContext
            }
        })
    })
    ...
}
```

---

### 2.7 Key Variables for Ride Issue Flow
**Location:** [static/js/chat-widget.js](static/js/chat-widget.js#L40-50)

```javascript
let rideRelatedOptions = [];              // Line 41
let farePaymentOptions = [];              // Line 42
let paymentModes = [];                    // Line 43
let cancellationChargeOptions = [];       // Line 44
let vehicleRelatedOptions = [];           // Line 46
let vehicleUnsafeCategories = [];         // Line 47
let safetyRelatedOptions = [];            // Line 48
let flowState = createEmptyFlowState();   // Line 57
```

---

## 3. FLOW STRUCTURE DIAGRAM

### Ride Related Issues Decision Tree:

```
User selects "Ride Related Issues"
    ↓
showRideRelatedOptions() - Display 4 main categories
    ├─→ "Fare and Payment" (handleRideRelatedOptionClick)
    │    ├─→ showFarePaymentOptions()
    │    │    ├─→ "Multiple Debits" → Form (comments + screenshots) → escalate
    │    │    ├─→ "Driver charged extra fare" → showPaymentModes()
    │    │    │                                   ├─→ "Cash" → Verify → escalate
    │    │    │                                   └─→ "UPI" → Form (comments + screenshots) → escalate
    │    │    ├─→ "Charged higher than estimated" → Show breakdown → askFurtherHelp → escalate/CSAT
    │    │    └─→ "Cancellation Charges" → showCancellationChargeOptions()
    │    │                                   └─→ Waiver logic → escalate/CSAT
    │
    ├─→ "Find a lost item" (handleLostItemFlow)
    │    └─→ Call driver/alternate → Further help? → escalate/CSAT
    │
    ├─→ "Vehicle related issue" (handleRideRelatedOptionClick)
    │    └─→ showVehicleRelatedOptions()
    │         ├─→ "Unclean/unhygienic vehicle" → Log issue → CSAT
    │         ├─→ "Vehicle unsafe" → showVehicleUnsafeOptions() → escalate
    │         ├─→ "AC not working" → Troubleshoot → escalate/CSAT
    │         └─→ "Vehicle was different" → Troubleshoot → escalate/CSAT
    │
    └─→ "Safety related" (handleRideRelatedOptionClick)
         └─→ showSafetyRelatedOptions()
              ├─→ Safety issues → Immediate escalation to safety team
              └─→ Issues → Escalate
```

---

## 4. CURRENT FLOW STATE CAPTURE

When ride escalation occurs, the following state is captured:

```javascript
flowState = {
    mainCategory: "Ride Related Issues",
    category: "Fare and Payment",           // Or other ride categories
    subcategory: "Driver charged extra fare", // Specific issue type
    detail: "Cash"                          // Additional detail (e.g., payment mode)
}

// This gets sent to backend as issueContext:
issueContext = {
    mainCategory: "Ride Related Issues",
    category: "Fare and Payment",
    subcategory: "Driver charged extra fare",
    detail: "Cash",
    currentPath: "Ride Related Issues > Fare and Payment > Driver charged extra fare > Cash"
}
```

---

## 5. MISSING: Direct Ride Parameter Extraction in Escalation

**IMPORTANT FINDING:** The `performEscalation()` function (line 517-545) currently **DOES NOT** extract or send `rideRelatedCategory`, `rideRelatedSubcategory`, or `rideRelatedDetail` separately. 

Instead, it relies on the backend to extract these values from the `issueContext.category`, `issueContext.subcategory`, and `issueContext.detail` fields.

**Current Payload:**
```javascript
body: JSON.stringify({
    conversationId: conversationId,
    appUserId: appUserId,
    reason: reason || lastContext,
    appRelatedCategory: category,           // ← Only app category sent separately
    issueContext: {                         // ← All ride params are nested here
        mainCategory: flowState.mainCategory,
        category: flowState.category,
        subcategory: flowState.subcategory,
        detail: flowState.detail,
        currentPath: getCurrentFlowPath()
    }
})
```

**HOWEVER**, the backend `escalate_to_agent()` function expects them to be sent as:
```json
{
    "rideRelatedCategory": "...",
    "rideRelatedSubcategory": "...", 
    "rideRelatedDetail": "..."
}
```

---

## 6. REQUIRED BACKEND CHANGES FOR RIDE ESCALATION

To properly support ride escalations, the backend needs to:

1. **Extract ride parameters from issueContext** in `escalate_to_agent()`:
   - If `issueContext.mainCategory == "Ride Related Issues"`, map:
     - `rideRelatedCategory = issueContext.category`
     - `rideRelatedSubcategory = issueContext.subcategory`
     - `rideRelatedDetail = issueContext.detail`

2. **Or update frontend** to send explicit ride parameters alongside issueContext

---

## SUMMARY

**Ride Issue Categories:** 4 main types
- Fare and Payment (4 subcategories + 2 payment modes)
- Find a lost item (1 subcategory)
- Vehicle related issue (4 subcategories)
- Safety related (8+ subcategories)

**Zendesk Integration:**
- Each category maps to a specific Zendesk form
- Custom fields populate with normalized tags
- Safety issues auto-escalate to safety team

**Flow State Tracking:**
- Frontend maintains complete flowState tree
- Backend extracts from issueContext on escalation
- Ticket routing applies form and custom fields based on category
