document.addEventListener('DOMContentLoaded', function () {
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
    const conversationListView = document.querySelector('.conversation-list-view');
    const conversationList = document.querySelector('.conversation-list');
    const chatView = document.querySelector('.chat-view');
    const newConversationBtn = document.querySelector('.new-conversation-btn');
    const backBtn = document.querySelector('.chat-back-btn');

    let isChatOpen = false;
    let appUserId = null;
    let conversationId = null;
    let lastContext = "General Inquiry";
    let displayedMessageIds = new Set();
    let displayedImageFileNames = new Set();
    let pendingImage = null;
    let currentView = 'list'; // 'list' or 'chat'
    let sunshineSocket = null;
    let sessionEnded = false;
    let isAgentConnected = localStorage.getItem('chat_isAgentConnected') === 'true';
    let agentJoinAnnounced = localStorage.getItem('chat_agentJoinAnnounced') === 'true';
    let troubleshootingSteps = {};
    let mainOptions = [];
    let appRelatedOptions = [];
    let deleteAccountReasons = [];
    let unreadCounts = new Map(); // conversationId -> count
    let totalUnread = 0;
    let surveyMessageShown = false; // Track if survey has been displayed
    let lastMessageDate = null; // Track last message date for daily separator
    function initNotificationSystem() {
        loadUnreadCounts();
        calculateTotalUnread();
        updateBadges();
    }
    const updateUnreadUI = () => {calculateTotalUnread();saveUnreadCounts();updateBadges();};
    function loadUnreadCounts(){try{const stored=localStorage.getItem('chat_unread_counts');if(stored)unreadCounts=new Map(Object.entries(JSON.parse(stored)));calculateTotalUnread();}catch(e){}}
    const saveUnreadCounts=()=>{try{localStorage.setItem('chat_unread_counts',JSON.stringify(Object.fromEntries(unreadCounts)));}catch(e){}};
    const calculateTotalUnread=()=>{totalUnread=Array.from(unreadCounts.values()).reduce((s,c)=>s+c,0);};
    const incrementUnreadCount=(id,n=1)=>{if(!id)return;unreadCounts.set(id,(unreadCounts.get(id)||0)+n);updateUnreadUI();};
    const clearUnreadCount=id=>{if(!id||!unreadCounts.has(id))return;unreadCounts.delete(id);updateUnreadUI();};
    const updateBadges=()=>{updateToggleButtonBadge();updateConversationListBadges();updateTitleNotification();if(currentView==='list')renderConversationList();};
    const updateToggleButtonBadge=()=>{if(!toggleBtn)return;let b=document.querySelector('.chat-toggle-badge');if(!b){b=document.createElement('div');b.className='chat-toggle-badge';toggleBtn.style.position='relative';toggleBtn.appendChild(b);}b.style.display=totalUnread>0?'flex':'none';if(totalUnread>0)b.textContent=totalUnread>99?'99+':totalUnread;};
    const updateConversationListBadges=()=>{if(currentView!=='list')return;document.querySelectorAll('.conversation-item').forEach(item=>{const id=item.getAttribute('data-conv-id');if(!id)return;const c=unreadCounts.get(id)||0;let b=item.querySelector('.conversation-badge');if(c>0){if(!b){b=document.createElement('div');b.className='conversation-badge';item.style.position='relative';item.appendChild(b);}b.textContent=c>99?'99+':c;b.style.display='flex';item.classList.add('conversation-unread');}else{if(b)b.style.display='none';item.classList.remove('conversation-unread');}});};
    const updateTitleNotification=()=>{const o=document.title.replace(/^\(\d+\)\s*/,'');document.title=totalUnread>0?`(${totalUnread}) ${o}`:o;};
    const isViewingConversation=c=>!!(c&&isChatOpen&&currentView==='chat'&&conversationId===c);
    const setLS=(k,v)=>{try{localStorage.setItem(k,v);}catch(e){}};
    const getLS=k=>{try{return localStorage.getItem(k);}catch(e){}};
    let sseConnection = null;
    let sseReconnectAttempts = 0;
    const sseMaxReconnectAttempts = 10;
    
    function playNotificationSound() {
        try {
            const audio = new Audio('data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEAQB8AAAB9AAACABAAZGF0YQIAAAAAAA==');
            audio.play().catch(() => {});
        } catch (e) {}
    }

    function connectSSE(convId, isGlobal = false) {
        const url = isGlobal ? '/api/notifications/stream/global' : `/api/notifications/stream/${convId}`;
        
        if (!convId && !isGlobal) {
            return;
        }
        if (sseConnection && sseConnection.url === url && sseConnection.eventSource) {
            return;
        }
        if (sseConnection && sseConnection.eventSource) {
            sseConnection.eventSource.close();
        }
        
        const eventSource = new EventSource(url);
        sseConnection = {
            url: url,
            conversationId: convId,
            eventSource: eventSource,
            isGlobal: isGlobal
        };
        sseReconnectAttempts = 0;
        
        eventSource.addEventListener('connected', () => {});
        
        eventSource.addEventListener('new_message', (e) => {
            const data = JSON.parse(e.data);
            const notificationConvId = data.conversationId;
            const backendUnreadCount = data.unreadCount;
            
            if (isGlobal) {
                const isUserViewingThisConv = isViewingConversation(notificationConvId);
                
                if (!isUserViewingThisConv && backendUnreadCount && backendUnreadCount > 0) {
                    unreadCounts.set(notificationConvId, backendUnreadCount);
                    calculateTotalUnread();
                    saveUnreadCounts();
                    updateBadges();
                    playNotificationSound();
                }
                
                saveConversation(notificationConvId, null, data.messagePreview, data.timestamp);
                renderConversationList();
            } else {
                const isUserViewing = isViewingConversation(notificationConvId);
                
                if (!isUserViewing && backendUnreadCount && backendUnreadCount > 0) {
                    unreadCounts.set(notificationConvId, backendUnreadCount);
                    calculateTotalUnread();
                    saveUnreadCounts();
                    updateBadges();
                    playNotificationSound();
                }
                
                saveConversation(notificationConvId, null, data.messagePreview, data.timestamp);
                renderConversationList();
            }
        });
        
        eventSource.onerror = (e) => {
            eventSource.close();
            
            if (sseReconnectAttempts < sseMaxReconnectAttempts) {
                sseReconnectAttempts++;
                const delay = Math.min(1000 * Math.pow(1.5, sseReconnectAttempts), 10000);
                setTimeout(() => connectSSE(convId, isGlobal), delay);
            }
        };
    }
    
    const disconnectSSE=()=>{if(sseConnection&&sseConnection.eventSource){sseConnection.eventSource.close();sseConnection=null;}};
    function notifyBackendViewingStatus(conversationId, isViewing) {
        if (!conversationId) return;
        fetch('/api/chat/viewing-status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conversationId, isViewing })
        }).catch(() => {});
    }
    function getStoredConversations() {
        const stored = getLS('chat_conversations');
        return stored ? JSON.parse(stored) : [];
    }
    
    function saveConversation(convId, title, lastMessage, timestamp) {
        let conversations = getStoredConversations();
        const existingIndex = conversations.findIndex(c => c.id === convId);
        const existingConv = existingIndex >= 0 ? conversations[existingIndex] : null;
        
        const convData = {
            id: convId,
            title: title || existingConv?.title || 'Conversation',
            lastMessage: lastMessage || '',
            timestamp: timestamp || new Date().toISOString(),
            updatedAt: new Date().toISOString()
        };
        
        if (existingIndex >= 0) {
            conversations[existingIndex] = { ...conversations[existingIndex], ...convData };
        } else {
            conversations.unshift(convData);
        }
        conversations = conversations.slice(0, 50);
        
        setLS('chat_conversations', JSON.stringify(conversations));
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
            const unreadCount = unreadCounts.get(conv.id) || 0;
            const hasUnread = unreadCount > 0;
            const unreadClass = hasUnread ? 'conversation-unread' : '';
            
            return `
                <div class="conversation-item ${unreadClass}" data-conv-id="${conv.id}">
                    <div class="conversation-icon">💬</div>
                    <div class="conversation-details">
                        <div class="conversation-title">${conv.title}</div>
                        <div class="conversation-preview">${preview}</div>
                    </div>
                    <div class="conversation-time">${timeAgo}</div>
                    ${hasUnread ? `<div class="conversation-badge">${unreadCount > 99 ? '99+' : unreadCount}</div>` : ''}
                </div>
            `;
        }).join('');
        conversationList.querySelectorAll('.conversation-item').forEach(item => {
            item.addEventListener('click', () => {
                const convId = item.getAttribute('data-conv-id');
                openExistingConversation(convId);
            });
        });
    }
    
    const getTimeAgo=t=>{if(!t)return'';const d=(new Date()-new Date(t)),m=Math.floor(d/60000),h=Math.floor(d/3600000),dy=Math.floor(d/86400000);return m<1?'Just now':m<60?`${m}m ago`:h<24?`${h}h ago`:dy<7?`${dy}d ago`:new Date(t).toLocaleDateString();};
    
    function showConversationList() {
        if (conversationId) notifyBackendViewingStatus(conversationId, false);
        
        currentView = 'list';
        conversationListView.style.display = 'flex';
        chatView.style.display = 'none';
        backBtn.style.display = 'none';
        chatHeaderTitle.textContent = 'Yatri Bandhu';
        connectSSE(null, true);
        if (conversationId) {
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
        if (conversationId) {
            notifyBackendViewingStatus(conversationId, true);
            clearUnreadCount(conversationId);
            fetch('/api/chat/clear-badge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ conversationId: conversationId })
            }).catch(() => {});
        }
        
        currentView = 'chat';
        conversationListView.style.display = 'none';
        chatView.style.display = 'flex';
        backBtn.style.display = 'block';
        disconnectSSE();
    }
    
    function openExistingConversation(convId) {
        const previousConvId = localStorage.getItem('chat_current_conversation');
        if (previousConvId && previousConvId !== convId) {
            notifyBackendViewingStatus(previousConvId, false);
        }
        
        clearUnreadCount(convId);
        
        fetch('/api/chat/clear-badge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conversationId: convId })
        }).catch(() => {});
        
        conversationId = convId;
        localStorage.setItem('chat_current_conversation', convId);
        const storedAppUserId = localStorage.getItem(`chat_appUserId_${convId}`);
        if (storedAppUserId) {
            appUserId = storedAppUserId;
        } else {
            const genericUserId = localStorage.getItem('chat_user_id');
            if (genericUserId) {
                appUserId = genericUserId;
                localStorage.setItem(`chat_appUserId_${convId}`, genericUserId);
            } else {
                appUserId = null;
            }
        }
        displayedMessageIds.clear();
        displayedImageFileNames.clear();
        lastMessageDate = null; // Reset daily separator for new conversation
        const convState = localStorage.getItem(`chat_conv_state_${convId}`);
        let restoredAgentName = 'Agent';
        if (convState) {
            try {
                const state = JSON.parse(convState);
                isAgentConnected = state.isAgentConnected || false;
                agentJoinAnnounced = state.agentJoinAnnounced || false;
                restoredAgentName = state.agentName || 'Agent';
            } catch (e) {
                isAgentConnected = false;
                agentJoinAnnounced = false;
            }
        } else {
            isAgentConnected = false;
            agentJoinAnnounced = false;
        }
        messagesContainer.innerHTML = '';
        showChatView();
        if (isAgentConnected) {
            chatInputArea.style.display = 'flex';
            chatHeaderTitle.textContent = restoredAgentName;
            localStorage.setItem('chat_agentName', restoredAgentName);
        } else {
            chatInputArea.style.display = 'none';
            chatHeaderTitle.textContent = 'Yatri Bandhu';
        }
        if (sunshineSocket) {
            sunshineSocket.disconnect();
            sunshineSocket = null;
        }
        sunshineSocket = new SunshineWebSocketManager(conversationId);
        sunshineSocket.connect();
        if (!appUserId) {
            fetchConversationDetails(convId).then(() => {
                fetchMessages();
            });
        } else {
            fetchMessages();
        }
    }
    
    function fetchConversationDetails(convId) {
        return new Promise((resolve, reject) => {
            fetch(`/api/chat/get-messages?conversationId=${convId}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    if (data.conversation && data.conversation.participants) {
                        const userParticipant = data.conversation.participants.find(
                            p => p.userExternalId || p.userId
                        );
                        if (userParticipant) {
                            appUserId = userParticipant.userId || userParticipant.userExternalId;
                            localStorage.setItem(`chat_appUserId_${convId}`, appUserId);
                            localStorage.setItem('chat_user_id', appUserId);
                            resolve();
                            return;
                        }
                    }
                    resolve(); // Still resolve to continue
                })
                .catch(error => {
                    resolve(); // Don't reject, allow flow to continue
                });
        });
    }
    
    function startNewConversation() {
        conversationId = null;
        appUserId = null;
        displayedMessageIds.clear();
        displayedImageFileNames.clear();
        surveyMessageShown = false; // Reset survey flag
        lastMessageDate = null; // Reset daily separator tracking
        isAgentConnected = false;
        agentJoinAnnounced = false;
        sessionEnded = false;
        lastContext = "General Inquiry";
        window.lastAppRelatedCategory = null;
        localStorage.removeItem('chat_current_conversation');
        localStorage.removeItem('chat_isAgentConnected');
        localStorage.removeItem('chat_agentJoinAnnounced');
        localStorage.removeItem('chat_agentName');
        if (sunshineSocket) {
            sunshineSocket.disconnect();
            sunshineSocket = null;
        }
        messagesContainer.innerHTML = '';
        showChatView();
        chatInputArea.style.display = 'none';
        chatHeaderTitle.textContent = 'Yatri Bandhu';
        appendMessage("Hello! 👋 How can I help you today?", 'bot-message');
        showMainOptions();
    }
    
    function createConversationAndEscalate(reason, category) {
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
                    localStorage.setItem(`chat_appUserId_${conversationId}`, appUserId);

                    localStorage.setItem('chat_current_conversation', conversationId);
                    saveConversation(conversationId, category || 'Support Request', '', new Date().toISOString());
                    sunshineSocket = new SunshineWebSocketManager(conversationId);
                    sunshineSocket.connect();
                    performEscalation(reason, category);

                } else {
                    appendMessage("Failed to connect. Please try again.", 'system-message');
                }
            })
            .catch(error => {
                appendMessage("Connection error. Please try again.", 'system-message');
            });
    }
    
    function performEscalation(reason, category) {
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
                isAgentConnected = true;
                agentJoinAnnounced = false;
                localStorage.setItem('chat_isAgentConnected', 'true');
                localStorage.setItem('chat_agentJoinAnnounced', 'false');
                showLoadingIndicator();
                chatInputArea.style.display = 'flex';
                chatInput.focus();
            })
            .catch(error => {
                appendMessage("Error connecting to agent. Please try again.", 'system-message');
            });
    }
    class SunshineWebSocketManager {
        constructor(conversationId) {
            this.conversationId = conversationId;
            this.socket = null;
            this.connected = false;
            this.reconnectAttempts = 0;
            this.maxReconnectAttempts = 10;
            this.pingInterval = null;
        }

        connect() {
            if (!this.conversationId) {
                return;
            }
            if (this.socket) {
                this.disconnect();
            }
            const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
            const wsUrl = `${wsProtocol}://${window.location.host}/ws/chat/${this.conversationId}/`;
            this.socket = new WebSocket(wsUrl);

            this.socket.onopen = () => {
                this.connected = true;
                this.reconnectAttempts = 0;
                this.startPingInterval();
                this.send({
                    type: 'echo',
                    message: 'WebSocket connected',
                    timestamp: Date.now()
                });
            };

            this.socket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleIncomingMessage(data);

                } catch (error) {
                }
            };

            this.socket.onerror = (error) => {
            };

            this.socket.onclose = (event) => {
                this.connected = false;
                if (this.pingInterval) {
                    clearInterval(this.pingInterval);
                    this.pingInterval = null;
                }
                if (!sessionEnded && event.code !== 1000) {
                    this.reconnect();
                }
            };
        }

        startPingInterval() {
            if (this.pingInterval) {
                clearInterval(this.pingInterval);
            }
            this.pingInterval = setInterval(() => {
                if (this.socket && this.socket.readyState === WebSocket.OPEN) {
                    this.send({
                        type: 'ping',
                        timestamp: Date.now()
                    });
                }
            }, 25000);
        }

        send(data) {
            if (this.socket && this.socket.readyState === WebSocket.OPEN) {
                try {
                    this.socket.send(JSON.stringify(data));
                    return true;
                } catch (error) {
                    return false;
                }
            }
            return false;
        }

        handleIncomingMessage(data) {
            if (data.type === 'connection_established') {
                return;
            }
            if (data.type === 'pong') {
                return;
            }
            if (data.type === 'echo_response') {
                return;
            }
            if (data.type === 'keepalive') {
                return;
            }
            if (data.type === 'agent_message') {
                this.processAgentMessage(data.payload || data);
                return;
            }
            if (data.type === 'error') {
                return;
            }
        }

        processAgentMessage(message) {
            const isAgent = message.author && (
                message.author.type === 'business' ||
                message.author.type === 'agent' ||
                message.source === 'zendesk' ||
                message.author.role === 'agent'
            );

            if (!isAgent) {
                return;
            }
            const text = message.content?.text || message.text || '';
            const messageId = message.id || `agent_${Date.now()}`;
            const agentName = message.author?.displayName || 'Agent';
            const msgConversationId = message.conversationId || this.conversationId;
            // Use only Zendesk timestamps - primary: message.timestamp, secondary: message.received
            // NO FALLBACK - messages without Zendesk timestamps won't be displayed
            const timestamp = message.timestamp || message.received;
            const choices = message.choices || [];
            const actions = message.actions || [];
            
            if (choices.length > 0) {
            }
            if (actions.length > 0) {
            }
            if (displayedMessageIds.has(messageId)) {
                return;
            }
            const isUserViewingThisConv = msgConversationId === conversationId && isChatOpen && currentView === 'chat';
            
            if (msgConversationId && isUserViewingThisConv) {
                clearUnreadCount(msgConversationId);
                fetch('/api/chat/clear-badge', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ conversationId: msgConversationId })
                }).catch(() => {});
                saveConversation(msgConversationId, null, text.substring(0, 50), new Date().toISOString());
            } else if (msgConversationId && !isUserViewingThisConv && agentJoinAnnounced) {
                saveConversation(msgConversationId, null, text.substring(0, 50), new Date().toISOString());
            }
            if (msgConversationId !== conversationId) {
                return;
            }
            if (!agentJoinAnnounced) {
                removeLoadingIndicator();
                appendMessage(`${agentName} will help you now.`, 'system-message');
                agentJoinAnnounced = true;
                localStorage.setItem('chat_agentJoinAnnounced', 'true');
                localStorage.setItem('chat_agentName', agentName);
                chatInputArea.style.display = 'flex';
                chatHeaderTitle.textContent = agentName;
                ensureScrollToBottom();
            }
            displayedMessageIds.add(messageId);
            // Don't display text message if it has choices/actions - let appendChoicesMessage handle the full message with question + buttons
            if (choices.length > 0 || actions.length > 0) {
                chatInputArea.style.display = 'none';
                appendMessage('Messaging session ended', 'agent-announcement');
                // Pass the message object with text to appendChoicesMessage
                appendChoicesMessage(choices.length > 0 ? choices : actions, 'bot-message', { text: text, choices: choices.length > 0 ? choices : actions });
            } else {
                // Use the Zendesk-provided 'received' timestamp directly
                appendMessage(text, 'bot-message', timestamp);
            }
            ensureScrollToBottom();
            showMessageReceivedIndicator();
        }

        reconnect() {
            if (this.reconnectAttempts >= this.maxReconnectAttempts || sessionEnded) {
                return;
            }

            this.reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), 10000);

            setTimeout(() => {
                this.connect();
            }, delay);
        }

        disconnect() {
            if (this.pingInterval) {
                clearInterval(this.pingInterval);
                this.pingInterval = null;
            }

            if (this.socket) {
                this.socket.close(1000, 'User disconnected');
                this.socket = null;
            }

            this.connected = false;
        }
        testConnection() {
            if (!this.connected) {
                return false;
            }
            const testResult = this.send({
                type: 'test_agent_message',
                message: 'Test message from debug function',
                timestamp: Date.now()
            });
            return testResult;
        }

        isConnected() {
            return this.connected;
        }
    }

    function fetchMessages() {
        if (!conversationId) {
            return;
        }

        fetch(`/api/chat/full-history?conversationId=${conversationId}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.appUserId && !appUserId) {
                    appUserId = data.appUserId;
                    localStorage.setItem(`chat_appUserId_${conversationId}`, appUserId);
                }
                if (data.ticket_id) {
                    if (!isAgentConnected) {
                        isAgentConnected = true;
                        localStorage.setItem('chat_isAgentConnected', 'true');
                        chatInputArea.style.display = 'flex';
                    }
                }

                if (!data.messages || data.messages.length === 0) {
                    return;
                }

                const sortedMessages = data.messages.sort(
                    (a, b) => new Date(a.received) - new Date(b.received)
                );
                let hasNewMessages = false;

                sortedMessages.forEach((msg, index) => {
                    if (!msg || !msg.id) return;
                    if (displayedMessageIds.has(msg.id)) {
                        return;
                    }

                    displayedMessageIds.add(msg.id);
                    hasNewMessages = true;
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
                    if (isAgent && !agentJoinAnnounced && authorName) {
                        removeLoadingIndicator();
                        appendMessage(`${authorName} joined the chat`, 'system-message');
                        agentJoinAnnounced = true;
                        localStorage.setItem('chat_agentJoinAnnounced', 'true');
                        localStorage.setItem('chat_agentName', authorName);
                        chatInputArea.style.display = 'flex';
                        chatHeaderTitle.textContent = authorName;
                    }
                    if (msg.attachments && msg.attachments.length > 0) {
                        msg.attachments.forEach(att => {
                            if (att.type === 'image' && att.url) {
                                const fileName = att.url.split('/').pop() || 'image';
                                if (!displayedImageFileNames.has(fileName)) {
                                    displayedImageFileNames.add(fileName);
                                    // Pass message received timestamp for correct date separator
                                    appendImageMessage(att.url, msg.text || '', cssClass, msg.received);
                                }
                            } else if (att.type === 'file' && att.url) {
                                // Pass message received timestamp for correct date separator
                                appendFileMessage(
                                    att.fileName || 'file',
                                    formatFileSize(att.size || 0),
                                    cssClass,
                                    msg.text || '',
                                    msg.received
                                );
                            }
                        });
                        if (msg.text && msg.attachments.some(a => a.type === 'image')) {
                            return;
                        }
                    }
                    if (msg.text) {
                        if (msg.text.includes('Connecting to agent') || 
                            msg.text.includes('Escalation Reason:')) {
                            return;
                        }
                        // Skip displaying text message if it has choices/actions - they will be shown with the message
                        if (!msg.choices?.length && !msg.actions?.length) {
                            const hasWebviewChoice = msg.choices?.some(c => c.type === 'webview' && c.uri) ||
                                                    msg.actions?.some(a => a.type === 'webview' && a.uri);
                            if (!hasWebviewChoice) {
                                // Pass the message's received timestamp for proper daily separator
                                appendMessage(msg.text, cssClass, msg.received);
                            }
                        }
                    }
                    if (msg.choices && msg.choices.length > 0) {
                        // Show session ended first, then CSAT bubble with question + buttons
                        chatInputArea.style.display = 'none';
                        appendMessage('Messaging session ended', 'agent-announcement');
                        appendChoicesMessage(msg.choices, cssClass, msg);
                    } else if (msg.actions && msg.actions.length > 0) {
                        // Show session ended first, then actions bubble with question + buttons
                        chatInputArea.style.display = 'none';
                        appendMessage('Messaging session ended', 'agent-announcement');
                        appendChoicesMessage(msg.actions, cssClass, msg);
                    }
                });

                if (hasNewMessages) {
                    ensureScrollToBottom();
                }
                if (sortedMessages.length > 0 && isAgentConnected) {
                    const lastMsg = sortedMessages[sortedMessages.length - 1];
                    if (lastMsg.text) {
                        const text = lastMsg.text.toLowerCase();
                        const isEndSession = text.includes("messaging session ended") ||
                            text.includes("the agent has ended the session");
                        
                        if (isEndSession) {
                            endSession();
                        }
                    }
                }
            })
            .catch(error => {
            });
    }

    function endSession() {
        isAgentConnected = false;
        agentJoinAnnounced = false;
        sessionEnded = true;

        if (sunshineSocket) {
            sunshineSocket.disconnect();
        }

        localStorage.removeItem('chat_isAgentConnected');
        localStorage.removeItem('chat_agentJoinAnnounced');

        chatInputArea.style.display = 'none';
        chatHeaderTitle.textContent = "Yatri Bandhu";
        appendMessage("What can I help you with?", 'bot-message');
        showMainOptions();
    }

    function handleAgentConnect(option) {
        appendMessage(option, 'user-message');
        if (!conversationId) {
            createConversationAndEscalate(lastContext, window.lastAppRelatedCategory);
        } else {
            performEscalation(lastContext, window.lastAppRelatedCategory);
        }
    }

    function showMessageReceivedIndicator() {
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
            setTimeout(() => {
                indicator.remove();
            }, 1000);
        }
    }

    function sendToSunshine(text) {
        if (!appUserId || !conversationId) {
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
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                saveConversation(conversationId, null, text, new Date().toISOString());
                renderConversationList();
                
                if (data.data?.messages?.length > 0) {
                    const msgId = data.data.messages[0].id;
                    displayedMessageIds.add(msgId);
                }
            });
    }

    function toggleChat() {
        isChatOpen = !isChatOpen;
        if (isChatOpen) {
            chatBox.style.display = 'flex';
            toggleBtn.innerHTML = '✖';
            toggleBtn.setAttribute('aria-label', 'Close chat');
            const activeConvId = localStorage.getItem('chat_current_conversation');
            const wasInChat = currentView === 'chat' && conversationId;
            
            if (activeConvId && wasInChat && messagesContainer.children.length > 0) {
                showChatView();
                if (!sunshineSocket || !sunshineSocket.socket?.readyState === WebSocket.OPEN) {
                    sunshineSocket = new SunshineWebSocketManager(conversationId);
                    sunshineSocket.connect();
                }
                fetchMessages();
            } else {
                showConversationList();
            }
        } else {
            chatBox.style.display = 'none';
            toggleBtn.innerHTML = '💬';
            toggleBtn.setAttribute('aria-label', 'Open chat');
            if (sunshineSocket) {
                sunshineSocket.disconnect();
            }
            disconnectSSE();
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
        window.lastAppRelatedCategory = option;  // NEW: Store category

        if (option === "Others") {
            appendMessage("Please describe your issue below.", 'bot-message');
            chatInputArea.style.display = 'flex';
            chatInput.focus();
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
        loaderDiv.style.flexDirection = 'row';
        loaderDiv.style.alignItems = 'center';
        loaderDiv.style.justifyContent = 'center';
        loaderDiv.style.gap = '6px';

        const textSpan = document.createElement('span');
        textSpan.textContent = 'Please hang on';
        loaderDiv.appendChild(textSpan);

        const dotsDiv = document.createElement('div');
        dotsDiv.className = 'typing-indicator-inline';
        dotsDiv.innerHTML = `
            <div class="typing-dot-small"></div>
            <div class="typing-dot-small"></div>
            <div class="typing-dot-small"></div>
        `;
        loaderDiv.appendChild(dotsDiv);
        messagesContainer.appendChild(loaderDiv);
        ensureScrollToBottom();
    }

    const removeLoadingIndicator=()=>{const l=document.getElementById('agent-loading-indicator');if(l)l.remove();};

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
        
        // If no conversation yet, initialize one before sending
        if (!conversationId) {
            showLoadingIndicator();
            const storedUserId = localStorage.getItem('chat_user_id');
            const payload = {
                userId: storedUserId || null,
                forceNew: false
            };

            fetch('/api/chat/init', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
                .then(response => {
                    if (!response.ok) {
                        return response.text().then(text => {
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
                        localStorage.setItem(`chat_appUserId_${conversationId}`, appUserId);
                        localStorage.setItem('chat_current_conversation', conversationId);
                        
                        // Save conversation and setup WebSocket
                        saveConversation(conversationId, lastContext || 'Support Request', '', new Date().toISOString());
                        sunshineSocket = new SunshineWebSocketManager(conversationId);
                        sunshineSocket.connect();
                        
                        removeLoadingIndicator();
                        // Now send the message
                        appendMessage(messageText, 'user-message');
                        saveConversation(conversationId, null, messageText, new Date().toISOString());
                        sendToSunshine(messageText);
                        chatInput.value = '';

                        if (!isAgentConnected) {
                            chatInputArea.style.display = 'none';
                            setTimeout(() => {
                                appendMessage("Your issue has been forwarded to our support team. An agent will review it shortly.", 'bot-message');
                            }, 1500);
                        }
                    } else {
                        removeLoadingIndicator();
                        appendMessage("Failed to initialize chat. Please try again.", 'system-message');
                    }
                })
                .catch(error => {
                    removeLoadingIndicator();
                    appendMessage("Connection error. Please try again.", 'system-message');
                });
            return;
        }
        
        if (!appUserId) {
            const storedUserId = localStorage.getItem(`chat_appUserId_${conversationId}`) 
                              || localStorage.getItem('chat_user_id');
            if (storedUserId) {
                appUserId = storedUserId;
            } else {
                appendMessage("Error: Chat not initialized. Please refresh and try again.", 'system-message');
                return;
            }
        }
        
        appendMessage(messageText, 'user-message');
        
        saveConversation(conversationId, null, messageText, new Date().toISOString());
        sendToSunshine(messageText);
        chatInput.value = '';

        if (!isAgentConnected) {
            chatInputArea.style.display = 'none';
            setTimeout(() => {
                appendMessage("Your issue has been forwarded to our support team. An agent will review it shortly.", 'bot-message');
            }, 1500);
        }
    }

    // Check if day changed for new timestamp separator
    function shouldAddDaySeparator(messageDate) {
        if (!lastMessageDate) return true; // Always show first separator
        const lastDay = lastMessageDate.toDateString();
        const currentDay = messageDate.toDateString();
        return lastDay !== currentDay; // Show separator only if day changed
    }
    
    // Add daily timestamp separator to messages
    function appendDaySeparator(date) {
        const separatorDiv = document.createElement('div');
        separatorDiv.classList.add('message', 'day-separator');
        separatorDiv.style.textAlign = 'center';
        
        const separatorText = document.createElement('span');
        const options = { month: 'long', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true };
        const formattedDate = date.toLocaleString('en-US', options);
        
        separatorText.textContent = formattedDate;
        separatorText.style.padding = '4px 12px';
        separatorText.style.borderRadius = '12px';
        separatorText.style.fontSize = '0.85rem';
        separatorText.style.color = 'rgba(0, 0, 0, 0.5)';
        separatorText.style.fontWeight = '500';
        separatorText.style.display = 'inline-block';
        
        separatorDiv.appendChild(separatorText);
        messagesContainer.appendChild(separatorDiv);
    }

    const appendMessage=(t,c,timestamp)=>{
        const d=document.createElement('div');
        d.classList.add('message',c);
        d.style.whiteSpace="pre-wrap";
        
        // Parse the message timestamp from Zendesk/Sunshine
        let messageDate = null;
        if (timestamp) {
            try {
                messageDate = new Date(timestamp);
                // Validate the date is valid
                if (isNaN(messageDate.getTime())) {
                    messageDate = null;
                }
            } catch (e) {
                messageDate = null;
            }
        }
        
        // Only show daily separator if we have a valid Zendesk timestamp
        if (messageDate && shouldAddDaySeparator(messageDate)) {
            appendDaySeparator(messageDate);
        }
        if (messageDate) {
            lastMessageDate = messageDate;
        }
        
        // Create message content wrapper
        const contentDiv = document.createElement('div');
        contentDiv.classList.add('message-content');
        contentDiv.textContent = t;
        d.appendChild(contentDiv);
        
        messagesContainer.appendChild(d);
        ensureScrollToBottom();
    };

    function appendImageMessage(imageUrl, caption, className, messageDate = null) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', className, 'image-bubble');

        // Parse message date from Zendesk timestamp - validate it's a valid date
        let parsedDate = null;
        if (messageDate) {
            try {
                parsedDate = new Date(messageDate);
                if (isNaN(parsedDate.getTime())) {
                    parsedDate = null;
                }
            } catch (e) {
                parsedDate = null;
            }
        }
        
        // Only show daily separator if we have a valid Zendesk timestamp
        if (parsedDate && shouldAddDaySeparator(parsedDate)) {
            appendDaySeparator(parsedDate);
        }
        if (parsedDate) {
            lastMessageDate = parsedDate;
        }

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

    function appendFileMessage(fileName, fileSize, className, caption = '', messageDate = null) {
        const bubble = document.createElement('div');
        bubble.classList.add('message', className, 'file-bubble');

        // Parse message date from Zendesk timestamp - validate it's a valid date
        let parsedDate = null;
        if (messageDate) {
            try {
                parsedDate = new Date(messageDate);
                if (isNaN(parsedDate.getTime())) {
                    parsedDate = null;
                }
            } catch (e) {
                parsedDate = null;
            }
        }
        
        // Only show daily separator if we have a valid Zendesk timestamp
        if (parsedDate && shouldAddDaySeparator(parsedDate)) {
            appendDaySeparator(parsedDate);
        }
        if (parsedDate) {
            lastMessageDate = parsedDate;
        }

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
        setTimeout(() => scrollToBottom(), 50);
    }
    function appendChoicesMessage(choices, className, msg) {
        // Create outer bubble to contain message + choices + survey
        const messageBubble = document.createElement('div');
        messageBubble.classList.add('message', className, 'combined-message-bubble');
        messageBubble.id = `bubble_${Date.now()}`;
        
        // Add message text if present
        if (msg && msg.text) {
            const textDiv = document.createElement('div');
            textDiv.classList.add('message-text-content');
            textDiv.style.whiteSpace = 'pre-wrap';
            textDiv.textContent = msg.text;
            messageBubble.appendChild(textDiv);
        }
        
        // Create choices container inside the bubble
        const choicesDiv = document.createElement('div');
        choicesDiv.classList.add('choices-container', 'inline-choices');
        choicesDiv.id = `choices_${Date.now()}`;
        
        let emojiCount = 0;
        let hasWebview = false;

        choices.forEach((choice) => {
            const choiceObj = typeof choice === 'string' ? { text: choice } : choice;
            const choiceEmoji = choiceObj.emoji || choiceObj.icon || '';
            const choiceType = choiceObj.type || '';

            if (choiceType === 'webview') {
                hasWebview = true;
            }

            if (choiceEmoji) {
                emojiCount++;
            }
        });

        if (emojiCount > 0 && emojiCount >= choices.length * 0.5) {
            choicesDiv.classList.add('emoji-layout');
        }
        if (hasWebview) {
            choicesDiv.classList.add('webview-layout');
        }
        
        // Store reference to bubble for survey injection
        choicesDiv.dataset.bubbleId = messageBubble.id;

        choices.forEach((choice, index) => {
            const choiceObj = typeof choice === 'string' ? { text: choice } : choice;

            const choiceText = choiceObj.text || choiceObj.label || choiceObj.value || '';
            const choiceValue = choiceObj.value || choiceObj.text || choiceObj.label || index.toString();
            const choiceEmoji = choiceObj.emoji || choiceObj.icon || '';
            const choiceUri = choiceObj.uri || choiceObj.fallback || '';
            const choiceType = choiceObj.type || '';

            const btn = document.createElement('button');
            btn.classList.add('choice-btn');

            // Check if this choice was already clicked in localStorage
            const surveyKey = `survey_clicked_${conversationId}`;
            const surveyUriKey = `survey_uri_${conversationId}`;
            const surveyTitleKey = `survey_title_${conversationId}`;
            const clickedChoice = localStorage.getItem(surveyKey);
            const isAlreadyClicked = clickedChoice === choiceValue || clickedChoice === choiceText;

            if (isAlreadyClicked) {
                btn.disabled = true;
                btn.style.opacity = '0.5';
                btn.classList.add('selected');
                
                // Auto-open survey if it's a webview and we have stored URI
                if (choiceType === 'webview' && choiceUri) {
                    setTimeout(() => {
                        appendWebviewSurvey(choiceUri, choiceText, messageBubble);
                    }, 300);
                }
            }

            if (choiceType === 'webview' && choiceUri) {
                btn.textContent = choiceText || 'Open Survey';
                btn.classList.add('webview-btn');

                btn.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    if (btn.dataset.clicked === 'true' || btn.disabled) {
                        return;
                    }
                    btn.dataset.clicked = 'true';
                    btn.disabled = true;
                    btn.style.opacity = '0.5';
                    btn.classList.add('selected');
                    localStorage.setItem(surveyKey, choiceValue || choiceText);
                    // Pass bubble ID so survey is added to same bubble
                    appendWebviewSurvey(choiceUri, choiceText, messageBubble);
                    choicesDiv.querySelectorAll('.choice-btn').forEach(b => {
                        b.disabled = true;
                        b.style.opacity = '0.5';
                    });
                });
            }
            else if (choiceEmoji) {
                btn.textContent = choiceEmoji;
                btn.title = choiceText;
                btn.classList.add('emoji-choice');

                btn.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    if (btn.dataset.clicked === 'true' || btn.disabled) {
                        return;
                    }
                    btn.dataset.clicked = 'true';
                    btn.disabled = true;
                    localStorage.setItem(surveyKey, choiceValue);
                    appendMessage(choiceEmoji, 'user-message');
                    choicesDiv.querySelectorAll('.choice-btn').forEach(b => {
                        b.disabled = true;
                        b.style.opacity = '0.5';
                    });
                    sendToSunshine(choiceValue);
                    btn.classList.add('selected');
                });
            }
            else {
                btn.textContent = choiceText;

                btn.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    if (btn.dataset.clicked === 'true' || btn.disabled) {
                        return;
                    }
                    btn.dataset.clicked = 'true';
                    btn.disabled = true;
                    localStorage.setItem(surveyKey, choiceValue);
                    appendMessage(choiceValue, 'user-message');
                    choicesDiv.querySelectorAll('.choice-btn').forEach(b => {
                        b.disabled = true;
                        b.style.opacity = '0.5';
                    });
                    sendToSunshine(choiceValue);
                    btn.classList.add('selected');
                });
            }

            choicesDiv.appendChild(btn);
        });

        // Add choices to message bubble
        messageBubble.appendChild(choicesDiv);
        // Add the entire bubble to messages container
        messagesContainer.appendChild(messageBubble);
        ensureScrollToBottom();
    }
    function appendWebviewSurvey(surveyUri, surveyTitle, parentBubble) {
        // If parent bubble provided, append survey inside it; otherwise create new bubble
        const targetContainer = parentBubble || document.createElement('div');
        if (!parentBubble) {
            targetContainer.classList.add('message', 'survey-bubble');
        }
        
        const surveyContainer = document.createElement('div');
        surveyContainer.classList.add('survey-iframe-wrapper');
        const iframeWrapper = document.createElement('div');
        iframeWrapper.classList.add('survey-iframe-wrapper');
        const loadingDiv = document.createElement('div');
        loadingDiv.classList.add('survey-loading');
        loadingDiv.textContent = 'Loading survey...';
        iframeWrapper.appendChild(loadingDiv);
        const iframe = document.createElement('iframe');
        iframe.classList.add('survey-iframe');
        iframe.src = surveyUri;
        iframe.title = surveyTitle || 'Survey';
        iframe.allow = 'geolocation; microphone; camera; payment; usb; magnetometer; gyroscope; accelerometer';
        iframe.style.width = '100%';
        iframe.style.height = '600px';
        iframe.style.border = 'none';
        iframe.style.borderRadius = '0 0 8px 8px';
        iframe.style.display = 'block';
        iframeWrapper.appendChild(iframe);
        
        surveyContainer.appendChild(iframeWrapper);
        targetContainer.appendChild(surveyContainer);
        
        // Only append to messagesContainer if this is a standalone bubble
        if (!parentBubble) {
            messagesContainer.appendChild(targetContainer);
        }
        
        setTimeout(() => {
            if (loadingDiv && loadingDiv.parentElement) {
                loadingDiv.style.display = 'none';
            }
            iframe.style.display = 'block';
            ensureScrollToBottom();
        }, 500);
        iframe.addEventListener('load', function () {
            if (loadingDiv && loadingDiv.parentElement) {
                loadingDiv.style.display = 'none';
            }
            iframe.style.display = 'block';
            ensureScrollToBottom();
        });

        iframe.addEventListener('error', function () {
            loadingDiv.textContent = 'Survey could not be loaded. Please try again.';
            loadingDiv.style.color = '#dc3545';
            iframe.style.display = 'none';
        });
    }

    const scrollToBottom=()=>messagesContainer&&requestAnimationFrame(()=>{messagesContainer.scrollTop=messagesContainer.scrollHeight;});
    const ensureScrollToBottom=()=>{scrollToBottom();setTimeout(scrollToBottom,100);setTimeout(scrollToBottom,300);};

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

    const formatFileSize=b=>{if(b===0)return'0 Bytes';const k=1024,s=['Bytes','KB','MB','GB'],i=Math.floor(Math.log(b)/Math.log(k));return parseFloat((b/Math.pow(k,i)).toFixed(2))+' '+s[i];};

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
            if (conversationId && !appUserId) {
                const storedUserId = localStorage.getItem(`chat_appUserId_${conversationId}`) 
                                  || localStorage.getItem('chat_user_id');
                if (storedUserId) {
                    appUserId = storedUserId;
                } else {
                    appendMessage("Error: Chat not initialized. Please refresh and try again.", 'system-message');
                    return;
                }
            } else {
                appendMessage("Error: Chat not initialized. Please refresh and try again.", 'system-message');
                return;
            }
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
            ensureScrollToBottom();
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
                    if (progressContainer) {
                        statusText.textContent = 'Error processing response';
                        progressFill.style.backgroundColor = '#dc3545';
                    }
                }
            } else {
                if (progressContainer) {
                    statusText.textContent = 'Error sending document';
                    progressFill.style.backgroundColor = '#dc3545';
                }
                appendMessage("Failed to send file. Please try again.", 'system-message');
            }
        });

        xhr.addEventListener('error', function () {
            if (progressContainer) {
                statusText.textContent = 'Network error - please try again';
                progressFill.style.backgroundColor = '#dc3545';
            }
            appendMessage("Network error. Please check your connection.", 'system-message');
        });

        xhr.addEventListener('abort', function () {
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
            if (e.key === 'Escape') {
                modal.remove();
            }
        });

        document.body.appendChild(modal);
    }

    const clearImagePreview=()=>{const p=document.getElementById('image-preview-container');if(p)p.remove();pendingImage=null;chatInput.placeholder='Type a message...';};

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
        function validateDeleteButton() {
            if (selectedReason === "Others") {
                const hasText = otherInput.value.trim() !== "";
                deleteBtn.disabled = !hasText;
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
                const otherText = otherInput.value.trim();
                reasonText += ": " + otherText;
            }
            sendToSunshine("Delete Account Request: " + reasonText);

            modal.remove();
            appendMessage("Delete Account Request", 'user-message');

            setTimeout(() => {
                appendMessage("Your request has been submitted. Our team will contact you shortly.", 'bot-message');
            }, 500);
        });
    }

    toggleBtn.addEventListener('click', toggleChat);
    closeBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        toggleChat();
    });
    newConversationBtn.addEventListener('click', function () {
        startNewConversation();
    });
    backBtn.addEventListener('click', function () {
        if (conversationId) {
            clearUnreadCount(conversationId);
        }
        if (conversationId) {
            const agentName = localStorage.getItem('chat_agentName') || 'Agent';
            const convState = {
                isAgentConnected: isAgentConnected,
                agentJoinAnnounced: agentJoinAnnounced,
                agentName: agentName
            };
            localStorage.setItem(`chat_conv_state_${conversationId}`, JSON.stringify(convState));
        }
        if (sunshineSocket) {
            sunshineSocket.disconnect();
        }
        
        showConversationList();
    });

    fileAttachBtn.addEventListener('click', function () {
        fileInput.click();
    });

    fileInput.addEventListener('change', function (e) {
        const file = e.target.files[0];
        if (file) {
            showDocumentPreviewModal(file);
        }
    });

    sendBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') sendMessage();
    });
    const issuesUrl = window.issuesUrl || 'static/js/issues.json';
    fetch(issuesUrl)
        .then(response => response.json())
        .then(data => {
            troubleshootingSteps = data.troubleshooting;
            mainOptions = data.mainOptions;
            appRelatedOptions = data.appRelatedOptions;
            deleteAccountReasons = data.deleteAccountReasons;
        });
    const lastConversationId = localStorage.getItem('chat_current_conversation');

    if (lastConversationId) {
        const conversations = getStoredConversations();
        const lastConv = conversations.find(c => c.id === lastConversationId);
        
        if (lastConv) {
            conversationId = lastConversationId;
            const storedUserId = localStorage.getItem(`chat_appUserId_${lastConversationId}`) 
                              || localStorage.getItem('chat_user_id');
            if (storedUserId) {
                appUserId = storedUserId;
            }
        } else {
            localStorage.removeItem('chat_current_conversation');
        }
    } else {
    }
    showConversationList();
    initNotificationSystem();
});