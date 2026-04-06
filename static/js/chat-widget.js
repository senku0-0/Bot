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
    const FORCE_NEW_CONVERSATION_KEY = 'chat_force_new_conversation';
    let shouldForceNewConversation = localStorage.getItem(FORCE_NEW_CONVERSATION_KEY) === 'true';
    const DEFAULT_TROUBLESHOOTING_STEPS = {
        "Location Not Found or Inaccurate": "There could be multiple reasons why the location is inaccurate. Please try the following:\n\nCheck location settings: Ensure GPS / Location is turned ON.\n\nEnable app permissions: Go to Settings -> Apps -> Namma Yatri -> Permissions -> Location and make sure it is set to Allow all the time or While using the app.\n\nTurn location off and on: Switch off GPS, wait a few seconds, then turn it back on.\n\nCheck for app and OS updates: Update the Namma Yatri app and your phone's operating system to the latest version.\n\nRestart your device: A restart helps refresh location services.",
        "Unable to Login": "There could be multiple reasons why you are unable to log in. Please try the following:\n\nCheck internet connection: Ensure you have a stable Wi-Fi or mobile data connection.\n\nClear cache and data: Go to your device settings, clear the app cache and data, and try logging in again.\n\nCheck for app updates: Make sure you are using the latest version of the app and update it if needed.",
        "My App is Not Responding": "There could be multiple reasons why the app is not responding. Please try the following:\n\nCheck internet connection: Ensure that you have a stable Wi-Fi or mobile data connection.\n\nRestart the app: Close the app completely and restart it.\n\nClear cache: Go to your phone settings, find the Namma Yatri app, and clear its cache.\n\nUpdate the app: Check the app store for available updates and install the latest version.\n\nReboot the device: Restart your device to refresh all system processes."
    };
    let troubleshootingSteps = { ...DEFAULT_TROUBLESHOOTING_STEPS };
    let mainOptions = [];
    let appRelatedOptions = [];
    let rideRelatedOptions = [];
    let farePaymentOptions = [];
    let paymentModes = [];
    let cancellationChargeOptions = [];
    let cancellationWaiverOptions = [];
    let cancellationWaiverApprovedReasons = [];
    let vehicleRelatedOptions = [];
    let vehicleUnsafeCategories = [];
    let safetyRelatedOptions = [];
    // Delete Account flow disabled.
    let deleteAccountReasons = [];
    let flowCopy = {};
    let surveyMessageShown = false;
    let lastMessageDate = null;
    let flowState = createEmptyFlowState();
    let unreadCounts = new Map(); // conversationId -> count
    let totalUnread = 0;

    function createEmptyFlowState() {
        return {
            mainCategory: null,
            category: null,
            subcategory: null,
            detail: null
        };
    }
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
    const CHAT_FLOW_VERSION = 'international-flow-2026-04-06-v12';
    let sseConnection = null;
    let sseReconnectAttempts = 0;
    const sseMaxReconnectAttempts = 10;

    function resetStoredWidgetStateIfNeeded() {
        try {
            const savedVersion = localStorage.getItem('chat_flow_version');
            if (savedVersion === CHAT_FLOW_VERSION) {
                return;
            }

            const keysToRemove = [];
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && (key.startsWith('chat_') || key.startsWith('survey_'))) {
                    keysToRemove.push(key);
                }
            }

            keysToRemove.forEach(key => localStorage.removeItem(key));
            localStorage.setItem('chat_flow_version', CHAT_FLOW_VERSION);
            isAgentConnected = false;
            agentJoinAnnounced = false;
        } catch (e) {}
    }

    resetStoredWidgetStateIfNeeded();

    function setForceNewConversation(value) {
        shouldForceNewConversation = Boolean(value);
        try {
            if (shouldForceNewConversation) {
                localStorage.setItem(FORCE_NEW_CONVERSATION_KEY, 'true');
            } else {
                localStorage.removeItem(FORCE_NEW_CONVERSATION_KEY);
            }
        } catch (e) {}
    }

    function closeActiveModals() {
        chatBox.querySelectorAll('.chat-modal').forEach(modal => modal.remove());
        document.querySelectorAll('.zoom-modal').forEach(modal => modal.remove());
    }
    
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
        closeActiveModals();
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
        closeActiveModals();
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
        setForceNewConversation(false);
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
        closeActiveModals();
        conversationId = null;
        appUserId = null;
        setForceNewConversation(true);
        displayedMessageIds.clear();
        displayedImageFileNames.clear();
        surveyMessageShown = false; // Reset survey flag
        lastMessageDate = null; // Reset daily separator tracking
        isAgentConnected = false;
        agentJoinAnnounced = false;
        sessionEnded = false;
        lastContext = "General Inquiry";
        flowState = createEmptyFlowState();
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
                    setForceNewConversation(false);
                    saveConversation(conversationId, category || 'Support Request', '', new Date().toISOString());
                    if (sunshineSocket) {
                        sunshineSocket.disconnect();
                    }
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
        removeLoadingIndicator();
        showLoadingIndicator();
        
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
            })
            .catch(error => {
                removeLoadingIndicator();
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
        closeActiveModals();
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
        flowState = createEmptyFlowState();
        window.lastAppRelatedCategory = null;
        lastContext = "General Inquiry";
        appendMessage("What can I help you with?", 'bot-message');
        showMainOptions();
    }

    function getFlowCopy(key, fallback = '') {
        return flowCopy[key] || fallback;
    }

    function updateFlowState(updates = {}) {
        flowState = { ...flowState, ...updates };
        const currentPath = getCurrentFlowPath();
        if (currentPath) {
            lastContext = currentPath;
        }
        if (flowState.mainCategory !== "App Related Issues") {
            window.lastAppRelatedCategory = null;
        }
    }

    function getCurrentFlowPath(extraDetail = null) {
        return [
            flowState.mainCategory,
            flowState.category,
            flowState.subcategory,
            flowState.detail,
            extraDetail
        ].filter(Boolean).join(' > ');
    }

    function buildIssueSummary(details = {}) {
        const lines = [];
        const issuePath = getCurrentFlowPath();
        if (issuePath) {
            lines.push(`Issue Path: ${issuePath}`);
        }
        if (details.selection) {
            lines.push(`Selection: ${details.selection}`);
        }
        if (details.comments) {
            lines.push(`Comments: ${details.comments}`);
        }
        if (details.files && details.files.length > 0) {
            lines.push(`Attachments: ${details.files.length} file(s)`);
        }
        return lines.join('\n');
    }

    function ensureConversationInitialized({ forceNew = false, title = 'Support Request' } = {}) {
        return new Promise((resolve, reject) => {
            const effectiveForceNew = forceNew || shouldForceNewConversation;

            if (!effectiveForceNew && conversationId) {
                if (!appUserId) {
                    const storedAppUserId = localStorage.getItem(`chat_appUserId_${conversationId}`)
                        || localStorage.getItem('chat_user_id');
                    if (storedAppUserId) {
                        appUserId = storedAppUserId;
                    }
                }
                if (appUserId) {
                    resolve({ appUserId, conversationId });
                    return;
                }
            }

            const storedUserId = localStorage.getItem('chat_user_id');
            const payload = {
                userId: storedUserId || null,
                forceNew: effectiveForceNew
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
                    if (!data.appUserId || !data.conversationId) {
                        throw new Error('Chat initialization failed');
                    }

                    appUserId = data.appUserId;
                    conversationId = data.conversationId;

                    if (data.externalId) {
                        localStorage.setItem('chat_user_id', data.externalId);
                    }

                    localStorage.setItem(`chat_appUserId_${conversationId}`, appUserId);
                    localStorage.setItem('chat_current_conversation', conversationId);
                    setForceNewConversation(false);
                    saveConversation(conversationId, title || 'Support Request', '', new Date().toISOString());

                    if (sunshineSocket) {
                        sunshineSocket.disconnect();
                    }
                    sunshineSocket = new SunshineWebSocketManager(conversationId);
                    sunshineSocket.connect();

                    resolve({ appUserId, conversationId });
                })
                .catch(reject);
        });
    }

    function connectToAgentDirect({ optionLabel = null, forceNewConversation = false } = {}) {
        if (optionLabel) {
            appendMessage(optionLabel, 'user-message');
        }

        setTimeout(() => {
            removeLoadingIndicator();
            showLoadingIndicator();
            chatInputArea.style.display = 'flex';
            chatInput.focus();

            const agentReason = getCurrentFlowPath() || lastContext;
            const appCategory = flowState.mainCategory === "App Related Issues"
                ? (flowState.category || window.lastAppRelatedCategory)
                : null;

            if (forceNewConversation || shouldForceNewConversation || !conversationId) {
                createConversationAndEscalate(agentReason, appCategory);
            } else {
                performEscalation(agentReason, appCategory);
            }
        }, 500);
    }

    function handleAgentConnect(option) {
        connectToAgentDirect({ optionLabel: option });
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
            closeActiveModals();
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
        const options = mainOptions.length > 0 ? mainOptions : ["App Related Issues", "Ride Related Issues"];
        appendOptions(options, handleMainOptionClick);
    }

    function handleMainOptionClick(option) {
        appendMessage(option, 'user-message');
        updateFlowState({
            mainCategory: option,
            category: null,
            subcategory: null,
            detail: null
        });

        if (option === "App Related Issues") {
            setTimeout(() => {
                appendMessage(getFlowCopy('appPrompt', "Choose one from the below options."), 'bot-message');
                showAppRelatedOptions();
            }, 500);
        } else if (option === "Ride Related Issues") {
            setTimeout(() => {
                appendMessage(getFlowCopy('rideCategoryPrompt', "Choose your concern."), 'bot-message');
                showRideRelatedOptions();
            }, 500);
        } else {
            setTimeout(() => {
                appendMessage("I'm sorry, I don't have information on that yet.", 'bot-message');
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
        updateFlowState({
            category: option,
            subcategory: null,
            detail: null
        });
        window.lastAppRelatedCategory = option;

        if (option === "Others") {
            setTimeout(() => {
                showSupportFormModal({
                    title: "Describe your issue",
                    textLabel: "Comment *",
                    textHelp: "Minimum 10 characters",
                    placeholder: getFlowCopy('appOtherPrompt', "Please describe your issue."),
                    requireText: true,
                    minLength: 10,
                    submitLabel: "Submit",
                    backLabel: "Back",
                    onBack: () => {
                        updateFlowState({
                            category: null,
                            subcategory: null,
                            detail: null
                        });
                        window.lastAppRelatedCategory = null;
                        setTimeout(() => {
                            appendMessage(getFlowCopy('appPrompt', "Choose one from the below options."), 'bot-message');
                            showAppRelatedOptions();
                        }, 300);
                    },
                    onSubmit: payload => {
                        const summary = buildIssueSummary({
                            comments: payload.text
                        });
                        submitSupportIssue({
                            summary: summary,
                            showUserSummary: false,
                            successMessage: getFlowCopy('appOtherLoggedMessage', "Thank you for sharing details. We have logged your issue."),
                            forceNewConversation: true,
                            afterSubmit: () => {
                                connectToAgentDirect();
                            }
                        });
                    }
                });
            }, 500);
        } else if (troubleshootingSteps[option]) {
            setTimeout(() => {
                appendMessage(troubleshootingSteps[option], 'bot-message');
                askTroubleshootingProgress(option);
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
            appendMessage(getFlowCopy('feedbackPrompt', "Was this helpful?"), 'bot-message');
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

    function askTroubleshootingProgress(issueLabel) {
        setTimeout(() => {
            appendMessage(getFlowCopy('appTroubleshootingPrompt', "Did you perform the troubleshooting steps?"), 'bot-message');
            appendOptions(["Yes", "No"], option => handleTroubleshootingProgress(issueLabel, option));
        }, 500);
    }

    function handleTroubleshootingProgress(issueLabel, option) {
        appendMessage(option, 'user-message');

        if (option === "Yes") {
            askAppResolution(issueLabel);
            return;
        }

        setTimeout(() => {
            appendMessage(getFlowCopy('appTryTroubleshooting', "Please try the troubleshooting steps and let me know if the issue is resolved."), 'bot-message');
            appendOptions(["I tried them", "Connect to Agent"], choice => {
                if (choice === "Connect to Agent") {
                    connectToAgentDirect({ optionLabel: choice });
                    return;
                }
                appendMessage(choice, 'user-message');
                askAppResolution(issueLabel);
            });
        }, 500);
    }

    function askAppResolution(issueLabel) {
        setTimeout(() => {
            appendMessage(getFlowCopy('appResolutionPrompt', "Was the issue resolved?"), 'bot-message');
            appendOptions(["Yes", "No"], option => handleAppResolution(issueLabel, option));
        }, 500);
    }

    function handleAppResolution(issueLabel, option) {
        appendMessage(option, 'user-message');

        if (option === "Yes") {
            setTimeout(() => {
                appendMessage("Glad to know the issue is resolved.", 'bot-message');
                askForFeedback();
            }, 500);
            return;
        }

        connectToAgentDirect();
    }

    function showRideRelatedOptions() {
        const options = rideRelatedOptions.length > 0 ? rideRelatedOptions : [
            "Fare and Payment",
            "Find a lost item",
            "Vehicle related issue",
            "Safety related"
        ];
        appendOptions(options, handleRideRelatedOptionClick);
    }

    function handleRideRelatedOptionClick(option) {
        appendMessage(option, 'user-message');
        updateFlowState({
            category: option,
            subcategory: null,
            detail: null
        });

        if (option === "Fare and Payment") {
            setTimeout(() => {
                appendMessage(getFlowCopy('farePaymentPrompt', "Choose one from the below options."), 'bot-message');
                showFarePaymentOptions();
            }, 500);
            return;
        }

        if (option === "Find a lost item") {
            handleLostItemFlow();
            return;
        }

        if (option === "Vehicle related issue") {
            setTimeout(() => {
                appendMessage("Choose one from the below options.", 'bot-message');
                showVehicleRelatedOptions();
            }, 500);
            return;
        }

        if (option === "Safety related") {
            setTimeout(() => {
                appendMessage(getFlowCopy('safetyIssuePrompt', "Choose one from the below options."), 'bot-message');
                showSafetyRelatedOptions();
            }, 500);
            return;
        }

        askForFeedback();
    }

    function showFarePaymentOptions() {
        const options = farePaymentOptions.length > 0 ? farePaymentOptions : [
            "Multiple Debits occurred",
            "Driver charged extra fare",
            "Charged higher than estimated fare",
            "Cancellation Charges"
        ];
        appendOptions(options, handleFarePaymentOptionClick);
    }

    function handleFarePaymentOptionClick(option) {
        appendMessage(option, 'user-message');
        updateFlowState({
            subcategory: option,
            detail: null
        });

        if (option === "Multiple Debits occurred") {
            setTimeout(() => {
                showSupportFormModal({
                    title: "Multiple Debits occurred",
                    description: getFlowCopy('multipleDebitsPrompt', "Please upload screenshot(s) of the payment and add comments."),
                    textLabel: "Short comment *",
                    textHelp: "Minimum 10 characters",
                    placeholder: "Add comments...",
                    requireText: true,
                    minLength: 10,
                    allowFiles: true,
                    filesRequired: true,
                    fileLabel: "Upload screenshot(s) *",
                    fileButtonText: "Choose screenshot(s)",
                    emptyFilesText: "No screenshot selected",
                    submitLabel: "Submit",
                    onSubmit: payload => {
                        const summary = buildIssueSummary({
                            comments: payload.text,
                            files: payload.files
                        });
                        if (payload.text) {
                            appendMessage(payload.text, 'user-message');
                        }
                        submitSupportIssue({
                            summary: summary,
                            files: payload.files,
                            showUserSummary: false,
                            successMessage: '',
                            afterSubmit: () => connectToAgentDirect()
                        });
                    }
                });
            }, 500);
            return;
        }

        if (option === "Driver charged extra fare") {
            setTimeout(() => {
                appendMessage("Select the mode of payment.", 'bot-message');
                showPaymentModes();
            }, 500);
            return;
        }

        if (option === "Charged higher than estimated fare") {
            setTimeout(() => {
                appendMessage(getFlowCopy('fareBreakdownPrompt', "Please find the fare breakdown."), 'bot-message');
                setTimeout(() => {
                    appendMessage(
                        getFlowCopy(
                            'fareBreakdownExample',
                            "Fare breakdown example:\nBase fare: Rs. 80\nDistance fare: Rs. 120\nPickup charge: Rs. 20\nPlatform fee: Rs. 10\nTotal fare: Rs. 230"
                        ),
                        'bot-message'
                    );
                    askFarePaymentFurtherHelp();
                }, 500);
            }, 500);
            return;
        }

        if (option === "Cancellation Charges") {
            setTimeout(() => {
                appendMessage("Choose one from the below options.", 'bot-message');
                showCancellationChargeOptions();
            }, 500);
        }
    }

    function showPaymentModes() {
        const options = paymentModes.length > 0 ? paymentModes : ["Cash", "UPI"];
        appendOptions(options, handlePaymentModeClick);
    }

    function handlePaymentModeClick(option) {
        appendMessage(option, 'user-message');
        updateFlowState({ detail: option });

        const isCash = option === "Cash";
        setTimeout(() => {
            if (isCash) {
                appendMessage(getFlowCopy('extraFareCashPrompt', "Our executive will be verifying your claim with the driver. Would you like to proceed?"), 'bot-message');
                appendOptions(["Yes", "No"], cashOption => {
                    appendMessage(cashOption, 'user-message');
                    if (cashOption === "Yes") {
                        handleAgentConnect();
                        return;
                    }
                    setTimeout(() => {
                        appendMessage(getFlowCopy('endFlowPrompt', "CSAT"), 'bot-message');
                        chatInputArea.style.display = 'none';
                    }, 500);
                });
                return;
            }

            showSupportFormModal({
                title: "UPI Issue",
                description: getFlowCopy('extraFareUpiPrompt', "Please upload screenshot(s) of the UPI payment and add comments."),
                textLabel: "Short comment *",
                textHelp: "Minimum 10 characters",
                placeholder: "Add comments...",
                requireText: true,
                minLength: 10,
                allowFiles: true,
                filesRequired: true,
                fileLabel: "Upload screenshot(s) *",
                fileButtonText: "Choose screenshot(s)",
                emptyFilesText: "No screenshot selected",
                submitLabel: "Submit",
                onSubmit: payload => {
                    const summary = buildIssueSummary({
                        comments: payload.text,
                        files: payload.files
                    });
                    if (payload.text) {
                        appendMessage(payload.text, 'user-message');
                    }
                    submitSupportIssue({
                        summary: summary,
                        files: payload.files,
                        showUserSummary: false,
                        successMessage: getFlowCopy('issueLoggedMessage', "Thanks for sharing the details. We have logged your issue."),
                        afterSubmit: () => showCsatBubble()
                    });
                }
            });
        }, 500);
    }

    function askVerificationProceed() {
        setTimeout(() => {
            appendMessage(getFlowCopy('verificationPrompt', "Our executive will verify your claim with the driver. Would you like to proceed?"), 'bot-message');
            appendOptions(["Yes", "No"], option => {
                appendMessage(option, 'user-message');
                if (option === "Yes") {
                    handleAgentConnect();
                    return;
                }
                setTimeout(() => {
                    appendMessage(getFlowCopy('verificationDeclinedMessage', "Okay, we will not proceed with this request right now."), 'bot-message');
                    askFarePaymentFurtherHelp();
                }, 500);
            });
        }, 500);
    }

    function askFarePaymentFurtherHelp() {
        askForFurtherHelp({
            prompt: "Do you need any further help?",
            onYes: () => connectToAgentDirect(),
            onNo: () => showCsatBubble(),
            layout: 'row'
        });
    }

    function showCancellationChargeOptions() {
        const options = cancellationChargeOptions.length > 0 ? cancellationChargeOptions : [
            "Cancellation Charge Reason",
            "Wrongly Charged"
        ];
        appendOptions(options, handleCancellationChargeOptionClick);
    }

    function handleCancellationChargeOptionClick(option) {
        appendMessage(option, 'user-message');
        updateFlowState({ detail: option });

        if (option === "Cancellation Charge Reason") {
            setTimeout(() => {
                appendMessage(getFlowCopy('cancellationReasonInfo', "Driver had travelled a significant distance towards the pickup location when you cancelled the ride. To compensate for their time and effort, a cancellation fee equal to the pickup fee may be charged."), 'bot-message');
            }, 500);
            return;
        }

        setTimeout(() => {
            appendMessage(getFlowCopy('wronglyChargedPrompt', "Choose one from the below options."), 'bot-message');
            showCancellationWaiverOptions();
        }, 500);
    }

    function showCancellationWaiverOptions() {
        const options = cancellationWaiverOptions.length > 0 ? cancellationWaiverOptions : [
            "Driver Not Moving",
            "Driver asked to cancel",
            "Could not connect with Driver",
            "Driver was Impolite"
        ];
        appendOptions(options, handleCancellationWaiverOptionClick);
    }

    function handleCancellationWaiverOptionClick(option) {
        appendMessage(option, 'user-message');
        updateFlowState({ detail: option });
        showLoadingIndicator();

        ensureConversationInitialized({
            title: flowState.category || lastContext || 'Support Request'
        })
            .then(() => {
                const summary = buildIssueSummary({ selection: option });
                if (summary) {
                    saveConversation(conversationId, null, summary, new Date().toISOString());
                    sendToSunshine(summary);
                }
                return callCancellationChargeWaiveOffApi(option);
            })
            .then(isApproved => {
                removeLoadingIndicator();
                appendMessage(
                    isApproved
                        ? getFlowCopy('cancellationWaivedMessage', "Your cancellation charges for this ride has been waived off.")
                        : getFlowCopy('cancellationNotWaivedMessage', "Sorry, your cancellation charges cannot be waived off."),
                    'bot-message'
                );

                if (isApproved) {
                    setTimeout(() => {
                        appendMessage(getFlowCopy('cancellationRefrainMessage', "Kindly refrain from cancelling rides at the last moment."), 'bot-message');
                        showEndFlowCsat();
                    }, 500);
                    return;
                }

                showEndFlowCsat();
            })
            .catch(() => {
                removeLoadingIndicator();
                appendMessage("Connection error. Please try again.", 'system-message');
            });
    }

    function handleLostItemFlow() {
        let lostItemCallOptionsDiv = null;

        setTimeout(() => {
            appendMessage(getFlowCopy('lostItemIntro', "Please find the details of your ride. Please call the driver to enquire about your belongings."), 'bot-message');
            setTimeout(() => {
                lostItemCallOptionsDiv = appendOptions(["Call Driver", "Call Alternate Number"], handleLostItemAction);
                setTimeout(() => {
                    appendMessage(getFlowCopy('lostItemFurtherHelpPrompt', "Do you need any further assistance?"), 'bot-message');
                    appendOptions(["Yes", "No"], lostItemHelpChoice => {
                        if (lostItemCallOptionsDiv && lostItemCallOptionsDiv.isConnected) {
                            lostItemCallOptionsDiv.querySelectorAll('.option-btn').forEach(button => {
                                button.disabled = true;
                                button.style.opacity = '0.5';
                            });
                        }

                        appendMessage(lostItemHelpChoice, 'user-message');
                        if (lostItemHelpChoice === "Yes") {
                            promptAgentTransfer();
                            return;
                        }

                        showCsatBubble();
                    }, { layout: 'row' });
                }, 500);
            }, 500);
        }, 500);
    }

    function handleLostItemAction(option) {
        appendMessage(option, 'user-message');

        setTimeout(() => {
            appendMessage(
                option === "Call Driver"
                    ? getFlowCopy('lostItemCallDriverNote', "Use the ride details screen to call the driver. If an alternate number is available, you can try that as well.")
                    : "If an alternate number is available for the ride, you can try that as well.",
                'bot-message'
            );
        }, 500);
    }

    function showVehicleRelatedOptions() {
        const options = vehicleRelatedOptions.length > 0 ? vehicleRelatedOptions : [
            "Unclean/unhygienic vehicle",
            "Vehicle unsafe",
            "AC not turned on / AC stopped working midway",
            "Vehicle was different"
        ];
        appendOptions(options, handleVehicleRelatedOptionClick);
    }

    function handleVehicleRelatedOptionClick(option) {
        appendMessage(option, 'user-message');
        const normalizedOption = option === "Unclean / unhygienic vehicle"
            ? "Unclean/unhygienic vehicle"
            : option;

        updateFlowState({
            subcategory: normalizedOption,
            detail: null
        });

        if (normalizedOption === "Vehicle unsafe") {
            setTimeout(() => {
                appendMessage(getFlowCopy('vehicleUnsafePrompt', "Select all that apply."), 'bot-message');
                showVehicleUnsafeOptions();
            }, 500);
            return;
        }

        const responseMap = {
            "AC not turned on / AC stopped working midway": getFlowCopy('acIssueResponse', "We apologise for the poor experience. This is not something we wish for our customers.\nIt is advisable to cancel this ride and book another ride"),
            "Unclean/unhygienic vehicle": getFlowCopy('uncleanVehicleResponse', "We apologise for the poor experience. This is not something we wish for our customers.\nWe will take your feedback and work towards improving your experience going forward"),
            "Vehicle was different": getFlowCopy('vehicleDifferentResponse', "We apologise for the poor experience. This is not something we wish for our customers.\nIt is advisable to cancel this ride and book another ride")
        };

        if (normalizedOption === "Unclean/unhygienic vehicle") {
            logSupportIssueSilently({
                summary: buildIssueSummary(),
                title: normalizedOption
            });
            setTimeout(() => {
                appendMessage(responseMap[normalizedOption], 'bot-message');
                showCsatBubble();
            }, 500);
            return;
        }

        if (
            normalizedOption === "AC not turned on / AC stopped working midway" ||
            normalizedOption === "Vehicle was different"
        ) {
            logSupportIssueSilently({
                summary: buildIssueSummary(),
                title: normalizedOption
            });
            setTimeout(() => {
                appendMessage(responseMap[normalizedOption], 'bot-message');
                askForFurtherHelp({
                    prompt: getFlowCopy('vehicleFurtherHelpPrompt', "Do you need any further help?"),
                    onYes: () => promptAgentTransfer(),
                    onNo: () => showCsatBubble(),
                    layout: 'row'
                });
            }, 500);
            return;
        }

        setTimeout(() => {
            appendMessage(
                getFlowCopy('issueLoggedMessage', "Thanks for sharing the details. We have logged your issue."),
                'bot-message'
            );
        }, 500);
    }

    function showVehicleUnsafeOptions() {
        const options = vehicleUnsafeCategories.length > 0 ? vehicleUnsafeCategories : [
            "Ineffective brakes",
            "Dark tinted glass",
            "Wheel wobbling",
            "Door is loose"
        ];
        appendMultiSelectOptions(options, selectedOptions => {
            const selectedText = selectedOptions.join(', ');
            updateFlowState({ detail: selectedText });
            appendMessage(`${getFlowCopy('vehicleUnsafeSelectionPrefix', "You have selected:")} ${selectedText}`, 'bot-message');
            logSupportIssueSilently({
                summary: buildIssueSummary({ selection: selectedText }),
                title: "Vehicle unsafe"
            });
            setTimeout(() => {
                appendMessage(
                    getFlowCopy('vehicleUnsafeResponse', "We have taken your feedback regarding the vehicle being unsafe and we will be taking this up with the driver."),
                    'bot-message'
                );
                showCsatBubble();
            }, 500);
        });
    }

    function showSafetyRelatedOptions() {
        const options = safetyRelatedOptions.length > 0 ? safetyRelatedOptions : [
            "Drunk and drive",
            "Driver was rude or misbehaved",
            "Other",
            "Met with an accident",
            "Sexual Harassment",
            "Physical Fights",
            "Extra Person in the vehicle",
            "Rash Driving",
            "Vehicle Broke down"
        ];
        appendOptions(options, handleSafetyRelatedOptionClick);
    }

    function handleSafetyRelatedOptionClick(option) {
        appendMessage(option, 'user-message');
        updateFlowState({
            subcategory: option,
            detail: null
        });

        if (option === "Other") {
            setTimeout(() => {
                showSupportFormModal({
                    title: "Safety issue",
                    description: getFlowCopy('safetyOtherPrompt', "Please enter your issue."),
                    textLabel: "Enter issue *",
                    textHelp: "Minimum 10 characters",
                    placeholder: "Please enter your issue...",
                    requireText: true,
                    minLength: 10,
                    submitLabel: "Submit",
                    onSubmit: payload => {
                        const summary = buildIssueSummary({
                            comments: payload.text
                        });
                        if (payload.text) {
                            appendMessage(payload.text, 'user-message');
                        }
                        logSupportIssueSilently({
                            summary: summary,
                            title: "Safety Other"
                        });
                        setTimeout(() => {
                            appendMessage(
                                getFlowCopy('safetyThankYou', "Thank you for reporting the issue. We have taken your feedback and we will work towards improving your experience."),
                                'bot-message'
                            );
                            askForFurtherHelp({
                                prompt: getFlowCopy('drunkDriveFurtherHelpPrompt', "Do you need further help?"),
                                onYes: () => promptSafetySosFlow("Safety Other SOS"),
                                onNo: () => showCsatBubble(),
                                layout: 'row'
                            });
                        }, 500);
                    }
                });
            }, 500);
            return;
        }

        if ([
            "Met with an accident",
            "Sexual Harassment",
            "Physical Fights",
            "Extra Person in the vehicle",
            "Rash Driving",
            "Vehicle Broke down"
        ].includes(option)) {
            promptSafetySosFlow(`${option} SOS`);
            return;
        }

        if (option === "Drunk and drive") {
            handleDrunkAndDriveFlow();
            return;
        }

        if (option === "Driver was rude or misbehaved") {
            handleDriverMisbehavedFlow();
            return;
        }

        const successMessage = option === "Drunk and drive"
            ? getFlowCopy('safetyImmediateResponse', "We sincerely apologise for your experience. Your safety is our top priority, and we take such incidents very seriously. This has been escalated to the safety team for immediate action against the driver.")
            : getFlowCopy('safetyFeedbackResponse', "We apologise for the poor experience. This is not something we wish for our customers. We have taken your feedback and we will work towards improving your experience.");

        submitSupportIssue({
            summary: buildIssueSummary(),
            successMessage: successMessage,
            afterSubmit: () => askForFurtherHelp()
        });
    }

    function handleDrunkAndDriveFlow() {
        logSupportIssueSilently({
            summary: buildIssueSummary(),
            title: "Drunk and drive"
        });

        setTimeout(() => {
            appendMessage(
                getFlowCopy(
                    'safetyImmediateResponse',
                    "We sincerely apologize for your experience. Your safety is our top priority, and we take such incidents very seriously.\nThis has been escalated to safety team for immediate action against the driver."
                ),
                'bot-message'
            );
            askForFurtherHelp({
                prompt: getFlowCopy('drunkDriveFurtherHelpPrompt', "Do you need further help?"),
                onYes: () => promptSafetySosFlow("Drunk and drive SOS"),
                onNo: () => showCsatBubble(),
                layout: 'row'
            });
        }, 500);
    }

    function handleDriverMisbehavedFlow() {
        logSupportIssueSilently({
            summary: buildIssueSummary(),
            title: "Driver was rude or misbehaved"
        });

        setTimeout(() => {
            appendMessage(
                getFlowCopy(
                    'safetyRudeResponse',
                    "We apologise for the poor experience. This is not something we wish for our customers.\nWe have taken your feedback and we will work towards improving your experience."
                ),
                'bot-message'
            );
            askForFurtherHelp({
                prompt: getFlowCopy('drunkDriveFurtherHelpPrompt', "Do you need further help?"),
                onYes: () => promptSafetySosFlow("Driver was rude or misbehaved SOS"),
                onNo: () => showCsatBubble(),
                layout: 'row'
            });
        }, 500);
    }

    function promptSafetySosFlow(sosTitle = "Safety SOS") {
        setTimeout(() => {
            appendMessage(getFlowCopy('drunkDriveSosPrompt', "This will raise an SOS alert. Proceed?"), 'bot-message');
            appendOptions(["Yes, proceed", "No"], option => {
                appendMessage(option, 'user-message');
                if (option === "Yes, proceed") {
                    logSupportIssueSilently({
                        summary: buildIssueSummary({ selection: "SOS requested" }),
                        title: sosTitle
                    });
                    setTimeout(() => {
                        appendMessage(
                            getFlowCopy('sosRaisedMessage', "SOS ticket raised. Our safety team has been notified."),
                            'bot-message'
                        );
                        showCsatBubble();
                    }, 500);
                    return;
                }

                showCsatBubble();
            }, { layout: 'row' });
        }, 500);
    }

    function showSupportFormModal(config) {
        closeActiveModals();
        const modal = document.createElement('div');
        modal.classList.add('chat-modal', 'support-form-modal');

        const header = document.createElement('div');
        header.classList.add('chat-modal-header');
        header.textContent = config.title || 'Share details';

        const description = document.createElement('p');
        description.classList.add('support-form-description');
        description.textContent = config.description || '';

        const form = document.createElement('div');
        form.classList.add('support-form');

        let selectedFiles = [];
        let textArea = null;

        if (config.placeholder !== false) {
            const textSection = document.createElement('div');
            textSection.classList.add('support-form-section');

            const textLabel = document.createElement('label');
            textLabel.classList.add('support-form-field-label');
            textLabel.textContent = config.textLabel || (config.requireText ? 'Comments *' : 'Comments');
            textSection.appendChild(textLabel);

            textArea = document.createElement('textarea');
            textArea.classList.add('support-form-textarea');
            textArea.placeholder = config.placeholder || 'Type here...';
            textSection.appendChild(textArea);

            if (config.textHelp || config.minLength) {
                const note = document.createElement('div');
                note.classList.add('support-form-note');
                note.textContent = config.textHelp || `Minimum ${config.minLength} characters`;
                textSection.appendChild(note);
            }

            form.appendChild(textSection);
        }

        let filePicker = null;
        let fileList = null;
        if (config.allowFiles) {
            const fileSection = document.createElement('div');
            fileSection.classList.add('support-form-section');

            const fileLabel = document.createElement('label');
            fileLabel.classList.add('support-form-file-label');
            fileLabel.textContent = config.fileLabel || (config.filesRequired ? 'Upload file(s) *' : 'Upload file(s)');
            fileSection.appendChild(fileLabel);

            filePicker = document.createElement('input');
            filePicker.type = 'file';
            filePicker.multiple = config.multiple !== false;
            filePicker.accept = '.pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.gif';
            filePicker.classList.add('support-form-file-input');

            const fileTrigger = document.createElement('button');
            fileTrigger.type = 'button';
            fileTrigger.classList.add('support-form-file-trigger');
            fileTrigger.textContent = config.fileButtonText || 'Choose file(s)';
            fileTrigger.addEventListener('click', function () {
                filePicker.click();
            });

            fileList = document.createElement('div');
            fileList.classList.add('support-form-file-list');
            fileList.textContent = config.emptyFilesText || 'No file selected';

            fileSection.appendChild(filePicker);
            fileSection.appendChild(fileTrigger);
            fileSection.appendChild(fileList);
            form.appendChild(fileSection);
        }

        const buttonsDiv = document.createElement('div');
        buttonsDiv.classList.add('modal-buttons');

        const submitBtn = document.createElement('button');
        submitBtn.classList.add('modal-btn', 'btn-submit');
        submitBtn.textContent = config.submitLabel || 'Submit';
        submitBtn.disabled = true;

        const backBtn = document.createElement('button');
        backBtn.classList.add('modal-btn', 'btn-back');
        backBtn.textContent = config.backLabel || 'Go Back';

        buttonsDiv.appendChild(submitBtn);
        buttonsDiv.appendChild(backBtn);

        modal.appendChild(header);
        if (description.textContent) {
            modal.appendChild(description);
        }
        modal.appendChild(form);
        modal.appendChild(buttonsDiv);
        chatBox.appendChild(modal);

        function renderFiles() {
            if (!fileList) {
                return;
            }
            if (selectedFiles.length === 0) {
                fileList.textContent = config.emptyFilesText || 'No file selected';
                return;
            }
            fileList.innerHTML = '';
            selectedFiles.forEach(file => {
                const chip = document.createElement('div');
                chip.classList.add('support-form-file-chip');
                chip.textContent = file.name;
                fileList.appendChild(chip);
            });
        }

        function validate() {
            const textValue = textArea ? textArea.value.trim() : '';
            const hasEnoughText = !config.requireText || textValue.length >= (config.minLength || 0);
            const hasFiles = !config.filesRequired || selectedFiles.length > 0;
            submitBtn.disabled = !(hasEnoughText && hasFiles);
        }

        if (textArea) {
            textArea.addEventListener('input', validate);
            textArea.focus();
        }

        if (filePicker) {
            filePicker.addEventListener('change', function () {
                selectedFiles = Array.from(filePicker.files || []);
                renderFiles();
                validate();
            });
        }

        validate();

        backBtn.addEventListener('click', function () {
            modal.remove();
            if (typeof config.onBack === 'function') {
                config.onBack();
            }
        });

        submitBtn.addEventListener('click', function () {
            const payload = {
                text: textArea ? textArea.value.trim() : '',
                files: selectedFiles
            };
            modal.remove();
            config.onSubmit(payload);
        });
    }

    function submitSupportIssue({
        summary = '',
        files = [],
        showUserSummary = false,
        successMessage = '',
        afterSubmit = null,
        title = null,
        forceNewConversation = false
    }) {
        const supportSummary = summary || buildIssueSummary();

        ensureConversationInitialized({
            forceNew: forceNewConversation,
            title: title || flowState.category || lastContext || 'Support Request'
        })
            .then(() => {
                if (showUserSummary && supportSummary) {
                    appendMessage(supportSummary, 'user-message');
                }

                if (supportSummary) {
                    saveConversation(conversationId, null, supportSummary, new Date().toISOString());
                    sendToSunshine(supportSummary);
                }

                if (files && files.length > 0) {
                    files.forEach(file => sendDocument(file, ''));
                }

                setTimeout(() => {
                    if (successMessage) {
                        appendMessage(successMessage, 'bot-message');
                    }
                    if (typeof afterSubmit === 'function') {
                        afterSubmit();
                    }
                }, 500);
            })
            .catch(() => {
                appendMessage("Connection error. Please try again.", 'system-message');
            });
    }

    function logSupportIssueSilently({
        summary = '',
        files = [],
        title = null
    } = {}) {
        const supportSummary = summary || buildIssueSummary();

        ensureConversationInitialized({
            title: title || flowState.category || lastContext || 'Support Request'
        })
            .then(() => {
                if (supportSummary) {
                    saveConversation(conversationId, null, supportSummary, new Date().toISOString());
                    sendToSunshine(supportSummary);
                }

                if (files && files.length > 0) {
                    files.forEach(file => sendDocument(file, ''));
                }
            })
            .catch(() => {});
    }

    function showEndFlowCsat(prompt = null) {
        setTimeout(() => {
            appendMessage(prompt || getFlowCopy('endFlowPrompt', "Was this helpful?"), 'bot-message');
            appendOptions(["Yes", "No"], option => {
                appendMessage(option, 'user-message');
                setTimeout(() => {
                    appendMessage(getFlowCopy('endFlowClosure', "Thank you for your feedback."), 'bot-message');
                    chatInputArea.style.display = 'none';
                }, 500);
            });
        }, 500);
    }

    function showCsatBubble(message = null) {
        setTimeout(() => {
            appendMessage(message || getFlowCopy('endFlowPrompt', "CSAT"), 'bot-message');
            chatInputArea.style.display = 'none';
        }, 500);
    }

    function callCancellationChargeWaiveOffApi(reason) {
        const fallbackResult = cancellationWaiverApprovedReasons.includes(reason);

        if (!conversationId || !appUserId) {
            return Promise.resolve(fallbackResult);
        }

        return fetch('/api/chat/cancellation-charges/waive-off', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                conversationId: conversationId,
                appUserId: appUserId,
                reason: reason
            })
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return response.json();
            })
            .then(data => Boolean(data.waivedOffSuccess))
            .catch(() => fallbackResult);
    }

    function askForFurtherHelp({ prompt = null, onYes = null, onNo = null, layout = null } = {}) {
        setTimeout(() => {
            appendMessage(prompt || getFlowCopy('furtherHelpPrompt', "Do you need further help?"), 'bot-message');
            appendOptions(["Yes", "No"], option => {
                appendMessage(option, 'user-message');
                if (option === "Yes") {
                    if (typeof onYes === 'function') {
                        onYes();
                    } else {
                        promptAgentTransfer();
                    }
                    return;
                }

                if (typeof onNo === 'function') {
                    onNo();
                } else {
                    askForFeedback();
                }
            }, layout ? { layout } : {});
        }, 500);
    }

    function promptAgentTransfer(message = null) {
        setTimeout(() => {
            appendMessage(
                message || getFlowCopy('appAgentTransferPrompt', "I can connect you to a human agent for more help."),
                'bot-message'
            );
            appendOptions(["Connect to Agent"], handleAgentConnect);
        }, 500);
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
            ensureConversationInitialized({
                title: lastContext || 'Support Request'
            })
                .then(() => {
                    removeLoadingIndicator();
                    appendMessage(messageText, 'user-message');
                    saveConversation(conversationId, null, messageText, new Date().toISOString());
                    sendToSunshine(messageText);
                    chatInput.value = '';
                    chatInputArea.style.display = 'none';

                    if (!isAgentConnected) {
                        setTimeout(() => {
                            appendMessage("Your issue has been forwarded to our support team. An agent will review it shortly.", 'bot-message');
                        }, 1500);
                    }
                })
                .catch(() => {
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

    function appendOptions(options, callback, config = {}) {
        const optionsDiv = document.createElement('div');
        optionsDiv.classList.add('options-container');
        if (config.layout === 'row') {
            optionsDiv.classList.add('options-row');
        }

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
        return optionsDiv;
    }

    function appendMultiSelectOptions(options, onSubmit, config = {}) {
        const multiSelectDiv = document.createElement('div');
        multiSelectDiv.classList.add('multi-select-container');

        const optionsList = document.createElement('div');
        optionsList.classList.add('multi-select-list');

        const selectedValues = new Set();

        options.forEach(option => {
            const label = document.createElement('label');
            label.classList.add('multi-select-item');

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = option;

            const text = document.createElement('span');
            text.textContent = option;

            checkbox.addEventListener('change', function () {
                if (checkbox.checked) {
                    selectedValues.add(option);
                } else {
                    selectedValues.delete(option);
                }
                submitBtn.disabled = selectedValues.size === 0;
            });

            label.appendChild(checkbox);
            label.appendChild(text);
            optionsList.appendChild(label);
        });

        const submitBtn = document.createElement('button');
        submitBtn.classList.add('multi-select-submit');
        submitBtn.textContent = config.submitLabel || 'Submit';
        submitBtn.disabled = true;
        submitBtn.addEventListener('click', function () {
            const selections = Array.from(selectedValues);
            if (selections.length === 0) {
                return;
            }

            multiSelectDiv.remove();
            onSubmit(selections);
        });

        multiSelectDiv.appendChild(optionsList);
        multiSelectDiv.appendChild(submitBtn);
        messagesContainer.appendChild(multiSelectDiv);
        setTimeout(() => scrollToBottom(), 50);
        return multiSelectDiv;
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
        // Delete Account flow intentionally disabled.
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
    const configuredIssuesUrl = window.issuesUrl || 'static/js/issues.json';
    const issuesUrlCandidates = Array.from(new Set([
        configuredIssuesUrl,
        '../static/js/issues.json',
        './static/js/issues.json',
        'static/js/issues.json'
    ].filter(Boolean)));

    function applyFlowConfig(data = {}) {
        troubleshootingSteps = {
            ...DEFAULT_TROUBLESHOOTING_STEPS,
            ...(data.troubleshooting || {})
        };
        mainOptions = data.mainOptions || [];
        appRelatedOptions = data.appRelatedOptions || [];
        rideRelatedOptions = data.rideRelatedOptions || [];
        farePaymentOptions = data.farePaymentOptions || [];
        paymentModes = data.paymentModes || [];
        cancellationChargeOptions = data.cancellationChargeOptions || [];
        cancellationWaiverOptions = data.cancellationWaiverOptions || [];
        cancellationWaiverApprovedReasons = data.cancellationWaiverApprovedReasons || [];
        vehicleRelatedOptions = data.vehicleRelatedOptions || [];
        vehicleUnsafeCategories = data.vehicleUnsafeCategories || [];
        safetyRelatedOptions = data.safetyRelatedOptions || [];
        deleteAccountReasons = [];
        flowCopy = data.copy || {};
    }

    function loadFlowConfig(index = 0) {
        if (index >= issuesUrlCandidates.length) {
            applyFlowConfig({});
            return;
        }

        fetch(issuesUrlCandidates[index])
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                applyFlowConfig(data);
            })
            .catch(() => {
                loadFlowConfig(index + 1);
            });
    }

    loadFlowConfig();
    const lastConversationId = localStorage.getItem('chat_current_conversation');

    if (lastConversationId) {
        const conversations = getStoredConversations();
        const lastConv = conversations.find(c => c.id === lastConversationId);
        
        if (lastConv) {
            conversationId = lastConversationId;
            setForceNewConversation(false);
            const storedUserId = localStorage.getItem(`chat_appUserId_${lastConversationId}`) 
                              || localStorage.getItem('chat_user_id');
            if (storedUserId) {
                appUserId = storedUserId;
            }
        } else {
            localStorage.removeItem('chat_current_conversation');
            setForceNewConversation(true);
        }
    } else {
        setForceNewConversation(true);
    }
    showConversationList();
    initNotificationSystem();
});
