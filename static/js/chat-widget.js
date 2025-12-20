// messaging session ended

document.addEventListener('DOMContentLoaded', function () {
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
    let displayedImageFileNames = new Set(); // Track displayed image file names to prevent duplicates
    let pendingImage = null; // Hold pending image file for caption

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

                    // Fetch previous messages
                    fetchMessages();
                } else {
                    console.error("Failed to initialize chat session", data);
                }
            })
            .catch(error => console.error('Error initializing chat:', error));
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
        if (!conversationId) return;

        fetch(`/api/chat/messages?conversationId=${conversationId}`)
            .then(response => response.json())
            .then(data => {

                /* ===============================
                   CONVERSATION / AGENT STATE LOGIC
                   (UNCHANGED)
                =============================== */
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

                /* ===============================
                   MESSAGE RENDERING
                =============================== */
                if (!data.messages) return;

                const sortedMessages = data.messages.sort(
                    (a, b) => new Date(a.received) - new Date(b.received)
                );

                let hasNewMessages = false;

                for (let i = 0; i < sortedMessages.length; i++) {
                    const msg = sortedMessages[i];
                    if (displayedMessageIds.has(msg.id)) continue;

                    /* ===============================
                       FILE MESSAGE (IMAGE GROUPING)
                    =============================== */
                    if (msg.content?.type === 'file') {
                        const isUser = msg.author.type === 'user';

                        const fileUrl =
                            msg.content.mediaUrl ||
                            msg.content.file?.url ||
                            msg.content.url;

                        const contentType =
                            msg.content.contentType ||
                            msg.content.file?.contentType ||
                            '';

                        const isImage = contentType.startsWith('image/') ||
                            (fileUrl && /\.(jpg|jpeg|png|gif|webp)$/i.test(fileUrl));

                        if (isImage && fileUrl) {
                            // Skip all Zendesk images to avoid unwanted screenshots
                            if (fileUrl.includes('zendesk.com')) {
                                displayedMessageIds.add(msg.id);
                                continue;
                            }

                            // Check if this image has already been displayed immediately
                            const fileName = msg.content.fileName || msg.content.file?.fileName || '';
                            if (displayedImageFileNames.has(fileName)) {
                                displayedMessageIds.add(msg.id);
                                continue; // Skip rendering duplicate
                            }

                            let caption = '';

                            const nextMsg = sortedMessages[i + 1];
                            if (
                                nextMsg &&
                                nextMsg.content?.type === 'text' &&
                                nextMsg.author.type === msg.author.type
                            ) {
                                const timeDiff =
                                    new Date(nextMsg.received) -
                                    new Date(msg.received);

                                if (timeDiff < 2000) {
                                    caption = nextMsg.content.text;
                                    displayedMessageIds.add(nextMsg.id);
                                    i++; // skip caption message
                                }
                            }

                            appendImageMessage(
                                fileUrl,
                                caption,
                                isUser ? 'user-message' : 'bot-message'
                            );

                            displayedMessageIds.add(msg.id);
                            hasNewMessages = true;
                            continue;
                        } else if (!isImage && fileUrl) {
                            // Only render if file details are available
                            if (msg.content.fileName && msg.content.fileSize) {
                                appendFileMessage(
                                    msg.content.fileName,
                                    formatFileSize(msg.content.fileSize),
                                    isUser ? 'user-message' : 'bot-message'
                                );

                                displayedMessageIds.add(msg.id);
                                hasNewMessages = true;
                            } else {
                                // Skip rendering if details are incomplete
                                displayedMessageIds.add(msg.id);
                            }
                            continue;
                        } else {
                            // Image file but no URL yet, or file without URL, skip rendering to prevent duplicate with immediate display
                            displayedMessageIds.add(msg.id);
                            continue;
                        }
                    }

                    /* ===============================
                       TEXT MESSAGE
                    =============================== */
                    if (msg.content?.type === 'text') {
                        const isUser = msg.author.type === 'user';
                        const text = msg.content.text;
                        const lowerText = text.toLowerCase();

                        // Hide internal escalation message
                        if (isUser && text.startsWith("Connecting to agent. Reason:")) {
                            displayedMessageIds.add(msg.id);
                            continue;
                        }

                        appendMessage(
                            text,
                            isUser ? 'user-message' : 'bot-message'
                        );

                        displayedMessageIds.add(msg.id);
                        hasNewMessages = true;
                        continue;
                    }

                    /* ===============================
                       SYSTEM MESSAGE
                    =============================== */
                    if (msg.source?.type === 'system') {
                        appendMessage("Messaging session ended", 'system-message');
                        displayedMessageIds.add(msg.id);
                        hasNewMessages = true;
                    }
                }

                if (hasNewMessages) scrollToBottom();

                /* ===============================
                   SESSION END DETECTION
                =============================== */
                if (sortedMessages.length > 0 && isAgentConnected) {
                    const lastMsg = sortedMessages[sortedMessages.length - 1];
                    let isLastMsgEndSession = false;

                    if (lastMsg.content?.type === 'text') {
                        const senderName =
                            lastMsg.author.type === 'user'
                                ? null
                                : (lastMsg.author.displayName || 'Agent');

                        const text = lastMsg.content.text.toLowerCase();
                        isLastMsgEndSession =
                            senderName === 'System' ||
                            text.includes("messaging session ended") ||
                            text.includes("the agent has ended the session");
                    } else if (lastMsg.source?.type === 'system') {
                        isLastMsgEndSession = true;
                    }

                    const msgTime = new Date(lastMsg.received).getTime();
                    const isTrulyOld = msgTime < (lastAgentRequestTime - 5000);

                    if (isLastMsgEndSession && !isTrulyOld) {
                        endSession();
                    }
                }
            })
            .catch(error => console.error('Error fetching messages:', error));
    }


    // Poll for new messages every 1 second (1000ms)
    // Optimization: Only poll if chat is open OR if we are waiting for/connected to an agent
    setInterval(() => {
        if (isChatOpen || isAgentConnected) {
            fetchMessages();
        }
    }, 1000);

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
    closeBtn.addEventListener('click', function (e) {
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
            console.warn("Cannot escalate: Chat not initialized");
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

        // If there's a pending image, send it with the message
        if (pendingImage) {
            const caption = messageText;
            sendDocument(pendingImage, caption);
            clearImagePreview();
            pendingImage = null;
            chatInput.value = '';
            return;
        }

        if (messageText === "") return;

        // Removed optimistic appendMessage to prevent duplicates - let fetchMessages handle it

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

    // Append Image Message to UI (WhatsApp-style)
    function appendImageMessage(imageUrl, caption, className) {
        // Skip unwanted Zendesk images
        if (imageUrl.includes('zendesk.com')) return;

        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', className, 'image-bubble');

        const img = document.createElement('img');
        img.src = imageUrl;
        img.classList.add('image-thumbnail');
        img.addEventListener('click', function () {
            showImageZoomModal(imageUrl);
        });

        messageDiv.appendChild(img);

        if (caption && caption.trim()) {
            const captionDiv = document.createElement('div');
            captionDiv.classList.add('caption-text');
            captionDiv.textContent = caption;
            messageDiv.appendChild(captionDiv);
        }

        messagesContainer.appendChild(messageDiv);
        scrollToBottom();
    }

    // Append File Message to UI (WhatsApp-style)
    function appendFileMessage(fileName, fileSize, className, caption = '') {
        const bubble = document.createElement('div');
        bubble.classList.add('message', className, 'file-bubble');

        const fileContainer = document.createElement('div');
        fileContainer.classList.add('file-bubble-container');

        // File Icon
        const fileIcon = document.createElement('div');
        fileIcon.classList.add('file-icon');
        fileIcon.textContent = '📄'; // Generic file icon

        // File Details
        const fileDetails = document.createElement('div');
        fileDetails.classList.add('file-details');

        const nameDiv = document.createElement('div');
        nameDiv.classList.add('file-name');
        nameDiv.textContent = fileName;

        const sizeDiv = document.createElement('div');
        sizeDiv.classList.add('file-size');
        sizeDiv.textContent = fileSize;

        fileDetails.appendChild(nameDiv);
        fileDetails.appendChild(sizeDiv);

        fileContainer.appendChild(fileIcon);
        fileContainer.appendChild(fileDetails);

        // Optional caption below file
        if (caption) {
            const captionDiv = document.createElement('div');
            captionDiv.className = 'file-bubble-caption';
            captionDiv.textContent = caption;
            fileContainer.appendChild(captionDiv);
        }

        bubble.appendChild(fileContainer);
        messagesContainer.appendChild(bubble);

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
            btn.addEventListener('click', function () {
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
            radio.addEventListener('change', function () {
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
        backBtn.addEventListener('click', function () {
            modal.remove();
            appendMessage("What can I help you with?", 'bot-message');
            showMainOptions();
        });

        deleteBtn.addEventListener('click', function () {
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

    // Document Upload Functionality
    const fileAttachBtn = document.querySelector('#file-attach-btn');
    const fileInput = document.querySelector('#file-input');

    // File attachment button click handler
    fileAttachBtn.addEventListener('click', function () {
        fileInput.click();
    });

    // File selection handler
    fileInput.addEventListener('change', function (e) {
        const file = e.target.files[0];
        if (file) {
            // Show preview modal for both images and documents
            showDocumentPreviewModal(file);
        }
    });

    // Show document preview modal
    function showDocumentPreviewModal(file) {
        // Create modal elements
        const modal = document.createElement('div');
        modal.classList.add('document-preview-modal');

        const modalContent = document.createElement('div');
        modalContent.classList.add('document-preview-content');

        // Header
        const header = document.createElement('div');
        header.classList.add('document-preview-header');

        const filename = document.createElement('div');
        filename.classList.add('filename');
        filename.textContent = file.name;

        const closeBtn = document.createElement('button');
        closeBtn.classList.add('close-btn');
        closeBtn.innerHTML = '×';
        closeBtn.addEventListener('click', function () {
            modal.remove();
        });

        header.appendChild(filename);
        header.appendChild(closeBtn);

        // Body
        const body = document.createElement('div');
        body.classList.add('document-preview-body');

        const info = document.createElement('div');
        info.classList.add('document-preview-info');

        if (file.type.startsWith('image/')) {
            // Display the image
            const img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            img.style.maxWidth = '100%';
            img.style.maxHeight = '100%';
            img.style.objectFit = 'contain';
            img.style.borderRadius = '12px';
            info.appendChild(img);
        } else {
            // Display file icon and details for non-images
            const fileIcon = document.createElement('div');
            fileIcon.classList.add('document-file-icon');
            fileIcon.innerHTML = '📄'; // Generic file icon

            const details = document.createElement('div');
            details.classList.add('document-details');

            const name = document.createElement('div');
            name.classList.add('name');
            name.textContent = file.name;

            const size = document.createElement('div');
            size.classList.add('size');
            size.textContent = formatFileSize(file.size) + ' · ' + getFileType(file.type);

            details.appendChild(name);
            details.appendChild(size);

            info.appendChild(fileIcon);
            info.appendChild(details);
        }

        body.appendChild(info);

        // Footer (Chat Input Style)
        const footer = document.createElement('div');
        footer.classList.add('document-preview-footer');

        const messageInputBar = document.createElement('div');
        messageInputBar.classList.add('chat-input');
        messageInputBar.style.display = 'flex';
        messageInputBar.style.padding = '0';
        messageInputBar.style.borderTop = 'none';
        messageInputBar.style.backgroundColor = 'transparent';
        messageInputBar.style.justifyContent = 'center';

        const sendBtn = document.createElement('button');
        sendBtn.innerHTML = 'Send';
        sendBtn.style.backgroundColor = '#007bff';
        sendBtn.style.color = 'white';
        sendBtn.style.border = 'none';
        sendBtn.style.width = 'auto';
        sendBtn.style.padding = '10px 20px';
        sendBtn.style.borderRadius = '20px';
        sendBtn.style.cursor = 'pointer';
        sendBtn.style.display = 'flex';
        sendBtn.style.justifyContent = 'center';
        sendBtn.style.alignItems = 'center';
        sendBtn.style.transition = 'background-color 0.2s, transform 0.2s';
        sendBtn.style.boxShadow = '0 2px 5px rgba(0, 123, 255, 0.3)';
        sendBtn.style.fontSize = '0.95em';
        sendBtn.style.fontWeight = '500';

        sendBtn.addEventListener('click', function () {
            sendDocument(file, '');
            modal.remove();
        });

        messageInputBar.appendChild(sendBtn);

        footer.appendChild(messageInputBar);

        // Assemble modal
        modalContent.appendChild(header);
        modalContent.appendChild(body);
        modalContent.appendChild(footer);
        modal.appendChild(modalContent);

        // Add to chat box to match its size
        const chatBox = document.querySelector('.chat-box');
        chatBox.appendChild(modal);
    }

    // Format file size
    function formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    // Get file type description
    function getFileType(mimeType) {
        if (!mimeType) return 'File';
        const typeMap = {
            'application/pdf': 'PDF',
            'application/msword': 'DOC',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DOCX',
            'application/vnd.ms-excel': 'XLS',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'XLSX',
            'application/vnd.ms-powerpoint': 'PPT',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'PPTX',
            'text/plain': 'TXT',
            'image/jpeg': 'JPEG',
            'image/png': 'PNG',
            'image/gif': 'GIF',
            'image/webp': 'WEBP',
            'video/mp4': 'MP4',
            'video/avi': 'AVI',
            'video/quicktime': 'MOV',
            'audio/mpeg': 'MP3',
            'audio/wav': 'WAV',
            'application/zip': 'ZIP',
            'application/x-rar-compressed': 'RAR'
        };
        return typeMap[mimeType] || mimeType.split('/')[1]?.toUpperCase() || 'File';
    }

    // Send document to backend
    function sendDocument(file, message) {
        if (!appUserId || !conversationId) {
            console.error("Cannot send document: Chat not initialized");
            appendMessage("Error: Chat not initialized. Please refresh and try again.", 'system-message');
            return;
        }

        // Check if file is an image
        const isImage = file.type.startsWith('image/');

        // Display image immediately in chat to avoid waiting for Zendesk response
        if (isImage) {
            const imageUrl = URL.createObjectURL(file);
            appendImageMessage(imageUrl, '', 'user-message');
            displayedImageFileNames.add(file.name);
        }

        // Create FormData for multipart upload
        const formData = new FormData();
        formData.append('file', file);
        formData.append('appUserId', appUserId);
        formData.append('conversationId', conversationId);
        if (message && !isImage) {
            formData.append('message', message);
        }

        // Create progress bar element (only show for non-images or if upload takes time)
        let progressContainer = null;
        if (!isImage) {
            progressContainer = document.createElement('div');
            progressContainer.classList.add('upload-progress-container');
            progressContainer.innerHTML = `
                <div class="upload-progress-bar">
                    <div class="upload-progress-fill"></div>
                </div>
                <div class="upload-status">Uploading...</div>
            `;
            messagesContainer.appendChild(progressContainer);
            scrollToBottom();
        }

        const progressFill = progressContainer ? progressContainer.querySelector('.upload-progress-fill') : null;
        const statusText = progressContainer ? progressContainer.querySelector('.upload-status') : null;

        // Use XMLHttpRequest for progress tracking
        const xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', function (e) {
            if (e.lengthComputable && progressContainer) {
                const percentComplete = (e.loaded / e.total) * 100;
                progressFill.style.width = percentComplete + '%';
                statusText.textContent = `Uploading... ${Math.round(percentComplete)}%`;
            }
        });

        xhr.addEventListener('load', function () {
            if (xhr.status === 200) {
                try {
                    const data = JSON.parse(xhr.responseText);
                    console.log("Document sent:", data);

                    // Add message IDs to displayedMessageIds to prevent duplication by fetchMessages
                    if (data.data && data.data.messages) {
                        data.data.messages.forEach(msg => {
                            displayedMessageIds.add(msg.id);
                        });
                    }

                    if (progressContainer) {
                        // Update status to success
                        statusText.textContent = 'Sent successfully!';
                        progressFill.style.backgroundColor = '#28a745';
                        progressContainer.classList.add('upload-complete');

                        // Remove progress bar after a delay
                        setTimeout(() => {
                            progressContainer.remove();
                        }, 2000);
                    }
                } catch (e) {
                    console.error('Error parsing response:', e);
                    if (progressContainer) {
                        statusText.textContent = 'Error processing response';
                        progressFill.style.backgroundColor = '#dc3545';
                    }
                }
            } else {
                console.error('Error sending document:', xhr.status, xhr.responseText);
                if (progressContainer) {
                    statusText.textContent = 'Error sending document';
                    progressFill.style.backgroundColor = '#dc3545';
                }
            }
        });

        xhr.addEventListener('error', function () {
            console.error('Network error sending document');
            if (progressContainer) {
                statusText.textContent = 'Network error - please try again';
                progressFill.style.backgroundColor = '#dc3545';
            }
        });

        xhr.addEventListener('abort', function () {
            console.log('Upload aborted');
            if (progressContainer) {
                statusText.textContent = 'Upload cancelled';
                progressFill.style.backgroundColor = '#ffc107';
            }
        });

        xhr.open('POST', '/api/send-to-zendesk');
        xhr.send(formData);

        // Reset file input
        fileInput.value = '';
    }

    // Show image zoom modal
    function showImageZoomModal(imageUrl) {
        // Create modal elements
        const modal = document.createElement('div');
        modal.classList.add('zoom-modal');

        const img = document.createElement('img');
        img.src = imageUrl;

        modal.appendChild(img);

        // Close modal on click or ESC
        modal.addEventListener('click', function () {
            modal.remove();
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                modal.remove();
            }
        });

        document.body.appendChild(modal);
    }

    // Show image preview in input area
    function showImagePreviewInInput(file) {
        // Create preview container
        const previewContainer = document.createElement('div');
        previewContainer.id = 'image-preview-container';
        previewContainer.classList.add('image-preview-container');

        const img = document.createElement('img');
        img.src = URL.createObjectURL(file);
        img.classList.add('image-preview-thumbnail');

        const removeBtn = document.createElement('button');
        removeBtn.classList.add('image-preview-remove');
        removeBtn.innerHTML = '×';
        removeBtn.addEventListener('click', function () {
            clearImagePreview();
        });

        previewContainer.appendChild(img);
        previewContainer.appendChild(removeBtn);

        // Insert before the input field
        const inputArea = document.querySelector('.chat-input');
        inputArea.insertBefore(previewContainer, chatInput);

        // Update placeholder
        chatInput.placeholder = 'Add a caption (optional)...';
    }

    // Clear image preview
    function clearImagePreview() {
        const preview = document.getElementById('image-preview-container');
        if (preview) {
            preview.remove();
        }
        pendingImage = null;
        chatInput.placeholder = 'Type a message...';
    }

    // Event Listeners for Sending
    sendBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });
});
