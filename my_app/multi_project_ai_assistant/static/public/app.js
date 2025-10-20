const socket = io();
alert("hhhhhhh")

const chatMessages = document.getElementById('chat-messages');
const messageInput = document.getElementById('message-input');
const sendButton = document.getElementById('send-button');
const modelSelect = document.getElementById('model-select');
const providerRadios = document.getElementsByName('provider');

let currentProvider = 'ollama';

// ---- Dynamic model lists ----
const ollamaModels = [
    "llama3:8b", "llama3.2:3b", "deepseek-v3.1:671b-cloud",
    "qwen3-coder:480b-cloud", "deepseek-r1:14b"
];

const openaiModels = [
    "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"
];

const openrouterModels = [
    "qwen3-vl:235b-cloud", "kimi-k2:1t-cloud", "gpt-oss:120b-cloud",
    "codegeex4:latest", "deepseek-coder:6.7b-instruct"
];

// ---- Load models dynamically ----
function loadModels(provider) {
    modelSelect.innerHTML = `<option>Loading ${provider} models...</option>`;
    let list = [];

    if (provider === 'ollama') list = ollamaModels;
    else if (provider === 'openai') list = openaiModels;
    else if (provider === 'openrouter') list = openrouterModels;

    modelSelect.innerHTML = list.map(m => `<option value="${m}">${m}</option>`).join('');
}

providerRadios.forEach(radio => {
    radio.addEventListener('change', e => {
        currentProvider = e.target.value;
        loadModels(currentProvider);
    });
});

// initial load
loadModels(currentProvider);

// ---- Send message ----
sendButton.addEventListener('click', sendMessage);
messageInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

function sendMessage() {
    const message = messageInput.value.trim();
    const model = modelSelect.value;
    if (!message) return;

    addMessage('user', message);
    messageInput.value = '';
    messageInput.disabled = true;
    sendButton.disabled = true;

    showTypingIndicator();

    socket.emit('send_message', {
        prompt: message,
        model: model,
        provider: currentProvider
    });
}

// ---- Chat UI ----
function addMessage(sender, content) {
    const msg = document.createElement('div');
    msg.className = `message ${sender}-message`;
    msg.innerHTML = `<strong>${sender === 'user' ? 'You' : 'Assistant'}:</strong> ${content}`;
    chatMessages.appendChild(msg);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function showTypingIndicator() {
    const div = document.createElement('div');
    div.id = 'typing';
    div.className = 'message assistant-message';
    div.innerHTML = 'Assistant is thinking...';
    chatMessages.appendChild(div);
}

function hideTypingIndicator() {
    const typing = document.getElementById('typing');
    if (typing) typing.remove();
}

// ---- Listen for response ----
socket.on('receive_message', data => {
    hideTypingIndicator();
    addMessage('assistant', data.reply);
    messageInput.disabled = false;
    sendButton.disabled = false;

    // Example: save to DB on backend using provider + model
});
