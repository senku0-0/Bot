// messaging session ended

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
    const attachBtn = document.querySelector('#chat-attach-btn');
    const fileInput = document.querySelector('#chat-file-input');

    let isChatOpen = false;
    let awaitingFeedback = false;
    let appUserId = null;
    let conversationId = null;
    let lastContext = "General Inquiry"; // Track user context for escalation
    let displayedMessageIds = new Set(); // Track displayed messages to prevent duplicates/reloading
    
    // State Management with Persistence
    let isAgentConnected = localStorage.getItem('chat_isAgentConnected') === 'true'; 
    let lastAgentRequestTime = parseInt(localStorage.getItem('chat_lastAgentRequestTime') || '0');
    let agentJoinAnnounced = localStorage.getItem('chat_agentJoinAnnounced') === 'true';
    let hasConfirmedAgentActivity = localStorage.getItem('chat_hasConfirmedAgentActivity') === 'true';

    // Predefined troubleshooting steps and options
    let troubleshootingSteps = {};
    let mainOptions = [];
    let appRelatedOptions = [];
    let deleteAccountReasons = [];

    let chatSocket = null;

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
                    
                    // Restore UI state if agent was connected
                    if (isAgentConnected) {
                        chatInputArea.style.display = 'flex';
                        chatHeaderTitle.textContent = "Agent"; // Or keep generic if name unknown
                    }

                    // Connect to websocket
                    connectWebSocket();
                } else {
                    console.error("Failed to initialize chat session", data);
                }
            })
            .catch(error => console.error('Error initializing chat:', error));
    }

    function connectWebSocket() {
        if (conversationId) {
            const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
            const wsPath = `${wsScheme}://${window.location.host}/ws/chat/${conversationId}/`;
            chatSocket = new WebSocket(wsPath);

            chatSocket.onopen = function(e) {
                console.log("WebSocket connection opened.");
                // Fetch initial messages
                fetchMessages();
            };

            chatSocket.onmessage = function(e) {
                const data = JSON.parse(e.data);
                if (data.type === 'messages') {
                    handleFetchedMessages(data.messages);
                } else if (data.type === 'new_message') {
                    handleNewMessage(data.message);
                }
            };

            chatSocket.onclose = function(e) {
                console.error('Chat socket closed unexpectedly');
            };
        }
    }



    function handleNewMessage(msg) {
        if (!displayedMessageIds.has(msg.id)) {
            renderMessage(msg);
            scrollToBottom();
        }
    }

    function handleFetchedMessages(data) {
        // This function is similar to the old fetchMessages success handler
        // Check Conversation Status (Active Switchboard Integration)
        if (data.conversation && data.conversation.id) {
            const activeIntegration = data.conversation.activeSwitchboardIntegration;
            
            const isAgentActive = activeIntegration && (
                activeIntegration.name === 'next' || 
                activeIntegration.name === 'zendesk' || 
                activeIntegration.integrationType === 'zendesk'
            );

            if (isAgentActive) {
                if (!isAgentConnected) {
                    isAgentConnected = true;
                    localStorage.setItem('chat_isAgentConnected', 'true');
                    chatInputArea.style.display = 'flex';
                }
                if (!hasConfirmedAgentActivity) {
                    hasConfirmedAgentActivity = true;
                    localStorage.setItem('chat_hasConfirmedAgentActivity', 'true');
                }
            }
        }

        if (data.messages) {
            const sortedMessages = data.messages.sort((a, b) => new Date(a.received) - new Date(b.received));
            let hasNewMessages = false;

            sortedMessages.forEach(msg => {
                if (!displayedMessageIds.has(msg.id)) {
                    renderMessage(msg);
                    hasNewMessages = true;
                }
            });
            
            if (hasNewMessages) {
                scrollToBottom();
            }

            if (sortedMessages.length > 0 && isAgentConnected) {
                const lastMsg = sortedMessages[sortedMessages.length - 1];
                let isLastMsgEndSession = false;

                if (lastMsg.content && lastMsg.content.type === 'text') {
                    const senderName = (lastMsg.author.type === 'user') ? null : (lastMsg.author.displayName || 'Agent');
                    const text = lastMsg.content.text.toLowerCase();
                    isLastMsgEndSession = (senderName === 'System') || 
                                          (text.includes("messaging session ended")) ||
                                          (text.includes("the agent has ended the session"));
                } else if (lastMsg.source && lastMsg.source.type === 'system') {
                    isLastMsgEndSession = true;
                }

                const msgTime = new Date(lastMsg.received).getTime();
                const isTrulyOld = msgTime < (lastAgentRequestTime - 5000);

                if (isLastMsgEndSession && !isTrulyOld) {
                    console.log("Last message is End Session. Closing chat.");
                    endSession();
                }
            }
        }
    }
    
    function renderMessage(msg) {
        if (displayedMessageIds.has(msg.id)) return;

        if (msg.content && msg.content.type === 'text') {
            const isUser = msg.author.type === 'user'; 
            const senderName = isUser ? null : (msg.author.displayName || 'Agent');
            const text = msg.content.text;
            const lowerText = text.toLowerCase();

            if (!isUser && senderName !== 'System') {
                removeLoadingIndicator();
            }

            if (isUser && text.startsWith("Connecting to agent. Reason:")) {
                displayedMessageIds.add(msg.id);
                return; 
            }

            if (!isUser && senderName !== 'System' && !hasConfirmedAgentActivity) {
                 console.log("Agent activity detected via message. Arming auto-close.");
                 hasConfirmedAgentActivity = true;
                 localStorage.setItem('chat_hasConfirmedAgentActivity', 'true');
            }

            const isEndSessionMessage = 
                (senderName === 'System') || 
                (lowerText.includes("messaging session ended")) ||
                (lowerText.includes("the agent has ended the session"));

            if (lowerText.includes(" connected") && senderName === 'System') {
                removeLoadingIndicator();
                
                if (!agentJoinAnnounced) {
                    const namePart = text.split(" connected")[0];
                    if (namePart && namePart !== "An agent") {
                        chatHeaderTitle.textContent = namePart;
                        chatHeaderTitle.style.fontSize = '1.1rem';
                    }
                    
                    appendMessage(text, 'system-message', null);
                    
                    agentJoinAnnounced = true;
                    localStorage.setItem('chat_agentJoinAnnounced', 'true');
                    
                    isAgentConnected = true; 
                    localStorage.setItem('chat_isAgentConnected', 'true');
                    chatInputArea.style.display = 'flex';
                }
                
                displayedMessageIds.add(msg.id);
                return;
            }

            if (isEndSessionMessage) {
                appendMessage(text, 'system-message', null);
                displayedMessageIds.add(msg.id);
                return; 
            }

            if (!isUser && !agentJoinAnnounced && senderName !== 'System') {
                const nameToUse = senderName || "An agent";
                appendMessage(`${nameToUse} connected`, 'system-message'); 
                agentJoinAnnounced = true;
                localStorage.setItem('chat_agentJoinAnnounced', 'true');
                
                isAgentConnected = true; 
                localStorage.setItem('chat_isAgentConnected', 'true');
                chatInputArea.style.display = 'flex'; 
            }

            if (!isUser && senderName && senderName !== 'Agent' && senderName !== 'System') {
                chatHeaderTitle.textContent = senderName;
                chatHeaderTitle.style.fontSize = '1.1rem'; 
            }

            appendMessage(text, isUser ? 'user-message' : 'bot-message', null);
            displayedMessageIds.add(msg.id);
        }
        else if (msg.source && msg.source.type === 'system') {
            const text = "Messaging session ended"; 
            appendMessage(text, 'system-message', null);
            displayedMessageIds.add(msg.id);
        }
    }

    // Fetch previous messages
    // Helper: End Session Cleanup
    function endSession() {
        console.log("Ending session and cleaning up...");
        isAgentConnected = false;
        agentJoinAnnounced = false;
        hasConfirmedAgentActivity = false;
        
        // Clear Persistence
        localStorage.removeItem('chat_isAgentConnected');
        localStorage.removeItem('chat_agentJoinAnnounced');
        localStorage.removeItem('chat_hasConfirmedAgentActivity');
        // We do NOT clear lastAgentRequestTime immediately to prevent race conditions with old messages
        
        // UI Updates
        chatInputArea.style.display = 'none';
        chatHeaderTitle.textContent = "Yatri Bandhu";
        
        // Show "What can I help you with?" message before options
        appendMessage("What can I help you with?", 'bot-message');
        showMainOptions();
    }


    // Fetch previous messages
    function fetchMessages() {
        if (!conversationId || !chatSocket || chatSocket.readyState !== WebSocket.OPEN) return;
        chatSocket.send(JSON.stringify({
            'type': 'fetch_messages',
            'data': {
                'conversationId': conversationId
            }
        }));
    }

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

    async function sendMessage() {
        const messageText = chatInput.value.trim();
        const files = [...attachedFiles];

        if (messageText === "" && files.length === 0) return;

        // Clear input and attachments UI
        chatInput.value = '';
        document.querySelector('#chat-attachments').innerHTML = '';
        attachedFiles = [];

        if (files.length > 0) {
            // Append a user message to show something is happening
            appendMessage(messageText || `Sending ${files.length} file(s)...`, 'user-message');

            const uploadPromises = files.map(file => {
                const formData = new FormData();
                formData.append('file', file);
                return fetch('/api/chat/upload', {
                    method: 'POST',
                    body: formData,
                    // Note: No 'Content-Type' header, browser sets it for FormData
                }).then(response => response.json());
            });

            const uploadResults = await Promise.all(uploadPromises);

            uploadResults.forEach((result, index) => {
                if (result.mediaUrl) {
                    const isLastFile = index === uploadResults.length - 1;
                    chatSocket.send(JSON.stringify({
                        'type': 'send_attachment',
                        'data': {
                            appUserId: appUserId,
                            conversationId: conversationId,
                            mediaUrl: result.mediaUrl,
                            text: isLastFile ? messageText : "" // Send text with the last file
                        }
                    }));
                }
            });

        } else if (messageText !== "") {
            appendMessage(messageText, 'user-message');
            if (chatSocket && chatSocket.readyState === WebSocket.OPEN) {
                chatSocket.send(JSON.stringify({
                    'type': 'send_message',
                    'data': {
                        appUserId: appUserId,
                        conversationId: conversationId,
                        text: messageText
                    }
                }));
            }
        }
        
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

    // Helper: human readable file size
    function humanFileSize(bytes, si = true) {
        const thresh = si ? 1000 : 1024;
        if (Math.abs(bytes) < thresh) {
            return bytes + ' B';
        }
        const units = si
            ? ['kB','MB','GB','TB','PB','EB','ZB','YB']
            : ['KiB','MiB','GiB','TiB','PiB','EiB','ZiB','YiB'];
        let u = -1;
        do {
            bytes /= thresh;
            ++u;
        } while (Math.abs(bytes) >= thresh && u < units.length - 1);
        return bytes.toFixed(1) + ' ' + units[u];
    }

    let attachedFiles = [];

    // Attachment button: open file picker and show preview locally
    if (attachBtn && fileInput) {
        attachBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            fileInput.click();
        });

        fileInput.addEventListener('change', function(e) {
            const files = e.target.files;
            if (!files) return;

            const attachmentsContainer = document.querySelector('#chat-attachments');
            if (!attachmentsContainer) return;

            for (const file of files) {
                attachedFiles.push(file);
                const chip = createAttachmentChip(file);
                attachmentsContainer.appendChild(chip);
            }
            
            // Clear the file input so the user can select the same file again
            fileInput.value = null;
        });
    }

    function createAttachmentChip(file) {
        const chip = document.createElement('div');
        chip.classList.add('attachment-chip');
        chip.dataset.fileName = file.name;

        // Thumbnail (image preview) or icon placeholder
        const thumb = document.createElement('div');
        thumb.classList.add('thumb');

        if (file.type && file.type.startsWith('image/')) {
            const url = URL.createObjectURL(file);
            const img = document.createElement('img');
            img.src = url;
            img.alt = file.name;
            img.className = 'thumb';
            img.style.width = '32px';
            img.style.height = '20px';
            img.style.borderRadius = '4px';
            chip.appendChild(img);
        } else {
            // show placeholder box
            chip.appendChild(thumb);
        }

        const meta = document.createElement('div');
        meta.classList.add('meta');

        const name = document.createElement('div');
        name.classList.add('name');
        name.textContent = file.name;

        const size = document.createElement('div');
        size.classList.add('size');
        size.textContent = humanFileSize(file.size);

        meta.appendChild(name);
        meta.appendChild(size);
        chip.appendChild(meta);

        const removeBtn = document.createElement('button');
        removeBtn.classList.add('remove-btn');
        removeBtn.setAttribute('aria-label', 'Remove attachment');
        removeBtn.innerHTML = '✕';
        removeBtn.addEventListener('click', function(ev) {
            ev.stopPropagation();
            const chipToRemove = ev.target.closest('.attachment-chip');
            const fileName = chipToRemove.dataset.fileName;
            attachedFiles = attachedFiles.filter(f => f.name !== fileName);
            chipToRemove.remove();
        });

        chip.appendChild(removeBtn);
        return chip;
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
            // Submit positive CSAT
            submitCSAT(5, null);
            setTimeout(() => {
                appendMessage("Thank you! Glad I could help. Have a great day! 👋", 'bot-message');
                chatInputArea.style.display = 'none';
            }, 500);
        } else {
            // Submit negative CSAT (allow user to optionally comment afterwards)
            submitCSAT(2, null);
            setTimeout(() => {
                appendMessage("I'm sorry about that. Would you like to connect to a human agent?", 'bot-message');
                appendOptions(["Connect to Agent"], handleAgentConnect);
            }, 500);
        }
    }

    // Submit CSAT to backend
    function submitCSAT(rating, comment) {
        if (!rating) return;

        const payload = {
            rating: rating,
            comment: comment || null,
            conversationId: conversationId,
            appUserId: appUserId
        };

        fetch('/api/csat/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(res => res.json())
        .then(data => {
            console.log('CSAT submitted', data);
        })
        .catch(err => console.error('Error submitting CSAT', err));
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

    // Send text to Sunshine via websocket if available, otherwise fallback to HTTP
    function sendToSunshine(text) {
        if (!conversationId || !appUserId) {
            console.error('Cannot send to Sunshine: missing conversation or user id');
            return;
        }

        if (chatSocket && chatSocket.readyState === WebSocket.OPEN) {
            chatSocket.send(JSON.stringify({
                type: 'send_message',
                data: {
                    appUserId: appUserId,
                    conversationId: conversationId,
                    text: text
                }
            }));
        } else {
            // fallback HTTP
            fetch('/api/chat/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ appUserId: appUserId, conversationId: conversationId, text: text })
            }).then(r => r.json()).then(res => console.log('Sent via HTTP fallback', res)).catch(err => console.error('Fallback send failed', err));
        }
    }

    // Handle Agent Connect
    function handleAgentConnect(option) {
        appendMessage(option, 'user-message');
        
        // Escalate to Sunshine/Zendesk with context
        escalateToAgent(lastContext);
        
        isAgentConnected = true; 
        lastAgentRequestTime = Date.now(); 
        agentJoinAnnounced = false;

        // Persist State
        localStorage.setItem('chat_isAgentConnected', 'true');
        localStorage.setItem('chat_lastAgentRequestTime', lastAgentRequestTime.toString());
        localStorage.setItem('chat_agentJoinAnnounced', 'false');

        setTimeout(() => {
            // Show loading indicator instead of text
            showLoadingIndicator();
            
            // Show input field for live chat
            chatInputArea.style.display = 'flex';
            chatInput.focus();
        }, 500);
    }

    // Helper: Show Loading Indicator
    function showLoadingIndicator() {
        if (document.getElementById('agent-loading-indicator')) return;

        const loaderDiv = document.createElement('div');
        loaderDiv.id = 'agent-loading-indicator';
        // Use system-message to avoid bubble styling
        loaderDiv.classList.add('message', 'system-message');
        
        loaderDiv.innerHTML = `
            Please hang on
            <div class="typing-indicator-inline">
                <div class="typing-dot-small"></div>
                <div class="typing-dot-small"></div>
                <div class="typing-dot-small"></div>
            </div>
        `;
        messagesContainer.appendChild(loaderDiv);
        scrollToBottom();
    }

    // Helper: Remove Loading Indicator
    function removeLoadingIndicator() {
        const loader = document.getElementById('agent-loading-indicator');
        if (loader) {
            loader.remove();
        }
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
