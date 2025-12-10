document.addEventListener('DOMContentLoaded', function() {
    const chatWidget = document.querySelector('.chat-widget');
    const chatBox = document.querySelector('.chat-box');
    const toggleBtn = document.querySelector('.chat-toggle-btn');
    const closeBtn = document.querySelector('.chat-close-btn');
    const chatInputArea = document.querySelector('.chat-input');
    const chatInput = document.querySelector('#chat-input-field');
    const sendBtn = document.querySelector('#chat-send-btn');
    const messagesContainer = document.querySelector('.chat-messages');

    let isChatOpen = false;
    let awaitingFeedback = false;

    // Predefined troubleshooting steps and options
    let troubleshootingSteps = {};
    let mainOptions = [];
    let appRelatedOptions = [];
    let deleteAccountReasons = [];

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

    // Handle Agent Connect
    function handleAgentConnect(option) {
        appendMessage(option, 'user-message');
        setTimeout(() => {
            appendMessage("Connecting you to a human agent... Please wait while we transfer your chat.", 'bot-message');
        }, 500);
    }

    // Send Message (For "OTHERS" flow)
    function sendMessage() {
        const messageText = chatInput.value.trim();
        if (messageText === "") return;

        appendMessage(messageText, 'user-message');
        chatInput.value = '';
        chatInputArea.style.display = 'none';

        setTimeout(() => {
            const botResponses = [
                "I understand. Based on your description, it sounds like a configuration issue. Please try resetting your preferences.",
                "That sounds unusual. Could you try reinstalling the application to see if that resolves the glitch?",
                "I see. This might be related to a recent server update. Please try again in 10 minutes."
            ];
            const randomResponse = botResponses[Math.floor(Math.random() * botResponses.length)];
            appendMessage(randomResponse, 'bot-message');
            
            askForFeedback();
        }, 1500);
    }

    // Append Message to UI
    function appendMessage(text, className) {
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
            // No action as requested
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
