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
    
    // New conversation list elements
    const conversationListView = document.querySelector('.conversation-list-view');
    const conversationList = document.querySelector('.conversation-list');
    const chatView = document.querySelector('.chat-view');
    const newConversationBtn = document.querySelector('.new-conversation-btn');
    const backBtn = document.querySelector('.chat-back-btn');

    let isChatOpen = false;
    let awaitingFeedback = false;
    let appUserId = null;
    let conversationId = null;
    let lastContext = "General Inquiry";
    let displayedMessageIds = new Set();
    let displayedImageFileNames = new Set();
    let pendingImage = null;
    let pendingLocalMessages = new Set();
    
    // Current view state
    let currentView = 'list'; // 'list' or 'chat'

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
    // CONVERSATION LIST MANAGEMENT
    // ============================================================================
    
    function getStoredConversations() {
        const stored = localStorage.getItem('chat_conversations');
        return stored ? JSON.parse(stored) : [];
    }
    
    function saveConversation(convId, title, lastMessage, timestamp) {
        let conversations = getStoredConversations();
        
        // Check if conversation already exists
        const existingIndex = conversations.findIndex(c => c.id === convId);
        
        const convData = {
            id: convId,
            title: title || 'Conversation',
            lastMessage: lastMessage || '',
            timestamp: timestamp || new Date().toISOString(),
            updatedAt: new Date().toISOString()
        };
        
        if (existingIndex >= 0) {
            conversations[existingIndex] = { ...conversations[existingIndex], ...convData };
        } else {
            conversations.unshift(convData);
        }
        
        // Keep only last 50 conversations
        conversations = conversations.slice(0, 50);
        
        localStorage.setItem('chat_conversations', JSON.stringify(conversations));
        renderConversationList();
    }
    
    function renderConversationList() {
        const conversations = getStoredConversations();
        
        if (conversations.length === 0) {
            conversationList.innerHTML = `
                <div class="no-conversations">
                    <div class="no-conv-icon">💬</div>
                    <p>No conversations yet</p>
                    <p class="no-conv-subtext">Start a new conversation to get help</p>
                </div>
            `;
            return;
        }
        
        conversationList.innerHTML = conversations.map(conv => {
            const timeAgo = getTimeAgo(conv.updatedAt || conv.timestamp);
            const preview = conv.lastMessage ? conv.lastMessage.substring(0, 40) + (conv.lastMessage.length > 40 ? '...' : '') : 'No messages';
            
            return `
                <div class="conversation-item" data-conv-id="${conv.id}">
                    <div class="conversation-icon">💬</div>
                    <div class="conversation-details">
                        <div class="conversation-title">${conv.title}</div>
                        <div class="conversation-preview">${preview}</div>
                    </div>
                    <div class="conversation-time">${timeAgo}</div>
                </div>
            `;
        }).join('');
        
        // Add click handlers
        conversationList.querySelectorAll('.conversation-item').forEach(item => {
            item.addEventListener('click', () => {
                const convId = item.getAttribute('data-conv-id');
                openExistingConversation(convId);
            });
        });
    }
    
    function getTimeAgo(timestamp) {
        if (!timestamp) return '';
        const now = new Date();
        const then = new Date(timestamp);
        const diffMs = now - then;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);
        
        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays < 7) return `${diffDays}d ago`;
        return then.toLocaleDateString();
    }
    
    function showConversationList() {
        console.log('📋 [VIEW] Switching to conversation list view');
        currentView = 'list';
        conversationListView.style.display = 'flex';
        chatView.style.display = 'none';
        backBtn.style.display = 'none';
        chatHeaderTitle.textContent = 'Yatri Bandhu';
        
        // Reset current conversation state but keep the data
        if (conversationId) {
            // Save state before switching - include agent name for restoration
            const agentName = localStorage.getItem('chat_agentName') || 'Agent';
            const convState = {
                isAgentConnected: isAgentConnected,
                agentJoinAnnounced: agentJoinAnnounced,
                agentName: agentName
            };
            localStorage.setItem(`chat_conv_state_${conversationId}`, JSON.stringify(convState));
        }
        
        renderConversationList();
    }
    
    function showChatView() {
        console.log('💬 [VIEW] Switching to chat view');
        currentView = 'chat';
        conversationListView.style.display = 'none';
        chatView.style.display = 'flex';
        backBtn.style.display = 'block';
    }
    
    function openExistingConversation(convId) {
        console.log('📂 [CONV] Opening existing conversation:', convId);
        
        // Set the conversation ID
        conversationId = convId;
        localStorage.setItem('chat_current_conversation', convId);
        
        // Restore appUserId for this conversation
        const storedAppUserId = localStorage.getItem(`chat_appUserId_${convId}`);
        if (storedAppUserId) {
            appUserId = storedAppUserId;
            console.log('📂 [CONV] Restored appUserId:', appUserId.substring(0, 10) + '...');
        } else {
            console.warn('⚠️ [CONV] No stored appUserId for this conversation');
        }
        
        // Clear display state but DON'T clear the container yet
        displayedMessageIds.clear();
        displayedImageFileNames.clear();
        
        // Load conversation state from storage (per-conversation state)
        const convState = localStorage.getItem(`chat_conv_state_${convId}`);
        let restoredAgentName = 'Agent';
        if (convState) {
            try {
                const state = JSON.parse(convState);
                isAgentConnected = state.isAgentConnected || false;
                agentJoinAnnounced = state.agentJoinAnnounced || false;
                restoredAgentName = state.agentName || 'Agent';
                console.log('📂 [CONV] Restored state:', { isAgentConnected, agentJoinAnnounced, agentName: restoredAgentName });
            } catch (e) {
                console.error('❌ [CONV] Failed to parse conversation state:', e);
                isAgentConnected = false;
                agentJoinAnnounced = false;
            }
        } else {
            isAgentConnected = false;
            agentJoinAnnounced = false;
        }
        
        // Clear messages container BEFORE fetching new messages
        messagesContainer.innerHTML = '';
        
        // Switch to chat view
        showChatView();
        
        // Show/hide input based on agent connection
        if (isAgentConnected) {
            chatInputArea.style.display = 'flex';
            chatHeaderTitle.textContent = restoredAgentName;
            // Also update global storage for compatibility
            localStorage.setItem('chat_agentName', restoredAgentName);
        } else {
            chatInputArea.style.display = 'none';
            chatHeaderTitle.textContent = 'Yatri Bandhu';
        }
        
        // Disconnect existing WebSocket
        if (sunshineSocket) {
            sunshineSocket.disconnect();
            sunshineSocket = null;
        }
        
        // Connect new WebSocket
        sunshineSocket = new SunshineWebSocketManager(conversationId);
        sunshineSocket.connect();
        
        // Fetch messages for this conversation
        fetchMessages();
    }
    
    function startNewConversation() {
        console.log('🆕 [CONV] Starting new conversation flow (no API call yet)');
        
        // Reset all state - but DON'T create conversation yet
        conversationId = null;
        appUserId = null;
        displayedMessageIds.clear();
        displayedImageFileNames.clear();
        isAgentConnected = false;
        agentJoinAnnounced = false;
        hasConfirmedAgentActivity = false;
        sessionEnded = false;
        lastContext = "General Inquiry";
        window.lastAppRelatedCategory = null;
        
        // Clear current conversation from storage
        localStorage.removeItem('chat_current_conversation');
        localStorage.removeItem('chat_isAgentConnected');
        localStorage.removeItem('chat_agentJoinAnnounced');
        localStorage.removeItem('chat_hasConfirmedAgentActivity');
        localStorage.removeItem('chat_agentName');
        
        // Disconnect existing WebSocket
        if (sunshineSocket) {
            sunshineSocket.disconnect();
            sunshineSocket = null;
        }
        
        // Clear messages container
        messagesContainer.innerHTML = '';
        
        // Switch to chat view
        showChatView();
        chatInputArea.style.display = 'none';
        chatHeaderTitle.textContent = 'Yatri Bandhu';
        
        // Show welcome message and options WITHOUT creating a conversation
        // Conversation will be created only when user clicks "Connect to Agent"
        appendMessage("Hello! 👋 How can I help you today?", 'bot-message');
        showMainOptions();
    }
    
    function createConversationAndEscalate(reason, category) {
        // This function creates the conversation ONLY when user wants to connect to agent
        console.log('🚀 [CHAT] Creating conversation for escalation...');
        console.log('🚀 [CHAT] Reason:', reason, 'Category:', category);

        const storedUserId = localStorage.getItem('chat_user_id');
        const payload = {
            userId: storedUserId || null,
            forceNew: true
        };

        fetch('/api/chat/init', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(response => {
                if (!response.ok) {
                    return response.text().then(text => {
                        console.error('❌ [CHAT] Server error:', text);
                        throw new Error(`HTTP ${response.status}: ${text}`);
                    });
                }
                return response.json();
            })
            .then(data => {
                if (data.appUserId && data.conversationId) {
                    appUserId = data.appUserId;
                    conversationId = data.conversationId;

                    if (data.externalId) {
                        localStorage.setItem('chat_user_id', data.externalId);
                    }
                    
                    // Store appUserId for this conversation (for restoration after refresh)
                    localStorage.setItem(`chat_appUserId_${conversationId}`, appUserId);

                    console.log("✅ [CHAT] Conversation created:", {
                        conversationId: conversationId.substring(0, 10) + '...'
                    });
                    
                    // Save to storage
                    localStorage.setItem('chat_current_conversation', conversationId);
                    saveConversation(conversationId, category || 'Support Request', '', new Date().toISOString());

                    // Initialize WebSocket
                    sunshineSocket = new SunshineWebSocketManager(conversationId);
                    sunshineSocket.connect();
                    
                    // NOW escalate to agent
                    performEscalation(reason, category);

                } else {
                    console.error("❌ [CHAT] Failed to create conversation:", data);
                    appendMessage("Failed to connect. Please try again.", 'system-message');
                }
            })
            .catch(error => {
                console.error('❌ [CHAT] Error creating conversation:', error);
                appendMessage("Connection error. Please try again.", 'system-message');
            });
    }
    
    function performEscalation(reason, category) {
        // Actually perform the escalation API call
        console.log('🚀 [ESCALATE] Escalating to agent...');
        
        fetch('/api/chat/escalate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                conversationId: conversationId,
                appUserId: appUserId,
                reason: reason || lastContext,
                appRelatedCategory: category || window.lastAppRelatedCategory
            })
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                console.log("✅ [ESCALATE] Success:", data);
                
                // Set agent connected state
                isAgentConnected = true;
                lastAgentRequestTime = Date.now();
                agentJoinAnnounced = false;
                localStorage.setItem('chat_isAgentConnected', 'true');
                localStorage.setItem('chat_lastAgentRequestTime', lastAgentRequestTime.toString());
                localStorage.setItem('chat_agentJoinAnnounced', 'false');
                
                // Show loading and enable input
                showLoadingIndicator();
                chatInputArea.style.display = 'flex';
                chatInput.focus();
            })
            .catch(error => {
                console.error('❌ [ESCALATE] Error:', error);
                appendMessage("Error connecting to agent. Please try again.", 'system-message');
            });
    }

    // ============================================================================
    // FIXED: Sunshine WebSocket Manager - SIMPLIFIED & GUARANTEED TO WORK
    // ============================================================================
    class SunshineWebSocketManager {
        constructor(conversationId) {
            this.conversationId = conversationId;
            this.socket = null;
            this.connected = false;
            this.reconnectAttempts = 0;
            this.maxReconnectAttempts = 10;
            this.pingInterval = null;
            this.messageHandler = null;

            console.log(`🎯 [WEBSOCKET] Manager created for conversation: ${conversationId}`);
        }

        connect() {
            if (!this.conversationId) {
                console.error('❌ [WEBSOCKET] Cannot connect: missing conversationId');
                return;
            }

            // Close existing connection
            if (this.socket) {
                this.disconnect();
            }

            // Create WebSocket URL - use secure when page is https, otherwise plain ws
            const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
            const wsUrl = `${wsProtocol}://${window.location.host}/ws/chat/${this.conversationId}/`;

            console.log('🔌 [WEBSOCKET] Connecting to:', wsUrl);

            this.socket = new WebSocket(wsUrl);

            this.socket.onopen = () => {
                console.log('✅ [WEBSOCKET] CONNECTED!');
                this.connected = true;
                this.reconnectAttempts = 0;
                webSocketConnected = true;

                // Start ping interval (25 seconds for keepalive)
                this.startPingInterval();

                // Log success
                console.log(`✅ [WEBSOCKET] ReadyState: ${this.socket.readyState} (OPEN=1)`);

                // Send connection established test message
                this.send({
                    type: 'echo',
                    message: 'WebSocket connected',
                    timestamp: Date.now()
                });
            };

            this.socket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    console.log('📨 [WEBSOCKET] Received:', data.type || 'unknown');

                    // Handle different message types
                    this.handleIncomingMessage(data);

                } catch (error) {
                    console.error('❌ [WEBSOCKET] Error parsing message:', error);
                }
            };

            this.socket.onerror = (error) => {
                console.error('❌ [WEBSOCKET] Error:', error);
            };

            this.socket.onclose = (event) => {
                console.log(`🔌 [WEBSOCKET] CLOSED: Code ${event.code}, Reason: ${event.reason}`);
                this.connected = false;
                webSocketConnected = false;

                // Clear ping interval
                if (this.pingInterval) {
                    clearInterval(this.pingInterval);
                    this.pingInterval = null;
                }

                // Auto-reconnect (except for normal closure)
                if (!sessionEnded && event.code !== 1000) {
                    this.reconnect();
                }
            };
        }

        startPingInterval() {
            // Clear existing interval
            if (this.pingInterval) {
                clearInterval(this.pingInterval);
            }

            // Send ping every 25 seconds to keep connection alive
            this.pingInterval = setInterval(() => {
                if (this.socket && this.socket.readyState === WebSocket.OPEN) {
                    this.send({
                        type: 'ping',
                        timestamp: Date.now()
                    });
                    console.log('🏓 [WEBSOCKET] Sent ping');
                }
            }, 25000);
        }

        send(data) {
            if (this.socket && this.socket.readyState === WebSocket.OPEN) {
                try {
                    this.socket.send(JSON.stringify(data));
                    console.log('📤 [WEBSOCKET] Sent:', data.type || 'unknown');
                    return true;
                } catch (error) {
                    console.error('❌ [WEBSOCKET] Send error:', error);
                    return false;
                }
            } else {
                console.warn('⚠️ [WEBSOCKET] Not ready to send. State:', this.socket?.readyState);
                return false;
            }
        }

        handleIncomingMessage(data) {
            // Handle connection established
            if (data.type === 'connection_established') {
                console.log('✅ [WEBSOCKET] ' + data.message);
                console.log('✅ [WEBSOCKET] Group:', data.group_name);
                return;
            }

            // Handle pong response
            if (data.type === 'pong') {
                console.log('🏓 [WEBSOCKET] Pong received');
                return;
            }

            // Handle echo response
            if (data.type === 'echo_response') {
                console.log('📨 [WEBSOCKET] Echo response received');
                return;
            }

            // Handle keepalive
            if (data.type === 'keepalive') {
                console.log('💓 [WEBSOCKET] Keepalive received');
                return;
            }

            // 🎯 CRITICAL: Handle agent messages
            if (data.type === 'agent_message') {
                console.log('🎯 [WEBSOCKET] AGENT MESSAGE received!');
                this.processAgentMessage(data.payload || data);
                return;
            }

            // Handle error
            if (data.type === 'error') {
                console.error('❌ [WEBSOCKET] Error from server:', data.message);
                return;
            }

            // Handle other message types
            console.log('📨 [WEBSOCKET] Unhandled type:', data.type, 'Data:', JSON.stringify(data).substring(0, 200));
        }

        processAgentMessage(message) {
            console.log('🎯 [WEBSOCKET] Processing agent message:', message);

            // Check if this is an agent message
            const isAgent = message.author && (
                message.author.type === 'business' ||
                message.author.type === 'agent' ||
                message.source === 'zendesk' ||
                message.author.role === 'agent'
            );

            if (!isAgent) {
                console.log('⚠️ [WEBSOCKET] Not an agent message:', message.author?.type, message.source);
                return;
            }

            // Extract text content
            const text = message.content?.text || message.text || '';
            const messageId = message.id || `agent_${Date.now()}`;
            const agentName = message.author?.displayName || 'Agent';

            console.log(`🎯 [WEBSOCKET] Agent: ${agentName}, Text: ${text.substring(0, 100)}...`);

            // Skip duplicates
            if (displayedMessageIds.has(messageId)) {
                console.log('⚠️ [WEBSOCKET] Duplicate message ID, skipping:', messageId);
                return;
            }

            // First agent message: replace loading indicator with single agent announcement
            if (!agentJoinAnnounced) {
                removeLoadingIndicator();
                appendMessage(`${agentName} will help you now.`, 'system-message');
                agentJoinAnnounced = true;
                localStorage.setItem('chat_agentJoinAnnounced', 'true');
                localStorage.setItem('chat_agentName', agentName);
                chatInputArea.style.display = 'flex';
                chatHeaderTitle.textContent = agentName;
                console.log(`🎯 [WEBSOCKET] Announced agent: ${agentName}`);
                
                // Scroll after agent announcement
                ensureScrollToBottom();
            }

            // Render the agent message (no per-message agent name)
            displayedMessageIds.add(messageId);
            appendMessage(text, 'bot-message');
            
            // Ensure scroll after agent message
            ensureScrollToBottom();
            showMessageReceivedIndicator();
        }

        reconnect() {
            if (this.reconnectAttempts >= this.maxReconnectAttempts || sessionEnded) {
                console.log('❌ [WEBSOCKET] Max reconnection attempts reached');
                return;
            }

            this.reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), 10000);

            console.log(`🔄 [WEBSOCKET] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

            setTimeout(() => {
                console.log('🔄 [WEBSOCKET] Attempting reconnect...');
                this.connect();
            }, delay);
        }

        disconnect() {
            console.log('🔌 [WEBSOCKET] Disconnecting...');

            if (this.pingInterval) {
                clearInterval(this.pingInterval);
                this.pingInterval = null;
            }

            if (this.socket) {
                this.socket.close(1000, 'User disconnected');
                this.socket = null;
            }

            this.connected = false;
            webSocketConnected = false;
        }

        // Test function to verify WebSocket is working
        testConnection() {
            if (!this.connected) {
                console.log('❌ [WEBSOCKET-TEST] Not connected');
                return false;
            }

            // Send test message
            const testResult = this.send({
                type: 'test_agent_message',
                message: 'Test message from debug function',
                timestamp: Date.now()
            });

            console.log(`✅ [WEBSOCKET-TEST] Test message ${testResult ? 'sent' : 'failed to send'}`);
            return testResult;
        }
    }

    // ============================================================================
    // Core Functions
    // ============================================================================

    function initializeChatSession() {
        console.log('🚀 [CHAT] Initializing chat session...');

        const storedUserId = localStorage.getItem('chat_user_id');
        const payload = storedUserId ? { userId: storedUserId } : {};

        fetch('/api/chat/init', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.appUserId && data.conversationId) {
                    appUserId = data.appUserId;
                    conversationId = data.conversationId;

                    if (data.externalId) {
                        localStorage.setItem('chat_user_id', data.externalId);
                    }

                    console.log("✅ [CHAT] Initialized:", {
                        appUserId: appUserId.substring(0, 10) + '...',
                        conversationId: conversationId.substring(0, 10) + '...'
                    });
                    
                    // Save to current conversation
                    localStorage.setItem('chat_current_conversation', conversationId);
                    
                    // Save to conversation list
                    saveConversation(conversationId, 'New Conversation', '', new Date().toISOString());

                    if (isAgentConnected) {
                        chatInputArea.style.display = 'flex';
                        chatHeaderTitle.textContent = "Agent";
                        console.log('✅ [CHAT] Agent already connected, showing input');
                    } else {
                        // Show welcome message and options for new conversations
                        appendMessage("Hello! 👋 How can I help you today?", 'bot-message');
                        showMainOptions();
                    }

                    // Initialize WebSocket
                    sunshineSocket = new SunshineWebSocketManager(conversationId);
                    sunshineSocket.connect();

                    // Add WebSocket test button for debugging
                    addWebSocketDebugButton();

                } else {
                    console.error("❌ [CHAT] Failed to initialize:", data);
                    appendMessage("Failed to initialize chat. Please refresh the page.", 'system-message');
                }
            })
            .catch(error => {
                console.error('❌ [CHAT] Error initializing:', error);
                // Removed UI display of connection error message as per request.
            });
    }

    function fetchMessages() {
        if (!conversationId) {
            console.warn('⚠️ [MESSAGES] No conversationId, skipping fetch');
            return;
        }

        console.log('📨 [MESSAGES] Fetching full history for:', conversationId.substring(0, 10) + '...');

        // Use the full-history endpoint that leverages Zendesk Conversation Log API
        fetch(`/api/chat/full-history?conversationId=${conversationId}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                console.log(`📨 [MESSAGES] Received ${data.messages?.length || 0} messages from ${data.source}`);

                // Restore appUserId from API response if we don't have it
                if (data.appUserId && !appUserId) {
                    appUserId = data.appUserId;
                    localStorage.setItem(`chat_appUserId_${conversationId}`, appUserId);
                    console.log(`📨 [MESSAGES] Restored appUserId from API: ${appUserId.substring(0, 10)}...`);
                }

                // If we have a ticket ID, we're in an escalated session
                if (data.ticket_id) {
                    console.log(`📨 [MESSAGES] Ticket ID: ${data.ticket_id}`);
                    if (!isAgentConnected) {
                        isAgentConnected = true;
                        localStorage.setItem('chat_isAgentConnected', 'true');
                        chatInputArea.style.display = 'flex';
                    }
                }

                if (!data.messages || data.messages.length === 0) {
                    console.log('📨 [MESSAGES] No messages in response');
                    return;
                }

                const sortedMessages = data.messages.sort(
                    (a, b) => new Date(a.received) - new Date(b.received)
                );

                console.log(`📨 [MESSAGES] Processing ${sortedMessages.length} messages`);

                let hasNewMessages = false;

                sortedMessages.forEach((msg, index) => {
                    if (!msg || !msg.id) return;

                    // Skip if already displayed
                    if (displayedMessageIds.has(msg.id)) {
                        return;
                    }

                    displayedMessageIds.add(msg.id);
                    hasNewMessages = true;

                    // Determine CSS class based on messageClass from backend
                    let cssClass = 'bot-message';
                    if (msg.messageClass === 'user') {
                        cssClass = 'user-message';
                    } else if (msg.messageClass === 'agent') {
                        cssClass = 'bot-message';  // Agent messages styled like bot
                    } else if (msg.messageClass === 'system') {
                        cssClass = 'system-message';
                    }

                    const authorName = msg.author?.displayName || '';
                    const isAgent = msg.messageClass === 'agent';

                    // Announce agent once
                    if (isAgent && !agentJoinAnnounced && authorName) {
                        removeLoadingIndicator();
                        appendMessage(`${authorName} joined the chat`, 'system-message');
                        agentJoinAnnounced = true;
                        localStorage.setItem('chat_agentJoinAnnounced', 'true');
                        localStorage.setItem('chat_agentName', authorName);
                        chatInputArea.style.display = 'flex';
                        chatHeaderTitle.textContent = authorName;
                    }

                    // Handle attachments (images/files)
                    if (msg.attachments && msg.attachments.length > 0) {
                        console.log(`🖼️ [MESSAGES] Processing ${msg.attachments.length} attachment(s)`);
                        msg.attachments.forEach(att => {
                            console.log(`🖼️ [MESSAGES] Attachment: type=${att.type}, url=${att.url?.substring(0, 80)}...`);
                            if (att.type === 'image' && att.url) {
                                const fileName = att.url.split('/').pop() || 'image';
                                if (!displayedImageFileNames.has(fileName)) {
                                    displayedImageFileNames.add(fileName);
                                    console.log(`🖼️ [MESSAGES] Appending image: ${fileName}`);
                                    appendImageMessage(att.url, msg.text || '', cssClass);
                                }
                            } else if (att.type === 'file' && att.url) {
                                console.log(`📎 [MESSAGES] Appending file: ${att.fileName}`);
                                appendFileMessage(
                                    att.fileName || 'file',
                                    formatFileSize(att.size || 0),
                                    cssClass,
                                    msg.text || ''
                                );
                            }
                        });
                        // If there's text with attachment, don't show text again
                        if (msg.text && msg.attachments.some(a => a.type === 'image')) {
                            return;
                        }
                    }

                    // Display text message
                    if (msg.text) {
                        // Skip certain system messages
                        if (msg.text.includes('Connecting to agent') || 
                            msg.text.includes('Escalation Reason:')) {
                            return;
                        }
                        appendMessage(msg.text, cssClass);
                    }
                });

                if (hasNewMessages) {
                    ensureScrollToBottom();
                    console.log('📨 [MESSAGES] Added new messages, scrolling to bottom');
                }

                // Session end detection
                if (sortedMessages.length > 0 && isAgentConnected) {
                    const lastMsg = sortedMessages[sortedMessages.length - 1];
                    if (lastMsg.text) {
                        const text = lastMsg.text.toLowerCase();
                        const isEndSession = text.includes("messaging session ended") ||
                            text.includes("the agent has ended the session");
                        
                        if (isEndSession) {
                            console.log('🔚 [MESSAGES] Detected session end');
                            endSession();
                        }
                    }
                }

                console.log('✅ [MESSAGES] Fetch complete');
            })
            .catch(error => {
                console.error('❌ [MESSAGES] Error fetching:', error);
            });
    }

    function endSession() {
        console.log("🔚 [SESSION] Ending session...");
        isAgentConnected = false;
        agentJoinAnnounced = false;
        hasConfirmedAgentActivity = false;
        sessionEnded = true;

        if (sunshineSocket) {
            sunshineSocket.disconnect();
        }

        localStorage.removeItem('chat_isAgentConnected');
        localStorage.removeItem('chat_agentJoinAnnounced');
        localStorage.removeItem('chat_hasConfirmedAgentActivity');

        chatInputArea.style.display = 'none';
        chatHeaderTitle.textContent = "Yatri Bandhu";
        appendMessage("What can I help you with?", 'bot-message');
        showMainOptions();

        console.log('✅ [SESSION] Session ended');
    }

    function handleAgentConnect(option) {
        appendMessage(option, 'user-message');
        
        // If conversation doesn't exist yet, create it first then escalate
        if (!conversationId) {
            console.log('🆕 [AGENT] No conversation yet, creating one first...');
            createConversationAndEscalate(lastContext, window.lastAppRelatedCategory);
        } else {
            // Conversation already exists, just escalate
            console.log('🔄 [AGENT] Conversation exists, escalating...');
            performEscalation(lastContext, window.lastAppRelatedCategory);
        }
    }

    // ============================================================================
    // Helper Functions
    // ============================================================================

    // Debug button removed

    function showMessageReceivedIndicator() {
        // Add visual indicator that a message was received
        const indicator = document.createElement('div');
        indicator.className = 'message-received-indicator';
        indicator.textContent = '📨';
        indicator.style.position = 'absolute';
        indicator.style.top = '10px';
        indicator.style.right = '10px';
        indicator.style.fontSize = '20px';
        indicator.style.animation = 'pulse 1s';

        const chatBoxHeader = document.querySelector('.chat-header');
        if (chatBoxHeader) {
            chatBoxHeader.appendChild(indicator);

            // Remove after animation
            setTimeout(() => {
                indicator.remove();
            }, 1000);
        }
    }

    function sendToSunshine(text) {
        if (!appUserId || !conversationId) {
            console.error("❌ [SEND] Cannot send: Chat not initialized");
            return;
        }

        console.log('📤 [SEND] Sending to Sunshine:', text.substring(0, 50) + '...');

        fetch('/api/chat/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                appUserId: appUserId,
                conversationId: conversationId,
                text: text
            })
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                console.log("✅ [SEND] Success:", data);
                if (data.data?.messages?.length > 0) {
                    const msgId = data.data.messages[0].id;
                    displayedMessageIds.add(msgId);
                    try {
                        const echoedText = data.data.messages[0].content?.text;
                        if (echoedText) pendingLocalMessages.delete(echoedText);
                    } catch (e) { }
                }
            })
            .catch(error => console.error('❌ [SEND] Error:', error));
    }

    function toggleChat() {
        isChatOpen = !isChatOpen;
        if (isChatOpen) {
            chatBox.style.display = 'flex';
            toggleBtn.innerHTML = '✖';
            toggleBtn.setAttribute('aria-label', 'Close chat');

            // Check if there was an active conversation
            const activeConvId = localStorage.getItem('chat_current_conversation');
            const wasInChat = currentView === 'chat' && conversationId;
            
            if (activeConvId && wasInChat && messagesContainer.children.length > 0) {
                // User was in a conversation before closing - just show the chat view again
                console.log('💬 [CHAT] Restoring active conversation:', activeConvId.substring(0, 10) + '...');
                showChatView();
                
                // Reconnect WebSocket if needed
                if (!sunshineSocket || !sunshineSocket.socket?.readyState === WebSocket.OPEN) {
                    sunshineSocket = new SunshineWebSocketManager(conversationId);
                    sunshineSocket.connect();
                }
                
                // Fetch any new messages
                fetchMessages();
            } else {
                // Show conversation list
                showConversationList();
                console.log('💬 [CHAT] Opened chat - showing conversation list');
            }
        } else {
            chatBox.style.display = 'none';
            toggleBtn.innerHTML = '💬';
            toggleBtn.setAttribute('aria-label', 'Open chat');
            
            // Disconnect WebSocket when closing
            if (sunshineSocket) {
                sunshineSocket.disconnect();
            }

            console.log('💬 [CHAT] Closed chat');
        }
    }

    function showMainOptions() {
        const options = mainOptions.length > 0 ? mainOptions : ["App Related Issues", "Ride Related Issues", "Delete Account"];
        console.log('📋 [UI] Showing main options:', options);
        appendOptions(options, handleMainOptionClick);
    }

    function handleMainOptionClick(option) {
        console.log('📋 [UI] Main option selected:', option);
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
        console.log('📋 [UI] Showing app options:', options);
        appendOptions(options, handleAppRelatedOptionClick);
    }

    function handleAppRelatedOptionClick(option) {
        console.log('📋 [UI] App option selected:', option);
        appendMessage(option, 'user-message');
        lastContext = option;

        // Store the selected category globally for escalation
        window.lastAppRelatedCategory = option;  // NEW: Store category

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
        console.log('📋 [UI] Feedback selected:', option);
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
        ensureScrollToBottom();

        console.log('⏳ [UI] Showing loading indicator');
    }

    function removeLoadingIndicator() {
        const loader = document.getElementById('agent-loading-indicator');
        if (loader) {
            loader.remove();
            console.log('✅ [UI] Removed loading indicator');
        }
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

        console.log('📤 [UI] Sending message:', messageText);
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
        console.log(`💬 [UI] Appending ${className}:`, text.substring(0, 50) + '...');

        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', className);
        messageDiv.style.whiteSpace = "pre-wrap";
        messageDiv.textContent = text;
        messagesContainer.appendChild(messageDiv);
        
        // Ensure scroll to bottom after message is added
        ensureScrollToBottom();
    }

    function appendImageMessage(imageUrl, caption, className) {
        console.log('🖼️ [UI] Appending image:', imageUrl.substring(0, 50) + '...');

        // NOTE: Removed zendesk.com filter - Conversation Log API returns valid Zendesk-hosted image URLs
        // These URLs are authenticated and should work for display

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
        ensureScrollToBottom();
    }

    function appendFileMessage(fileName, fileSize, className, caption = '') {
        console.log('📎 [UI] Appending file:', fileName);

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
        ensureScrollToBottom();
    }

    function appendOptions(options, callback) {
        console.log('📋 [UI] Appending options:', options);

        const optionsDiv = document.createElement('div');
        optionsDiv.classList.add('options-container');

        options.forEach(option => {
            const btn = document.createElement('button');
            btn.classList.add('option-btn');
            btn.textContent = option;
            btn.addEventListener('click', function () {
                console.log('📋 [UI] Option clicked:', option);
                optionsDiv.remove();
                callback(option);
            });
            optionsDiv.appendChild(btn);
        });

        messagesContainer.appendChild(optionsDiv);
        
        // Scroll after a small delay to ensure options are rendered
        setTimeout(() => scrollToBottom(), 50);
    }

    function scrollToBottom() {
        if (messagesContainer) {
            // Use requestAnimationFrame for smoother scrolling
            requestAnimationFrame(() => {
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            });
        }
    }
    
    // Auto-scroll helper - call this after any content change
    function ensureScrollToBottom() {
        // Multiple attempts to ensure scroll happens after render
        scrollToBottom();
        setTimeout(scrollToBottom, 100);
        setTimeout(scrollToBottom, 300);
    }

    // ============================================================================
    // File Handling Functions (with added logging)
    // ============================================================================

    function showDocumentPreviewModal(file) {
        console.log('📎 [FILE] Previewing file:', file.name, file.type);

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
            console.log('📎 [FILE] Closing preview modal');
            modal.remove();
        });

        header.appendChild(filename);
        header.appendChild(closeBtn);

        const body = document.createElement('div');
        body.classList.add('document-preview-body');

        const info = document.createElement('div');
        info.classList.add('document-preview-info');

        if (file.type.startsWith('image/')) {
            console.log('📎 [FILE] Displaying image preview');
            const img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            img.style.maxWidth = '100%';
            img.style.maxHeight = '100%';
            img.style.objectFit = 'contain';
            img.style.borderRadius = '12px';
            info.appendChild(img);
        } else {
            console.log('📎 [FILE] Displaying file icon preview');
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
            console.log('📎 [FILE] Send button clicked for:', file.name);
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

        console.log('📎 [FILE] Preview modal displayed');
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
        console.log('📎 [FILE] Sending document:', file.name, 'Size:', formatFileSize(file.size));

        if (!appUserId || !conversationId) {
            console.error("❌ [FILE] Cannot send document: Chat not initialized");
            appendMessage("Error: Chat not initialized. Please refresh and try again.", 'system-message');
            return;
        }

        const isImage = file.type.startsWith('image/');
        console.log('📎 [FILE] Is image:', isImage);

        if (isImage) {
            const imageUrl = URL.createObjectURL(file);
            appendImageMessage(imageUrl, '', 'user-message');
            displayedImageFileNames.add(file.name);
            console.log('📎 [FILE] Image preview added to chat');
        }

        const formData = new FormData();
        formData.append('file', file);
        formData.append('appUserId', appUserId);
        formData.append('conversationId', conversationId);
        if (message && !isImage) {
            formData.append('message', message);
            console.log('📎 [FILE] Added caption:', message);
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
            ensureScrollToBottom();
            console.log('📎 [FILE] Added progress container');
        }

        const progressFill = progressContainer ? progressContainer.querySelector('.upload-progress-fill') : null;
        const statusText = progressContainer ? progressContainer.querySelector('.upload-status') : null;

        const xhr = new XMLHttpRequest();
        console.log('📎 [FILE] Starting upload...');

        xhr.upload.addEventListener('progress', function (e) {
            if (e.lengthComputable && progressContainer) {
                const percentComplete = (e.loaded / e.total) * 100;
                progressFill.style.width = percentComplete + '%';
                statusText.textContent = `Uploading... ${Math.round(percentComplete)}%`;
                console.log('📎 [FILE] Upload progress:', Math.round(percentComplete) + '%');
            }
        });

        xhr.addEventListener('load', function () {
            console.log('📎 [FILE] Upload complete. Status:', xhr.status);

            if (xhr.status === 200) {
                try {
                    const data = JSON.parse(xhr.responseText);
                    console.log("✅ [FILE] Document sent successfully:", data);

                    if (data.data?.messages) {
                        data.data.messages.forEach(msg => {
                            displayedMessageIds.add(msg.id);
                        });
                        console.log('📎 [FILE] Added message IDs from response');
                    }

                    if (progressContainer) {
                        statusText.textContent = 'Sent successfully!';
                        progressFill.style.backgroundColor = '#28a745';
                        progressContainer.classList.add('upload-complete');
                        console.log('✅ [FILE] Upload marked as complete');

                        setTimeout(() => {
                            progressContainer.remove();
                            console.log('📎 [FILE] Progress container removed');
                        }, 2000);
                    }
                } catch (e) {
                    console.error('❌ [FILE] Error parsing response:', e);
                    if (progressContainer) {
                        statusText.textContent = 'Error processing response';
                        progressFill.style.backgroundColor = '#dc3545';
                    }
                }
            } else {
                console.error('❌ [FILE] Upload failed:', xhr.status, xhr.responseText);
                if (progressContainer) {
                    statusText.textContent = 'Error sending document';
                    progressFill.style.backgroundColor = '#dc3545';
                }
                appendMessage("Failed to send file. Please try again.", 'system-message');
            }
        });

        xhr.addEventListener('error', function () {
            console.error('❌ [FILE] Network error sending document');
            if (progressContainer) {
                statusText.textContent = 'Network error - please try again';
                progressFill.style.backgroundColor = '#dc3545';
            }
            appendMessage("Network error. Please check your connection.", 'system-message');
        });

        xhr.addEventListener('abort', function () {
            console.log('📎 [FILE] Upload aborted');
            if (progressContainer) {
                statusText.textContent = 'Upload cancelled';
                progressFill.style.backgroundColor = '#ffc107';
            }
        });

        xhr.open('POST', '/api/send-to-zendesk');
        xhr.send(formData);

        fileInput.value = '';
        console.log('📎 [FILE] File input cleared');
    }

    function showImageZoomModal(imageUrl) {
        console.log('🖼️ [FILE] Showing image zoom modal');

        const modal = document.createElement('div');
        modal.classList.add('zoom-modal');

        const img = document.createElement('img');
        img.src = imageUrl;
        modal.appendChild(img);

        modal.addEventListener('click', function () {
            console.log('🖼️ [FILE] Closing zoom modal');
            modal.remove();
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                console.log('🖼️ [FILE] Closing zoom modal with Escape key');
                modal.remove();
            }
        });

        document.body.appendChild(modal);
        console.log('🖼️ [FILE] Zoom modal displayed');
    }

    function showImagePreviewInInput(file) {
        console.log('🖼️ [FILE] Showing image preview in input');

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
        pendingImage = file;

        console.log('🖼️ [FILE] Image preview added to input');
    }

    function clearImagePreview() {
        console.log('🖼️ [FILE] Clearing image preview');

        const preview = document.getElementById('image-preview-container');
        if (preview) {
            preview.remove();
            console.log('🖼️ [FILE] Preview removed from DOM');
        }
        pendingImage = null;
        chatInput.placeholder = 'Type a message...';
        console.log('🖼️ [FILE] Input placeholder reset');
    }

    function showDeleteAccountModal() {
        console.log('🗑️ [UI] Showing delete account modal');

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

        console.log('🗑️ [UI] Delete reasons:', reasons);

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
                console.log('🗑️ [UI] Selected reason:', selectedReason);

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
        otherInput.style.display = 'none';
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
        console.log('🗑️ [UI] Delete modal added to DOM');

        function validateDeleteButton() {
            console.log('🗑️ [UI] Validating delete button, selectedReason:', selectedReason);

            if (selectedReason === "Others") {
                const hasText = otherInput.value.trim() !== "";
                deleteBtn.disabled = !hasText;
                console.log('🗑️ [UI] Others selected, has text:', hasText, 'disabled:', deleteBtn.disabled);
            } else {
                deleteBtn.disabled = selectedReason === null;
                console.log('🗑️ [UI] Regular reason, disabled:', deleteBtn.disabled);
            }
        }

        backBtn.addEventListener('click', function () {
            console.log('🗑️ [UI] Back button clicked');
            modal.remove();
            appendMessage("What can I help you with?", 'bot-message');
            showMainOptions();
        });

        deleteBtn.addEventListener('click', function () {
            console.log('🗑️ [UI] Delete button clicked');

            let reasonText = selectedReason;
            if (selectedReason === "Others") {
                const otherText = otherInput.value.trim();
                reasonText += ": " + otherText;
                console.log('🗑️ [UI] With other text:', otherText);
            }

            console.log('🗑️ [UI] Sending delete request:', reasonText);
            sendToSunshine("Delete Account Request: " + reasonText);

            modal.remove();
            appendMessage("Delete Account Request", 'user-message');

            setTimeout(() => {
                appendMessage("Your request has been submitted. Our team will contact you shortly.", 'bot-message');
                console.log('✅ [UI] Delete request completed');
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
    
    // New conversation button
    newConversationBtn.addEventListener('click', function () {
        console.log('🆕 [UI] New conversation button clicked');
        startNewConversation();
    });
    
    // Back button
    backBtn.addEventListener('click', function () {
        console.log('⬅️ [UI] Back button clicked');
        
        // Save current conversation state before going back - include agent name
        if (conversationId) {
            const agentName = localStorage.getItem('chat_agentName') || 'Agent';
            const convState = {
                isAgentConnected: isAgentConnected,
                agentJoinAnnounced: agentJoinAnnounced,
                agentName: agentName
            };
            localStorage.setItem(`chat_conv_state_${conversationId}`, JSON.stringify(convState));
        }
        
        // Disconnect WebSocket
        if (sunshineSocket) {
            sunshineSocket.disconnect();
        }
        
        showConversationList();
    });

    fileAttachBtn.addEventListener('click', function () {
        console.log('📎 [UI] File attach clicked');
        fileInput.click();
    });

    fileInput.addEventListener('change', function (e) {
        const file = e.target.files[0];
        if (file) {
            console.log('📎 [UI] File selected:', file.name);
            showDocumentPreviewModal(file);
        }
    });

    sendBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') sendMessage();
    });

    // ============================================================================
    // Initialization
    // ============================================================================

    console.log('🚀 [APP] Initializing chat widget...');

    const issuesUrl = window.issuesUrl || 'static/js/issues.json';
    fetch(issuesUrl)
        .then(response => response.json())
        .then(data => {
            troubleshootingSteps = data.troubleshooting;
            mainOptions = data.mainOptions;
            appRelatedOptions = data.appRelatedOptions;
            deleteAccountReasons = data.deleteAccountReasons;
            console.log('✅ [APP] Loaded issues data');
        })
        .catch(error => console.error('❌ [APP] Error loading issues:', error));

    // Load user ID if exists
    const storedUserId = localStorage.getItem('chat_user_id');
    if (storedUserId) {
        console.log('✅ [APP] Found stored user ID');
    }
    
    // Don't auto-start session - wait for user to open widget and select/create conversation

    // Restore last active conversation on page load
    const lastConversationId = localStorage.getItem('chat_current_conversation');
    if (lastConversationId) {
        console.log('🔄 [INIT] Restoring last active conversation:', lastConversationId);
        openExistingConversation(lastConversationId);
    } else {
        console.log('ℹ️ [INIT] No active conversation to restore');
        showConversationList();
    }

    // Global debug functions
    window.debugChat = {
        status: () => ({
            appUserId: appUserId ? appUserId.substring(0, 10) + '...' : null,
            conversationId: conversationId ? conversationId.substring(0, 10) + '...' : null,
            isAgentConnected,
            webSocketConnected,
            currentView,
            storedConversations: getStoredConversations().length,
            sunshineSocket: sunshineSocket ? {
                connected: sunshineSocket.connected,
                readyState: sunshineSocket.socket?.readyState,
                conversationId: sunshineSocket.conversationId
            } : 'No instance'
        }),
        testWebSocket: () => sunshineSocket ? sunshineSocket.testConnection() : 'No WebSocket',
        reconnect: () => sunshineSocket ? sunshineSocket.connect() : 'No WebSocket',
        sendTestMessage: () => {
            if (conversationId) {
                fetch('/api/debug/group_send', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        conversationId: conversationId,
                        text: 'Test message from debug console'
                    })
                }).then(r => r.json()).then(console.log);
            }
        },
        logDisplayedMessages: () => {
            console.log('Displayed message IDs:', Array.from(displayedMessageIds));
        },
        clearConversations: () => {
            localStorage.removeItem('chat_conversations');
            renderConversationList();
            console.log('✅ Cleared all conversations');
        }
    };

    console.log('✅ [APP] Chat widget initialized, debug functions available at window.debugChat');
});