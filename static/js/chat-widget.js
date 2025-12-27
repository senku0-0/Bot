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
    const fileAttachBtn = document.querySelector('#file-attach-btn');
    const fileInput = document.querySelector('#file-input');

    let isChatOpen = false;
    let awaitingFeedback = false;
    let appUserId = null;
    let conversationId = null;
    let lastContext = "General Inquiry";
    let displayedMessageIds = new Set();
    let displayedImageFileNames = new Set();
    let pendingImage = null;
    let pendingLocalMessages = new Set();

    // WebSocket variables
    let sunshineSocket = null;
    let webSocketConnected = false;
    let sessionEnded = false;

    // State Management
    let isAgentConnected = localStorage.getItem('chat_isAgentConnected') === 'true';
    let lastAgentRequestTime = parseInt(localStorage.getItem('chat_lastAgentRequestTime') || '0');
    let agentJoinAnnounced = localStorage.getItem('chat_agentJoinAnnounced') === 'true';
    let hasConfirmedAgentActivity = localStorage.getItem('chat_hasConfirmedAgentActivity') === 'true';

    // Data variables
    let troubleshootingSteps = {};
    let mainOptions = [];
    let appRelatedOptions = [];
    let deleteAccountReasons = [];

    // ============================================================================
    // Sunshine WebSocket Manager (REPLACES POLLING)
    // ============================================================================
    class SunshineWebSocketManager {
        constructor(userId, conversationId) {
            this.userId = userId;
            this.conversationId = conversationId;
            this.socket = null;
            this.connected = false;
            this.reconnectAttempts = 0;
            this.maxReconnectAttempts = 10;
            this.messageQueue = [];
        }

        connect() {
            if (!this.conversationId) {
                console.error('Cannot connect WebSocket: missing conversationId');
                return;
            }

            if (this.socket) {
                this.disconnect();
            }

            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/chat/${this.conversationId}/`;
            
            console.log('🔌 Connecting to Django WebSocket:', wsUrl);
            
            this.socket = new WebSocket(wsUrl);

            this.socket.onopen = () => {
                console.log('✅ WebSocket connected to Django successfully');
                this.connected = true;
                this.reconnectAttempts = 0;
                webSocketConnected = true;
                this.flushMessageQueue();
                this.showConnectionStatus('connected');
                console.log('📡 Django WebSocket is now handling real-time updates');
            };

            this.socket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleIncomingMessage(data);
                } catch (error) {
                    console.error('❌ Error parsing WebSocket message:', error);
                }
            };

            this.socket.onclose = (event) => {
                console.log('🔌 WebSocket disconnected from Django:', event.code, event.reason);
                this.connected = false;
                webSocketConnected = false;
                this.showConnectionStatus('disconnected');
                
                if (!sessionEnded) {
                    this.attemptReconnection();
                }
            };

            this.socket.onerror = (error) => {
                console.error('❌ WebSocket error connecting to Django:', error);
                this.showConnectionStatus('error');
            };
        }

        send(message) {
            if (this.socket && this.socket.readyState === WebSocket.OPEN) {
                this.socket.send(JSON.stringify(message));
                return true;
            } else {
                console.warn('⚠️ WebSocket not ready, queuing message');
                this.messageQueue.push(message);
                return false;
            }
        }

        flushMessageQueue() {
            if (this.messageQueue.length > 0 && this.socket && this.socket.readyState === WebSocket.OPEN) {
                console.log(`🔄 Flushing ${this.messageQueue.length} queued messages`);
                this.messageQueue.forEach(msg => {
                    this.socket.send(JSON.stringify(msg));
                });
                this.messageQueue = [];
            }
        }

        handleIncomingMessage(data) {
            if (data.type === 'conversation:message') {
                this.handleNewMessage(data.payload);
            } else if (data.type === 'participant:join') {
                this.handleParticipantJoin(data.payload);
            } else if (data.type === 'conversation:read') {
                this.handleConversationRead(data.payload);
            } else if (data.type === 'switchboard:passControl') {
                this.handleSwitchboardControl(data.payload);
            } else if (data.type === 'sunshine_webhook') {
                this.handleWebhookEvent(data.payload);
            } else if (data.type === 'debug_message') {
                console.log('🐛 Debug message:', data.payload);
            }
        }

        handleNewMessage(payload) {
            if (!payload || !payload.message) return;
            
            const message = payload.message;
            const isAgent = message.author && (
                message.author.type === 'business' || 
                message.author.type === 'agent' ||
                message.source === 'zendesk'
            );
            
            if (isAgent) {
                console.log('🎯 Agent message received via WebSocket');
                processWebSocketMessage(message);
            } else {
                if (message.id && !displayedMessageIds.has(message.id)) {
                    displayedMessageIds.add(message.id);
                }
            }
        }

        handleWebhookEvent(payload) {
            console.log('🔄 Processing forwarded webhook');
            
            if (payload.messages) {
                payload.messages.forEach(msg => this.processWebhookMessage(msg));
            } else if (payload.events) {
                payload.events.forEach(event => {
                    if (event.messages) {
                        event.messages.forEach(msg => this.processWebhookMessage(msg));
                    }
                });
            }
        }

        processWebhookMessage(message) {
            if (message.id) {
                displayedMessageIds.add(message.id);
            }
            
            const isAgent = message.author && (
                message.author.type === 'business' || 
                message.author.type === 'agent' ||
                message.source === 'zendesk'
            );
            
            if (isAgent) {
                console.log('🎯 Agent message from webhook');
                processWebSocketMessage(message);
            }
        }

        attemptReconnection() {
            if (this.reconnectAttempts >= this.maxReconnectAttempts || sessionEnded) {
                console.log('❌ Max reconnection attempts reached or session ended');
                return;
            }
            
            this.reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
            
            console.log(`🔄 Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
            
            setTimeout(() => {
                this.connect();
            }, delay);
        }

        showConnectionStatus(status) {
            if (!window.DEBUG_MODE) return;
            
            const statusElement = document.getElementById('websocket-status') || (() => {
                const div = document.createElement('div');
                div.id = 'websocket-status';
                div.style.position = 'fixed';
                div.style.bottom = '10px';
                div.style.right = '10px';
                div.style.padding = '5px 10px';
                div.style.borderRadius = '3px';
                div.style.fontSize = '12px';
                div.style.zIndex = '9999';
                document.body.appendChild(div);
                return div;
            })();
            
            const statusConfig = {
                connected: { text: '🟢 WebSocket Live', color: '#4CAF50' },
                disconnected: { text: '🔴 WebSocket Offline', color: '#F44336' }
            };
            
            const config = statusConfig[status] || statusConfig.disconnected;
            statusElement.textContent = config.text;
            statusElement.style.color = config.color;
        }

        disconnect() {
            if (this.socket) {
                this.socket.close(1000, 'Closing connection');
            }
        }
    }

    // ============================================================================
    // Core Functions
    // ============================================================================

    function initializeChatSession() {
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

                    if (data.externalId) {
                        localStorage.setItem('chat_user_id', data.externalId);
                    }

                    console.log("Chat initialized:", appUserId, conversationId);

                    if (isAgentConnected) {
                        chatInputArea.style.display = 'flex';
                        chatHeaderTitle.textContent = "Agent";
                    }

                    initializeWebSocketConnection(appUserId, conversationId);
                    fetchMessages();
                } else {
                    console.error("Failed to initialize chat session", data);
                }
            })
            .catch(error => console.error('Error initializing chat:', error));
    }

    function fetchMessages() {
        if (!conversationId) return;

        fetch(`/api/chat/messages?conversationId=${conversationId}`)
            .then(response => response.json())
            .then(data => {
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

                if (!data.messages) return;

                const sortedMessages = data.messages.sort(
                    (a, b) => new Date(a.received) - new Date(b.received)
                );

                let hasNewMessages = false;

                sortedMessages.forEach(msg => {
                    if (!msg || !msg.id || displayedMessageIds.has(msg.id)) return;

                    // Dedupe server-echoed user messages
                    if (msg.author?.type === 'user' && msg.content?.type === 'text') {
                        const serverText = msg.content.text || '';
                        if (pendingLocalMessages.has(serverText)) {
                            displayedMessageIds.add(msg.id);
                            pendingLocalMessages.delete(serverText);
                            return;
                        }
                    }

                    displayedMessageIds.add(msg.id);
                    hasNewMessages = true;

                    // Process message content
                    if (msg.content?.type === 'file' && msg.source?.type !== 'whatsapp') {
                        const mediaUrl = msg.content.mediaUrl;
                        const text = msg.content.text || '';
                        const fileName = mediaUrl?.split('/').pop() || 'file';
                        
                        if (displayedImageFileNames.has(fileName)) return;
                        
                        if (mediaUrl && (mediaUrl.includes('.jpg') || mediaUrl.includes('.jpeg') || 
                            mediaUrl.includes('.png') || mediaUrl.includes('.gif') || 
                            mediaUrl.includes('.webp'))) {
                            displayedImageFileNames.add(fileName);
                            appendImageMessage(mediaUrl, text, 'bot-message');
                        } else if (mediaUrl) {
                            appendFileMessage(fileName, formatFileSize(msg.content.size || 0), 'bot-message', text);
                        }
                    } else if (msg.content?.type === 'text') {
                        const isSystem = msg.author?.type === 'system';
                        const isAgent = msg.author?.type === 'business' || msg.author?.type === 'agent';
                        const senderName = isAgent ? (msg.author.displayName || 'Agent') : null;
                        
                        appendMessage(msg.content.text, 
                            isSystem ? 'system-message' : 'bot-message', 
                            senderName);
                    }
                });

                if (hasNewMessages) scrollToBottom();

                // Session end detection
                if (sortedMessages.length > 0 && isAgentConnected) {
                    const lastMsg = sortedMessages[sortedMessages.length - 1];
                    let isLastMsgEndSession = false;

                    if (lastMsg.content?.type === 'text') {
                        const senderName = lastMsg.author.type === 'user' ? null : 
                                          (lastMsg.author.displayName || 'Agent');
                        const text = lastMsg.content.text.toLowerCase();
                        isLastMsgEndSession = senderName === 'System' ||
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

    function initializeWebSocketConnection(userId, conversationId) {
        if (!window.WebSocket) {
            console.error('❌ WebSocket not supported by browser');
            return;
        }
        
        sunshineSocket = new SunshineWebSocketManager(userId, conversationId);
        sunshineSocket.connect();
    }

    function processWebSocketMessage(message) {
        const formattedMessage = {
            id: message.id,
            author: message.author,
            content: message.content,
            received: message.received,
            source: message.source || 'websocket'
        };
        
        handleIncomingServerMessage(formattedMessage);
    }

    function handleIncomingServerMessage(serverMessage) {
        if (serverMessage.id && displayedMessageIds.has(serverMessage.id)) return;
        
        const isAgent = serverMessage.author && serverMessage.author.type === 'business';
        const isSystem = serverMessage.author && serverMessage.author.type === 'system';
        
        if (isAgent || isSystem) {
            removeLoadingIndicator();
            
            if (serverMessage.id) displayedMessageIds.add(serverMessage.id);
            
            const text = serverMessage.content?.text || '';
            
            if (text) {
                const lowerText = text.toLowerCase();
                if (lowerText.includes('connected') || lowerText.includes('joined')) {
                    if (!agentJoinAnnounced) {
                        agentJoinAnnounced = true;
                        localStorage.setItem('chat_agentJoinAnnounced', 'true');
                        
                        let agentName = serverMessage.author.displayName || 'Agent';
                        localStorage.setItem('chat_agentName', agentName);
                        
                        chatHeaderTitle.textContent = agentName;
                        appendMessage(`${agentName} has joined the chat`, 'system-message');
                    }
                }
                
                appendMessage(text, 'bot-message');
                scrollToBottom();
            }
        }
    }

    function endSession() {
        console.log("Ending session and cleaning up...");
        isAgentConnected = false;
        agentJoinAnnounced = false;
        hasConfirmedAgentActivity = false;
        sessionEnded = true;
        
        if (sunshineSocket) sunshineSocket.disconnect();

        localStorage.removeItem('chat_isAgentConnected');
        localStorage.removeItem('chat_agentJoinAnnounced');
        localStorage.removeItem('chat_hasConfirmedAgentActivity');

        chatInputArea.style.display = 'none';
        chatHeaderTitle.textContent = "Yatri Bandhu";
        appendMessage("What can I help you with?", 'bot-message');
        showMainOptions();
    }

    function escalateToAgent(reason) {
        if (!conversationId) {
            console.warn("Cannot escalate: Chat not initialized");
            return;
        }

        console.log("Escalating to agent with reason:", reason);

        isAgentConnected = true;
        lastAgentRequestTime = Date.now();
        agentJoinAnnounced = false;
        localStorage.setItem('chat_isAgentConnected', 'true');
        localStorage.setItem('chat_lastAgentRequestTime', lastAgentRequestTime.toString());
        localStorage.setItem('chat_agentJoinAnnounced', 'false');
        
        if (sunshineSocket && !sunshineSocket.connected) {
            console.log('⚠️ WebSocket not connected, reconnecting...');
            sunshineSocket.connect();
        }
        
        showLoadingIndicator();
        chatInputArea.style.display = 'flex';

        fetch('/api/chat/escalate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                conversationId: conversationId,
                appUserId: appUserId,
                reason: reason || lastContext
            })
        })
            .then(response => response.json())
            .then(data => console.log("Escalation successful:", data))
            .catch(error => console.error('Error escalating chat:', error));
    }

    function handleAgentConnect(option) {
        appendMessage(option, 'user-message');
        escalateToAgent(lastContext);

        isAgentConnected = true;
        lastAgentRequestTime = Date.now();
        agentJoinAnnounced = false;
        localStorage.setItem('chat_isAgentConnected', 'true');
        localStorage.setItem('chat_lastAgentRequestTime', lastAgentRequestTime.toString());
        localStorage.setItem('chat_agentJoinAnnounced', 'false');

        setTimeout(() => {
            showLoadingIndicator();
            chatInputArea.style.display = 'flex';
            chatInput.focus();
        }, 500);
    }

    // ============================================================================
    // UI Functions
    // ============================================================================

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
                if (data.data?.messages?.length > 0) {
                    const msgId = data.data.messages[0].id;
                    displayedMessageIds.add(msgId);
                    try {
                        const echoedText = data.data.messages[0].content?.text;
                        if (echoedText) pendingLocalMessages.delete(echoedText);
                    } catch (e) {}
                }
            })
            .catch(error => console.error('Error sending message:', error));
    }

    function toggleChat() {
        isChatOpen = !isChatOpen;
        if (isChatOpen) {
            chatBox.style.display = 'flex';
            toggleBtn.innerHTML = '✖';
            toggleBtn.setAttribute('aria-label', 'Close chat');

            if (messagesContainer.children.length <= 1) {
                showMainOptions();
            }
        } else {
            chatBox.style.display = 'none';
            toggleBtn.innerHTML = '💬';
            toggleBtn.setAttribute('aria-label', 'Open chat');
        }
    }

    function showMainOptions() {
        const options = mainOptions.length > 0 ? mainOptions : ["App Related Issues", "Ride Related Issues", "Delete Account"];
        appendOptions(options, handleMainOptionClick);
    }

    function handleMainOptionClick(option) {
        appendMessage(option, 'user-message');
        lastContext = option;

        if (option === "App Related Issues") {
            setTimeout(() => {
                appendMessage("Please select the specific issue you are facing:", 'bot-message');
                showAppRelatedOptions();
            }, 500);
        } else if (option === "Delete Account") {
            showDeleteAccountModal();
        } else {
            setTimeout(() => {
                appendMessage("This feature is currently being updated. Please check back later.", 'bot-message');
                askForFeedback();
            }, 500);
        }
    }

    function showAppRelatedOptions() {
        const options = appRelatedOptions.length > 0 ? appRelatedOptions : [
            "Location Not Found or Inaccurate",
            "Unable to Login",
            "My App is Not Responding",
            "Others"
        ];
        appendOptions(options, handleAppRelatedOptionClick);
    }

    function handleAppRelatedOptionClick(option) {
        appendMessage(option, 'user-message');
        lastContext = option;

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
            setTimeout(() => {
                appendMessage("I'm sorry, I don't have information on that yet.", 'bot-message');
                askForFeedback();
            }, 500);
        }
    }

    function askForFeedback() {
        setTimeout(() => {
            appendMessage("Was this helpful?", 'bot-message');
            appendOptions(["Yes", "No"], handleFeedbackClick);
        }, 500);
    }

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

    function showLoadingIndicator() {
        if (document.getElementById('agent-loading-indicator')) return;

        const loaderDiv = document.createElement('div');
        loaderDiv.id = 'agent-loading-indicator';
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

    function removeLoadingIndicator() {
        const loader = document.getElementById('agent-loading-indicator');
        if (loader) loader.remove();
    }

    function sendMessage() {
        const messageText = chatInput.value.trim();

        if (pendingImage) {
            const caption = messageText;
            sendDocument(pendingImage, caption);
            clearImagePreview();
            pendingImage = null;
            chatInput.value = '';
            return;
        }

        if (messageText === "") return;

        appendMessage(messageText, 'user-message');
        pendingLocalMessages.add(messageText);
        sendToSunshine(messageText);
        chatInput.value = '';

        if (!isAgentConnected) {
            chatInputArea.style.display = 'none';
            setTimeout(() => {
                appendMessage("Your issue has been forwarded to our support team. An agent will review it shortly.", 'bot-message');
            }, 1500);
        }
    }

    function appendMessage(text, className, senderName = null) {
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
        messageDiv.style.whiteSpace = "pre-wrap";
        messageDiv.textContent = text;
        messagesContainer.appendChild(messageDiv);
        scrollToBottom();
    }

    function appendImageMessage(imageUrl, caption, className) {
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

    function appendFileMessage(fileName, fileSize, className, caption = '') {
        const bubble = document.createElement('div');
        bubble.classList.add('message', className, 'file-bubble');

        const fileContainer = document.createElement('div');
        fileContainer.classList.add('file-bubble-container');

        const fileIcon = document.createElement('div');
        fileIcon.classList.add('file-icon');
        fileIcon.textContent = '📄';

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

    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    // ============================================================================
    // File Handling Functions
    // ============================================================================

    function showDocumentPreviewModal(file) {
        const modal = document.createElement('div');
        modal.classList.add('document-preview-modal');

        const modalContent = document.createElement('div');
        modalContent.classList.add('document-preview-content');

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

        const body = document.createElement('div');
        body.classList.add('document-preview-body');

        const info = document.createElement('div');
        info.classList.add('document-preview-info');

        if (file.type.startsWith('image/')) {
            const img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            img.style.maxWidth = '100%';
            img.style.maxHeight = '100%';
            img.style.objectFit = 'contain';
            img.style.borderRadius = '12px';
            info.appendChild(img);
        } else {
            const fileIcon = document.createElement('div');
            fileIcon.classList.add('document-file-icon');
            fileIcon.innerHTML = '📄';

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

        modalContent.appendChild(header);
        modalContent.appendChild(body);
        modalContent.appendChild(footer);
        modal.appendChild(modalContent);

        const chatBox = document.querySelector('.chat-box');
        chatBox.appendChild(modal);
    }

    function formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

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

    function sendDocument(file, message) {
        if (!appUserId || !conversationId) {
            console.error("Cannot send document: Chat not initialized");
            appendMessage("Error: Chat not initialized. Please refresh and try again.", 'system-message');
            return;
        }

        const isImage = file.type.startsWith('image/');

        if (isImage) {
            const imageUrl = URL.createObjectURL(file);
            appendImageMessage(imageUrl, '', 'user-message');
            displayedImageFileNames.add(file.name);
        }

        const formData = new FormData();
        formData.append('file', file);
        formData.append('appUserId', appUserId);
        formData.append('conversationId', conversationId);
        if (message && !isImage) {
            formData.append('message', message);
        }

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

                    if (data.data?.messages) {
                        data.data.messages.forEach(msg => {
                            displayedMessageIds.add(msg.id);
                        });
                    }

                    if (progressContainer) {
                        statusText.textContent = 'Sent successfully!';
                        progressFill.style.backgroundColor = '#28a745';
                        progressContainer.classList.add('upload-complete');

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

        fileInput.value = '';
    }

    function showImageZoomModal(imageUrl) {
        const modal = document.createElement('div');
        modal.classList.add('zoom-modal');

        const img = document.createElement('img');
        img.src = imageUrl;
        modal.appendChild(img);

        modal.addEventListener('click', function () {
            modal.remove();
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') modal.remove();
        });

        document.body.appendChild(modal);
    }

    function showImagePreviewInInput(file) {
        const previewContainer = document.createElement('div');
        previewContainer.id = 'image-preview-container';
        previewContainer.classList.add('image-preview-container');

        const img = document.createElement('img');
        img.src = URL.createObjectURL(file);
        img.classList.add('image-preview-thumbnail');

        const removeBtn = document.createElement('button');
        removeBtn.classList.add('image-preview-remove');
        removeBtn.innerHTML = '×';
        removeBtn.addEventListener('click', clearImagePreview);

        previewContainer.appendChild(img);
        previewContainer.appendChild(removeBtn);

        chatInputArea.insertBefore(previewContainer, chatInput);
        chatInput.placeholder = 'Add a caption (optional)...';
    }

    function clearImagePreview() {
        const preview = document.getElementById('image-preview-container');
        if (preview) preview.remove();
        pendingImage = null;
        chatInput.placeholder = 'Type a message...';
    }

    function showDeleteAccountModal() {
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

        function validateDeleteButton() {
            if (selectedReason === "Others") {
                deleteBtn.disabled = otherInput.value.trim() === "";
            } else {
                deleteBtn.disabled = selectedReason === null;
            }
        }

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

            sendToSunshine("Delete Account Request: " + reasonText);

            modal.remove();
            appendMessage("Delete Account Request", 'user-message');

            setTimeout(() => {
                appendMessage("Your request has been submitted. Our team will contact you shortly.", 'bot-message');
            }, 500);
        });
    }

    // ============================================================================
    // Event Listeners
    // ============================================================================

    toggleBtn.addEventListener('click', toggleChat);
    closeBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        toggleChat();
    });

    fileAttachBtn.addEventListener('click', function () {
        fileInput.click();
    });

    fileInput.addEventListener('change', function (e) {
        const file = e.target.files[0];
        if (file) showDocumentPreviewModal(file);
    });

    sendBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') sendMessage();
    });

    // ============================================================================
    // Initialization
    // ============================================================================

    const issuesUrl = window.issuesUrl || 'static/js/issues.json';
    fetch(issuesUrl)
        .then(response => response.json())
        .then(data => {
            troubleshootingSteps = data.troubleshooting;
            mainOptions = data.mainOptions;
            appRelatedOptions = data.appRelatedOptions;
            deleteAccountReasons = data.deleteAccountReasons;
        })
        .catch(error => console.error('Error loading issues:', error));

    initializeChatSession();

    // Debug functions
    window.debugWebSocket = {
        status: () => sunshineSocket ? {
            connected: sunshineSocket.connected,
            readyState: sunshineSocket.socket?.readyState,
            userId: sunshineSocket.userId,
            conversationId: sunshineSocket.conversationId
        } : 'No WebSocket instance',
        reconnect: () => sunshineSocket ? sunshineSocket.connect() : 'No instance',
        test: () => {
            if (!sunshineSocket || !sunshineSocket.connected) {
                console.log('❌ WebSocket not connected');
                return;
            }
            
            const testMsg = {
                type: 'test',
                payload: { test: 'WebSocket is working!', timestamp: Date.now() }
            };
            
            sunshineSocket.send(testMsg);
            console.log('✅ Test message sent via WebSocket');
        }
    };
});