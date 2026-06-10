const chatContainer = document.getElementById('chat-container');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const statusBar = document.getElementById('status-bar');
const aiModeBtn = document.getElementById('ai-mode-btn');
const manualModeBtn = document.getElementById('manual-mode-btn');

let currentMode = 'ai';
let currentAgentMsg = null;

function sendMessage() {
  const text = userInput.value.trim();
  if (!text) return;

  addMessage('user', text);
  userInput.value = '';

  chrome.runtime.sendMessage({ type: 'user_message', content: text });
}

sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

chrome.runtime.onMessage.addListener((message, _sender, _sendResponse) => {
  if (message.type === 'stream') {
    if (message.content === '[DONE]') {
      currentAgentMsg = null;
      return;
    }
    if (message.content === '[BUSY]') {
      addMessage('system', 'Agent 正在工作中，请等待...');
      return;
    }

    if (!currentAgentMsg) {
      currentAgentMsg = addMessage('agent', message.content);
    } else {
      currentAgentMsg.textContent += message.content;
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  }

  if (message.type === 'error') {
    addMessage('system', `错误：${message.message}`);
    currentAgentMsg = null;
  }
});

aiModeBtn.addEventListener('click', () => setMode('ai'));
manualModeBtn.addEventListener('click', () => setMode('manual'));

function setMode(mode) {
  currentMode = mode;
  aiModeBtn.classList.toggle('active', mode === 'ai');
  manualModeBtn.classList.toggle('active', mode === 'manual');
  chrome.runtime.sendMessage({ type: 'mode_change', mode });
}

function updateStatus() {
  chrome.runtime.sendMessage({ type: 'get_status' }, (response) => {
    if (chrome.runtime.lastError || !response) {
      statusBar.textContent = '● 未连接';
      statusBar.className = 'disconnected';
    } else {
      statusBar.textContent = response.connected ? '● 已连接' : '● 未连接';
      statusBar.className = response.connected ? 'connected' : 'disconnected';
    }
  });
}

setInterval(updateStatus, 3000);
updateStatus();

function addMessage(role, text) {
  const div = document.createElement('div');
  div.className = `message ${role}`;
  div.textContent = text;
  chatContainer.appendChild(div);
  chatContainer.scrollTop = chatContainer.scrollHeight;
  return div;
}
