document.addEventListener('DOMContentLoaded', function() {
    const chatWidget = document.querySelector('.chat-widget');
    const chatBox = document.querySelector('.chat-box');
    const toggleBtn = document.querySelector('.chat-toggle-btn');
    const closeBtn = document.querySelector('.chat-close-btn');
    const chatInputArea = document.querySelector('.chat-input');
    const chatInput = document.querySelector('#chat-input-field');
    const sendBtn = document.querySelector('#chat-send-btn');
    const messagesContainer = document.querySelector('.chat-messages');
    const chatHeaderTitle = document.querySelector('.chat-header span');

    let isChatOpen = false;
    let awaitingFeedback = false;
    let appUserId = null;
    let conversationId = null;
    let lastContext = "General Inquiry"; // Track user context for escalation
    let displayedMessageIds = new Set(); // Track displayed messages to prevent duplicates/reloading
    let isAgentConnected = false; // Track if connected to human agent

    // Predefined troubleshooting steps and options
    let troubleshootingSteps = {};
    let mainOptions = [];
    let appRelatedOptions = [];
    let deleteAccountReasons = [];

    // Initialize Chat Session (Get IDs from Backend)
    function initializeChatSession() {
        // Check localStorage for existing user ID
        const storedUserId = localStorage.getItem('chat_user_id');
        const payload = storedUserId ? { userId: storedUserId } : {};

        fetch('/api/chat/init', { 
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(response => response.json())
            .then(data => {
                if (data.appUserId && data.conversationId) {
                    appUserId = data.appUserId;
                    conversationId = data.conversationId;
                    
                    // Save externalId (if returned) or appUserId to localStorage
                    if (data.externalId) {
                        localStorage.setItem('chat_user_id', data.externalId);
                    }

                    console.log("Chat initialized:", appUserId, conversationId);
                    
                    // Fetch previous messages
                    fetchMessages();
                } else {
                    console.error("Failed to initialize chat session", data);
                }
            })
            .catch(error => console.error('Error initializing chat:', error));
    }

    let agentJoinAnnounced = false; // Track if we've announced the agent joining

    // Fetch previous messages
    function fetchMessages() {
        if (!conversationId) return;

        fetch(`/api/chat/messages?conversationId=${conversationId}`)
            .then(response => response.json())
            .then(data => {
                // Check Conversation Status (Active Switchboard Integration)
                // If integration is NOT 'next' (agent) and we were connected, maybe session ended?
                // Note: 'next' is the keyword often used for the primary business integration (Zendesk)
                const activeIntegration = data.conversation && data.conversation.activeSwitchboardIntegration;
                const isAgentActive = activeIntegration && (activeIntegration.name === 'next' || activeIntegration.name === 'zendesk');

                // Detect Session End (If we were connected, but now integration is gone or changed back to bot)
                // This is heuristic; sometimes integration stays 'next' even after solve.
                // But if it explicitly goes to null or 'bot', we can assume end.
                if (isAgentConnected && !isAgentActive && activeIntegration && activeIntegration.name !== 'next') {
                     appendMessage("The agent has ended the session. If you need more help, please refresh or select an option.", "bot-message");
                     isAgentConnected = false;
                     chatInputArea.style.display = 'none';
                     chatHeaderTitle.textContent = "Yatri Bandhu"; // Reset header
                     agentJoinAnnounced = false; // Reset for next time
                }

                if (data.messages) {
                    // Sort messages by date (oldest first)
                    const sortedMessages = data.messages.sort((a, b) => new Date(a.received) - new Date(b.received));
                    let hasNewMessages = false;

                    sortedMessages.forEach(msg => {
                        // Check if message is already displayed
                        if (!displayedMessageIds.has(msg.id)) {
                            if (msg.content && msg.content.type === 'text') {
                                const isUser = msg.author.type === 'user'; 
                                // Extract sender name for agents
                                const senderName = isUser ? null : (msg.author.displayName || 'Agent');
                                
                                // Agent Join Announcement
                                if (!isUser && !agentJoinAnnounced) {
                                    const nameToUse = senderName || "An agent";
                                    appendMessage(`${nameToUse} will help you from here on out.`, 'bot-message'); // Using bot-message style for system notification
                                    agentJoinAnnounced = true;
                                    isAgentConnected = true; // Ensure we are in agent mode
                                    chatInputArea.style.display = 'flex'; // Ensure input is open
                                }

                                // Update header with agent name if connected
                                if (!isUser && senderName && senderName !== 'Agent') {
                                    chatHeaderTitle.textContent = senderName;
                                    chatHeaderTitle.style.fontSize = '1.1rem'; 
                                }

                                // Pass null for senderName so it doesn't appear above the message bubble
                                appendMessage(msg.content.text, isUser ? 'user-message' : 'bot-message', null);
                                displayedMessageIds.add(msg.id);
                                hasNewMessages = true;
                            }
                        }
                    });
                    
                    if (hasNewMessages) {
                        scrollToBottom();
                    }
                }
            })
            .catch(error => console.error('Error fetching messages:', error));
    }

    // Poll for new messages every 5 seconds
    setInterval(fetchMessages, 5000);

    // Call initialization on load
    initializeChatSession();

    // Fetch issues from JSON file
    const issuesUrl = window.issuesUrl || 'static/js/issues.json'; // Fallback for non-Django envs
    fetch(issuesUrl)
        .then(response => response.json())
        .then(data => {
            troubleshootingSteps = data.troubleshooting;
            mainOptions = data.mainOptions;
            appRelatedOptions = data.appRelatedOptions;
            deleteAccountReasons = data.deleteAccountReasons;
        })
        .catch(error => console.error('Error loading issues:', error));

    // Helper: Send Message to Backend (Sunshine)
    function sendToSunshine(text) {
        if (!appUserId || !conversationId) {
            console.error("Cannot send message: Chat not initialized");
            return;
        }

        fetch('/api/chat/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                appUserId: appUserId,
                conversationId: conversationId,
                text: text
            })
        })
        .then(response => response.json())
        .then(data => {
            console.log("Message sent to Sunshine:", data);
            // Optimistically add the message ID to displayed set to prevent duplication by poller
            if (data.data && data.data.messages && data.data.messages.length > 0) {
                const msgId = data.data.messages[0].id;
                displayedMessageIds.add(msgId);
            }
        })
        .catch(error => console.error('Error sending message:', error));
    }

    // Toggle Chat
    function toggleChat() {
        isChatOpen = !isChatOpen;
        if (isChatOpen) {
            chatBox.style.display = 'flex';
            toggleBtn.innerHTML = '✖'; // Close icon
            toggleBtn.setAttribute('aria-label', 'Close chat');
            
            // Initialize options if it's the first time or empty
            if (messagesContainer.children.length <= 1) {
                showMainOptions();
            }
        } else {
            chatBox.style.display = 'none';
            toggleBtn.innerHTML = '💬'; // Chat icon
            toggleBtn.setAttribute('aria-label', 'Open chat');
        }
    }

    toggleBtn.addEventListener('click', toggleChat);
    closeBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        toggleChat();
    });

    // Show Main Options (Level 1)
    function showMainOptions() {
        // Use fetched options or fallback if not loaded yet
        const options = mainOptions.length > 0 ? mainOptions : ["App Related Issues", "Ride Related Issues", "Delete Account"];
        appendOptions(options, handleMainOptionClick);
    }

    // Handle Main Option Click (Level 1)
    function handleMainOptionClick(option) {
        appendMessage(option, 'user-message');
        lastContext = option; // Update context
        
        if (option === "App Related Issues") {
            setTimeout(() => {
                appendMessage("Please select the specific issue you are facing:", 'bot-message');
                showAppRelatedOptions();
            }, 500);
        } else if (option === "Delete Account") {
            showDeleteAccountModal();
        } else {
            // Placeholder for other main options
            setTimeout(() => {
                appendMessage("This feature is currently being updated. Please check back later.", 'bot-message');
                askForFeedback();
            }, 500);
        }
    }

    // Show App Related Options (Level 2)
    function showAppRelatedOptions() {
        const options = appRelatedOptions.length > 0 ? appRelatedOptions : [
            "Location Not Found or Inaccurate", 
            "Unable to Login", 
            "My App is Not Responding", 
            "Others"
        ];
        appendOptions(options, handleAppRelatedOptionClick);
    }

    // Handle App Related Option Click (Level 2)
    function handleAppRelatedOptionClick(option) {
        appendMessage(option, 'user-message');
        lastContext = option; // Update context

        if (option === "Others") {
            appendMessage("Please describe your issue below.", 'bot-message');
            chatInputArea.style.display = 'flex';
            chatInput.focus();
            awaitingFeedback = false; 
        } else if (troubleshootingSteps[option]) {
            setTimeout(() => {
                appendMessage(troubleshootingSteps[option], 'bot-message');
                askForFeedback();
            }, 500);
        } else {
            // Fallback
            setTimeout(() => {
                appendMessage("I'm sorry, I don't have information on that yet.", 'bot-message');
                askForFeedback();
            }, 500);
        }
    }

    // Ask for Feedback
    function askForFeedback() {
        setTimeout(() => {
            appendMessage("Was this helpful?", 'bot-message');
            appendOptions(["Yes", "No"], handleFeedbackClick);
        }, 500);
    }

    // Handle Feedback Click
    function handleFeedbackClick(option) {
        appendMessage(option, 'user-message');

        if (option === "Yes") {
            setTimeout(() => {
                appendMessage("Thank you! Glad I could help. Have a great day! 👋", 'bot-message');
                chatInputArea.style.display = 'none';
            }, 500);
        } else {
            setTimeout(() => {
                appendMessage("I'm sorry about that. Would you like to connect to a human agent?", 'bot-message');
                appendOptions(["Connect to Agent"], handleAgentConnect);
            }, 500);
        }
    }

    // Helper: Escalate to Agent
    function escalateToAgent(reason) {
        if (!conversationId) {
            console.error("Cannot escalate: Chat not initialized");
            return;
        }
        
        console.log("Escalating to agent with reason:", reason);

        fetch('/api/chat/escalate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                conversationId: conversationId,
                appUserId: appUserId, // Send appUserId so backend can send a message on user's behalf
                reason: reason || lastContext
            })
        })
        .then(response => response.json())
        .then(data => {
            console.log("Escalation successful:", data);
        })
        .catch(error => console.error('Error escalating chat:', error));
    }

    // Handle Agent Connect
    function handleAgentConnect(option) {
        appendMessage(option, 'user-message');
        
        // Escalate to Sunshine/Zendesk with context
        escalateToAgent(lastContext);
        
        isAgentConnected = true; // Set flag to keep input open

        setTimeout(() => {
            appendMessage("Connecting you to a human agent... Please wait while we transfer your chat.", 'bot-message');
            // Show input field for live chat
            chatInputArea.style.display = 'flex';
            chatInput.focus();
        }, 500);
    }

    // Send Message (For "OTHERS" flow and Live Agent)
    function sendMessage() {
        const messageText = chatInput.value.trim();
        if (messageText === "") return;

        appendMessage(messageText, 'user-message');
        
        // Send user text to Sunshine
        sendToSunshine(messageText);

        chatInput.value = '';
        
        // If connected to agent, keep input open. Otherwise (ticket mode), close it.
        if (!isAgentConnected) {
            chatInputArea.style.display = 'none';

            setTimeout(() => {
                // Since we are escalating to Sunshine/Zendesk, we can show a confirmation
                appendMessage("Your issue has been forwarded to our support team. An agent will review it shortly.", 'bot-message');
                
                // Optional: Still ask for feedback or just end here
                // askForFeedback(); 
            }, 1500);
        }
    }

    // Append Message to UI
    function appendMessage(text, className, senderName = null) {
        // If senderName is provided (for agents), add a label
        if (senderName && className === 'bot-message') {
            const nameDiv = document.createElement('div');
            nameDiv.textContent = senderName;
            nameDiv.style.fontSize = '0.75rem';
            nameDiv.style.color = '#666';
            nameDiv.style.marginBottom = '2px';
            nameDiv.style.marginLeft = '5px';
            messagesContainer.appendChild(nameDiv);
        }

        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', className);
        
        // Allow newlines to be rendered
        messageDiv.style.whiteSpace = "pre-wrap"; 
        
        messageDiv.textContent = text;
        messagesContainer.appendChild(messageDiv);
        scrollToBottom();
    }

    // Append Options to UI
    function appendOptions(options, callback) {
        const optionsDiv = document.createElement('div');
        optionsDiv.classList.add('options-container');
        
        options.forEach(option => {
            const btn = document.createElement('button');
            btn.classList.add('option-btn');
            btn.textContent = option;
            btn.addEventListener('click', function() {
                optionsDiv.remove(); 
                callback(option);
            });
            optionsDiv.appendChild(btn);
        });

        messagesContainer.appendChild(optionsDiv);
        scrollToBottom();
    }

    // Auto-scroll to bottom
    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    // Delete Account Modal
    function showDeleteAccountModal() {
        // Create Modal Elements
        const modal = document.createElement('div');
        modal.classList.add('chat-modal');
        
        const header = document.createElement('div');
        header.classList.add('chat-modal-header');
        header.textContent = 'Why do you want to delete your account?';
        
        const radioGroup = document.createElement('div');
        radioGroup.classList.add('radio-group');
        
        const reasons = deleteAccountReasons.length > 0 ? deleteAccountReasons : [
            "Moving out of town",
            "App experience issues",
            "Change of phone number",
            "Not getting rides",
            "Not required as of now",
            "Others"
        ];
        
        let selectedReason = null;
        
        reasons.forEach((reason, index) => {
            const optionDiv = document.createElement('div');
            optionDiv.classList.add('radio-option');
            
            const radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = 'delete-reason';
            radio.id = `reason-${index}`;
            radio.value = reason;
            
            const label = document.createElement('label');
            label.htmlFor = `reason-${index}`;
            label.textContent = reason;
            
            optionDiv.appendChild(radio);
            optionDiv.appendChild(label);
            radioGroup.appendChild(optionDiv);
            
            // Event Listener for Radio
            radio.addEventListener('change', function() {
                selectedReason = this.value;
                if (selectedReason === "Others") {
                    otherInput.style.display = 'block';
                    otherInput.focus();
                    validateDeleteButton();
                } else {
                    otherInput.style.display = 'none';
                    deleteBtn.disabled = false;
                }
            });
        });
        
        const otherInput = document.createElement('textarea');
        otherInput.classList.add('delete-reason-input');
        otherInput.placeholder = 'Please describe the issue...';
        otherInput.addEventListener('input', validateDeleteButton);
        
        const buttonsDiv = document.createElement('div');
        buttonsDiv.classList.add('modal-buttons');
        
        const deleteBtn = document.createElement('button');
        deleteBtn.classList.add('modal-btn', 'btn-delete');
        deleteBtn.textContent = 'Delete Account';
        deleteBtn.disabled = true;
        
        const backBtn = document.createElement('button');
        backBtn.classList.add('modal-btn', 'btn-back');
        backBtn.textContent = 'Go Back';
        
        buttonsDiv.appendChild(deleteBtn);
        buttonsDiv.appendChild(backBtn);
        
        modal.appendChild(header);
        modal.appendChild(radioGroup);
        modal.appendChild(otherInput);
        modal.appendChild(buttonsDiv);
        
        chatBox.appendChild(modal);
        
        // Validation Logic
        function validateDeleteButton() {
            if (selectedReason === "Others") {
                deleteBtn.disabled = otherInput.value.trim() === "";
            } else {
                deleteBtn.disabled = selectedReason === null;
            }
        }
        
        // Button Actions
        backBtn.addEventListener('click', function() {
            modal.remove();
            appendMessage("What can I help you with?", 'bot-message');
            showMainOptions();
        });
        
        deleteBtn.addEventListener('click', function() {
            let reasonText = selectedReason;
            if (selectedReason === "Others") {
                reasonText += ": " + otherInput.value.trim();
            }
            
            // Send to Sunshine
            sendToSunshine("Delete Account Request: " + reasonText);
            
            modal.remove();
            appendMessage("Delete Account Request", 'user-message');
            
            setTimeout(() => {
                appendMessage("Your request has been submitted. Our team will contact you shortly.", 'bot-message');
            }, 500);
        });
    }

    // Event Listeners for Sending
    sendBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });
});
