
let SYSTEM_PROMPT = `
Write like a friendly human support agent at SanzCart, not an AI.
- Use casual short sentences. Never use bullet points.
- Occasionally use filler words: "sure!", "of course!", "let me check that for you"
- Break long answers into 2-3 separate short messages.
- Never say "I am an AI" or "As an AI" — you are Sanza, a human support agent.
- Use "we" when referring to the company, "I" for personal actions.
- End replies with a natural follow-up question when relevant.
- Current Company: SanzCart (Ecommerce).
`;

// --- State Management ---
let conversationHistory = [];
let currentLanguage = localStorage.getItem('sanza_lang') || (navigator.language.startsWith('ta') ? 'ta' : 'en');
let unreadCount = 0;
let messageTimeline = []; // For rate limiting
let retryCount = 0;
let lastUserMessage = "";
let isMuted = localStorage.getItem('sanza_muted') === 'true';
let lastActivityTime = Date.now();
let isEscalating = false; // For collect name/email flow
let escalationData = { name: '', email: '' };

let analytics = JSON.parse(localStorage.getItem('sanza_analytics')) || {
    totalMessages: 0,
    chipClicks: {},
    avgResponseTime: 0,
    sessionStart: Date.now(),
    responseTimes: []
};

let sanzaConfig = { userId: 'guest', userName: 'Guest' };

// --- Initialization ---
function initSanza() {
    try {
        const widget = document.getElementById('sanza-widget');
        if (widget) {
            sanzaConfig.userId = widget.dataset.userId || 'guest';
            sanzaConfig.userName = widget.dataset.userName || 'Guest';
        }

        loadHistory();
        updateLangUI();
        updateMuteUI();
    } catch (e) {
        console.error('Sanza init basic failed:', e);
    }
    
    try {
    setInterval(presenceManager, 5000);
    // Start Time Updater
    setInterval(updateTimestamps, 60000);

    const msgs = document.getElementById('sanza-messages');
    if (msgs && conversationHistory.length > 0) {
        renderHistory();
        addSystemMessage("Welcome back! Continuing from where we left off 👋");
    }
    
    // Accessibility: Escape to close
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const widget = document.getElementById('sanza-widget');
            if (widget && widget.style.display === 'flex') toggleSanza();
        }
    });

    // Toggle Listeners
    const langBtn = document.getElementById('sanza-lang-toggle');
    if (langBtn) langBtn.onclick = toggleLanguage;

    const muteBtn = document.getElementById('sanza-mute-toggle');
    if (muteBtn) muteBtn.onclick = toggleMute;

    console.log('Sanza Advanced Human Agent Initialization Complete ✓');
}

function presenceManager() {
    const diff = Date.now() - lastActivityTime;
    const statusText = document.getElementById('sanz-status-text');
    const statusDot = document.getElementById('sanz-status-dot');
    const lastSeen = document.getElementById('sanz-last-seen');

    if (diff > 120000) { // 2 mins
        updateAgentStatus('away');
    } else {
        if (statusText && !statusText.classList.contains('sanz-status-typing')) {
            updateAgentStatus('online');
        }
    }
    
    if (lastSeen) {
        const mins = Math.floor(diff / 60000);
        lastSeen.textContent = mins === 0 ? 'Last seen just now' : `Last seen ${mins}m ago`;
    }
}

function updateAgentStatus(status) {
    const text = document.getElementById('sanz-status-text');
    const dot = document.getElementById('sanz-status-dot');
    if (!text || !dot) return;

    if (status === 'typing') {
        text.textContent = 'Typing...';
        text.classList.add('sanz-status-typing');
        dot.className = 'sanz-status-dot online';
    } else if (status === 'away') {
        text.textContent = 'Away';
        text.classList.remove('sanz-status-typing');
        dot.className = 'sanz-status-dot away';
    } else {
        text.textContent = 'Online';
        text.classList.remove('sanz-status-typing');
        dot.className = 'sanz-status-dot online';
    }
}

// --- Language Logic ---
function toggleLanguage() {
    currentLanguage = currentLanguage === 'en' ? 'ta' : 'en';
    localStorage.setItem('sanza_lang', currentLanguage);
    updateLangUI();
    
    const msg = currentLanguage === 'ta' ? "Language switched to Tamil" : "Language switched to English";
    addSystemMessage(msg);
    showToast(msg);
}

function toggleMute() {
    isMuted = !isMuted;
    localStorage.setItem('sanza_muted', isMuted);
    updateMuteUI();
}

function updateMuteUI() {
    const btn = document.getElementById('sanza-mute-toggle');
    if (btn) {
        btn.classList.toggle('muted', isMuted);
    }
}

function playNotif() {
    if (isMuted) return;
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        o.connect(g); g.connect(ctx.destination);
        o.frequency.value = 520;
        g.gain.setValueAtTime(0.1, ctx.currentTime);
        g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
        o.start(); o.stop(ctx.currentTime + 0.3);
        if (navigator.vibrate) navigator.vibrate(100);
    } catch(e) {}
}

function analyzeSentiment(text) {
    const angryWords = ['worst', 'terrible', 'useless', 'refund', 'pathetic', 'hate', 'stupid', 'fraud'];
    const happyWords = ['good', 'great', 'awesome', 'thanks', 'thank you', 'perfect', 'love'];
    const lower = text.toLowerCase();
    
    if (angryWords.some(w => lower.includes(w))) return 'angry';
    if (happyWords.some(w => lower.includes(w))) return 'happy';
    return 'neutral';
}

function updateLangUI() {
    const btn = document.getElementById('sanza-lang-toggle');
    if (btn) btn.textContent = currentLanguage === 'en' ? 'EN' : 'தமிழ்';
    
    const input = document.getElementById('sanza-input');
    if (input) {
        input.placeholder = currentLanguage === 'ta' ? 'செய்தியைத் தட்டச்சு செய்க...' : 'Type your message...';
    }
}

// --- History & Storage ---
function loadHistory() {
    try {
        const saved = localStorage.getItem('sanza_history');
        if (saved) {
            conversationHistory = JSON.parse(saved);
        }
    } catch (e) {
        console.error('Sanza history load failed:', e);
        conversationHistory = [];
    }
}

function saveHistory() {
    try {
        const last50 = conversationHistory.slice(-50);
        localStorage.setItem('sanza_history', JSON.stringify(last50));
        showToast("Conversation saved", 1000);
    } catch {}
}

function renderHistory() {
    const msgs = document.getElementById('sanza-messages');
    if (!msgs) return;
    msgs.innerHTML = '';
    conversationHistory.forEach(msg => {
        if (msg.role === 'user') {
            addUserBubble(msg.parts[0].text, false);
        } else if (msg.role === 'model') {
            addBotBubble(msg.parts[0].text, false);
        }
    });
}

// --- UI Helpers ---
function showToast(text, duration = 3000) {
    const widget = document.getElementById('sanza-widget');
    if (!widget) return;
    const toast = document.createElement('div');
    toast.className = 'sanza-toast';
    toast.textContent = text;
    widget.appendChild(toast);
    setTimeout(() => toast.remove(), duration);
}

function addSystemMessage(text) {
    const msgs = document.getElementById('sanza-messages');
    if (!msgs) return;
    const div = document.createElement('div');
    div.style.textAlign = 'center';
    div.style.margin = '10px 0';
    div.style.fontSize = '0.75rem';
    div.style.color = '#888';
    div.textContent = text;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function updateUnreadBadge() {
    const badge = document.getElementById('sanza-badge');
    const widget = document.getElementById('sanza-widget');
    const isOpen = widget && widget.style.display === 'flex';
    
    if (isOpen) {
        unreadCount = 0;
    }
    
    if (badge) {
        badge.textContent = unreadCount;
        badge.style.display = unreadCount > 0 ? 'flex' : 'none';
        if (unreadCount > 0) badge.classList.add('pulse');
    }
}

// --- API Calls ---
async function callGemini(history, sysPrompt) {
    const start = Date.now();
    const res = await fetch('/api/sanza/chat/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRF()
        },
        body: JSON.stringify({
            history: history,
            system_prompt: sysPrompt,
            language: currentLanguage
        })
    });

    const data = await res.json();
    const end = Date.now();
    
    // Track response time
    analytics.responseTimes.push(end - start);
    updateAnalytics();

    if (!res.ok || data.error) throw new Error(data.error || 'Request failed');
    return data.reply;
}

// Default chips on first open
const DEFAULT_CHIPS = [
  'Where is my order? 📦',
  'How to return? 🔄',
  'Any offers today? 🎁',
  'Delivery charges? 🚚'
];

// Context-based chip mapping
const CHIP_MAP = {
  order: [
    'Track my order 📦',
    'Cancel order ❌',
    'Change address 📍'
  ],
  deliver: [
    'Expected delivery date? 📅',
    'Express delivery available? ⚡',
    'Delivery charges? 🚚'
  ],
  return: [
    'Start return request 🔄',
    'Refund status? 💰',
    'Exchange instead? 🔃'
  ],
  refund: [
    'Refund timeline? ⏳',
    'Refund to which account? 🏦',
    'Check refund status 🔍'
  ],
  payment: [
    'Pay via UPI? 📱',
    'EMI available? 💳',
    'COD available? 💵'
  ],
  offer: [
    'Apply coupon code 🎟️',
    'Flash sale timing? ⚡',
    'Student discount? 🎓'
  ],
  cancel: [
    'Confirm cancellation ✅',
    'Cancel and get refund? 💰',
    'Change order instead? 🔃'
  ],
  product: [
    'Check availability 🛒',
    'Product reviews? ⭐',
    'Add to wishlist? 💖'
  ],
  shipping: [
    'Free shipping? 🆓',
    'Express delivery? ⚡',
    'Track shipment 📍'
  ],
  account: [
    'Reset password 🔐',
    'Update profile 👤',
    'View my orders 📋'
  ],
  cash: [
    'COD charges? 💵',
    'Delivery timeline? 📅',
    'Track my order 📦'
  ]
};

// Detect context from bot reply text
function detectContext(replyText) {
  const text = replyText.toLowerCase();
  
  if (text.includes('cash') || 
      text.includes('cod')) 
    return 'cash';
  if (text.includes('refund')) 
    return 'refund';
  if (text.includes('return') || 
      text.includes('exchange')) 
    return 'return';
  if (text.includes('cancel')) 
    return 'cancel';
  if (text.includes('deliver') || 
      text.includes('ship')) 
    return 'deliver';
  if (text.includes('order') || 
      text.includes('track')) 
    return 'order';
  if (text.includes('payment') || 
      text.includes('pay') || 
      text.includes('upi') || 
      text.includes('emi')) 
    return 'payment';
  if (text.includes('offer') || 
      text.includes('discount') || 
      text.includes('coupon')) 
    return 'offer';
  if (text.includes('product') || 
      text.includes('available') || 
      text.includes('stock')) 
    return 'product';
  if (text.includes('account') || 
      text.includes('login') || 
      text.includes('password')) 
    return 'account';
  
  return null;
}

// Auto-generate chips after bot reply
function autoChips(botReply) {
  const context = detectContext(botReply);
  
  if (context && CHIP_MAP[context]) {
    // Use context-specific chips
    setChips(CHIP_MAP[context]);
  } else {
    // Use default chips
    setChips(DEFAULT_CHIPS);
  }
}

// --- Core Functionality ---
async function sendMessage(text) {
    text = (text || '').trim();
    if (!text) return;

    lastActivityTime = Date.now();
    updateAgentStatus('online');

    // Escalation Flow
    if (isEscalating) {
        handleEscalation(text);
        return;
    }

    const lower = text.toLowerCase();
    if (lower.includes('talk to human') || lower.includes('real agent') || lower.includes('manager')) {
        startEscalation();
        return;
    }

    // Rate Limiting
    const now = Date.now();
    messageTimeline = messageTimeline.filter(t => now - t < 60000);
    if (messageTimeline.length >= 10) {
        const oldest = messageTimeline[0];
        const wait = Math.ceil((60000 - (now - oldest)) / 1000);
        showCooldown(wait);
        return;
    }
    messageTimeline.push(now);

    lastUserMessage = text;
    disableInput();
    
    const msgId = 'u-' + Date.now();
    addUserBubble(text, msgId);

    // Sentiment Detection
    const sentiment = analyzeSentiment(text);
    let dynamicPrompt = SYSTEM_PROMPT;
    if (sentiment === 'angry') {
        dynamicPrompt += "\n- The user seems frustrated. Be extra empathetic, apologize sincerely, offer to escalation if needed.";
    } else if (sentiment === 'happy') {
        dynamicPrompt += "\n- The user seems happy. Be warmer, use light humor.";
    }

    conversationHistory.push({ role: 'user', parts: [{ text: text }] });
    analytics.totalMessages++;
    updateAnalytics();

    // Show Typing and update tick
    setTimeout(() => updateTick(msgId, 'delivered'), 500);

    try {
        updateAgentStatus('typing');
        const reply = await callGemini(conversationHistory, dynamicPrompt);
        
        updateTick(msgId, 'seen');
        retryCount = 0;

        await renderBotBubbles(reply);

        conversationHistory.push({ role: 'model', parts: [{ text: reply }] });
        saveHistory();
        
        // Unread logic
        const widget = document.getElementById('sanza-widget');
        if (widget.style.display !== 'flex') {
            unreadCount++;
            updateUnreadBadge();
        }

        // Auto contextual chips
        autoChips(reply);

    } catch (err) {
        console.error('Sanza error details:', err);
        updateAgentStatus('online');
        hideTyping();

        const errMsg = (err && err.message) ? err.message.toLowerCase() : '';
        if (errMsg.includes('no_api_key') || errMsg.includes('missing')) {
            addBotBubble('Configuration issue — please contact support.');
        } else if (errMsg.includes('timeout') || errMsg.includes('504')) {
            addBotBubble('Taking a bit longer than usual. Please try again!');
        } else if (errMsg.includes('rate limit') || errMsg.includes('429')) {
            addBotBubble('You\'re sending messages too fast. Give me a second! 😊');
        } else {
            handleError(err);
        }
    } finally {
        enableInput();
    }
}

async function renderBotBubbles(text) {
    const bubbles = splitIntoBubbles(text);
    for (let i = 0; i < bubbles.length; i++) {
        const bubbleText = bubbles[i];
        
        // Calculate dynamic typing delay
        const delay = Math.min(500 + bubbleText.length * 18, 4000) + (Math.random() * 400 - 200);
        
        showTyping();
        if (bubbleText.length > 150) {
            setTimeout(() => {
                const label = document.querySelector('.typing-label');
                if (label) label.textContent = "Sanza is still typing...";
            }, 2000);
        }

        await new Promise(r => setTimeout(r, delay));
        hideTyping();
        addBotBubble(bubbleText);
        playNotif();

        if (i < bubbles.length - 1) {
            await new Promise(r => setTimeout(r, 600 + Math.random() * 600));
        }
    }
    updateAgentStatus('online');
}

function splitIntoBubbles(text) {
    const sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
    if (sentences.length <= 2 || text.length < 120) return [text];
    
    const mid = Math.ceil(sentences.length / 2);
    return [
        sentences.slice(0, mid).join(' ').trim(),
        sentences.slice(mid).join(' ').trim()
    ];
}

function updateTick(msgId, status) {
    const el = document.querySelector(`[data-msg-id="${msgId}"] .tick`);
    if (!el) return;
    if (status === 'delivered') el.classList.add('double');
    if (status === 'seen') {
        el.classList.add('double', 'seen');
    }
}

function updateTimestamps() {
    document.querySelectorAll('.msg-time-label').forEach(el => {
        const time = parseInt(el.dataset.time);
        const diff = Math.floor((Date.now() - time) / 60000);
        if (diff === 0) el.textContent = 'just now';
        else el.textContent = `${diff}m ago`;
    });
}

// --- Escalation Flow ---
function startEscalation() {
    isEscalating = true;
    renderBotBubbles("Sure! Let me connect you with one of our team members. Can I get your name first?");
}

function handleEscalation(text) {
    if (!escalationData.name) {
        escalationData.name = text;
        addUserBubble(text, 'e-' + Date.now());
        renderBotBubbles(`Nice to meet you, ${text}. And your email address?`);
    } else if (!escalationData.email) {
        escalationData.email = text;
        addUserBubble(text, 'e-' + Date.now());
        const refId = `#SZ${Date.now().toString().slice(-5)}`;
        renderBotBubbles(`Got it! Our team will reach out to you within 2 hours. Reference ID: ${refId}`);
        
        let escalations = JSON.parse(localStorage.getItem('sanza_escalations')) || [];
        escalations.push({ ...escalationData, refId, timestamp: Date.now() });
        localStorage.setItem('sanza_escalations', JSON.stringify(escalations));
        
        isEscalating = false;
        escalationData = { name: '', email: '' };
    }
}

function handleError(err) {
    retryCount++;
    logError(err);
    
    const msgs = document.getElementById('sanza-messages');
    const div = document.createElement('div');
    div.className = 'error-bubble';
    
    if (retryCount >= 3) {
        div.innerHTML = `Our support is currently unavailable. Please try again later.`;
    } else {
        div.innerHTML = `
            <span>Something went wrong. Let's try again?</span>
            <button class="retry-btn" onclick="retryLastMessage(this)">Retry</button>
        `;
    }
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function retryLastMessage(btn) {
    btn.parentElement.remove();
    sendMessage(lastUserMessage);
}

function logError(err) {
    let errors = JSON.parse(localStorage.getItem('sanza_errors')) || [];
    errors.push({ msg: err.message, time: Date.now() });
    localStorage.setItem('sanza_errors', JSON.stringify(errors.slice(-20)));
}

function showCooldown(seconds) {
    const el = document.getElementById('sanza-cooldown');
    if (!el) return;
    el.style.display = 'block';
    let count = seconds;
    const interval = setInterval(() => {
        el.textContent = `Slow down! You can send more messages in ${count} seconds`;
        count--;
        if (count < 0) {
            clearInterval(interval);
            el.style.display = 'none';
        }
    }, 1000);
}

// --- UI Components ---
function addUserBubble(text, msgId, animate = true) {
    const msgs = document.getElementById('sanza-messages');
    if (!msgs) return;
    const div = document.createElement('div');
    div.className = 'user-msg';
    div.setAttribute('data-msg-id', msgId);
    if (!animate) div.style.animation = 'none';
    div.innerHTML = `
        <div class="user-bubble">${escHtml(text)}</div>
        <div class="msg-meta">
            <span class="msg-time">${getTime()}</span>
            <span class="read-receipt"><span class="tick"></span></span>
        </div>`;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function addBotBubble(text, animate = true) {
    const msgs = document.getElementById('sanza-messages');
    if (!msgs) return;
    const msgId = Date.now() + Math.random();
    const now = Date.now();
    const div = document.createElement('div');
    div.className = 'bot-msg';
    if (!animate) div.style.animation = 'none';
    div.innerHTML = `
        <div class="bot-bubble">${escHtml(text)}</div>
        <div class="msg-meta">
            <span style="font-weight:700;margin-right:4px;">Sanza • </span>
            <span class="msg-time msg-time-label" data-time="${now}">just now</span>
            <button class="thumb" onclick="ratMsg(this, 'up', '${msgId}')">👍</button>
            <button class="thumb" onclick="ratMsg(this, 'down', '${msgId}')">👎</button>
        </div>`;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function ratMsg(btn, type, msgId) {
    const parent = btn.parentElement;
    const buttons = parent.querySelectorAll('.thumb');
    buttons.forEach(b => b.disabled = true);
    
    if (type === 'up') btn.classList.add('active-up');
    else btn.classList.add('active-down');
    
    let feedback = JSON.parse(localStorage.getItem('sanza_feedback')) || [];
    feedback.push({ messageId: msgId, rating: type, timestamp: Date.now() });
    localStorage.setItem('sanza_feedback', JSON.stringify(feedback));
    
    showToast("Thanks for your feedback!");
}

function showTyping() {
    const msgs = document.getElementById('sanza-messages');
    if (!msgs) return;
    const div = document.createElement('div');
    div.id = 'sanza-typing';
    div.className = 'bot-msg';
    div.innerHTML = `
        <div class="typing-bubble">
            <span class="dot"></span>
            <span class="dot"></span>
            <span class="dot"></span>
        </div>
        <small class="typing-label">Sanza is typing...</small>`;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function hideTyping() {
    const el = document.getElementById('sanza-typing');
    if (el) el.remove();
}

function setChips(chipsArray) {
    const wrap = document.getElementById('sanza-chips');
    if (!wrap) return;
    
    // Clear old chips
    wrap.innerHTML = '';
    
    // Add new chips with stagger animation
    chipsArray.forEach((text, i) => {
        const btn = document.createElement('button');
        btn.className = 'sanza-chip';
        btn.textContent = text;
        btn.style.animationDelay = (i * 80) + 'ms';
        btn.addEventListener('click', () => {
            // Clear chips on click
            wrap.innerHTML = '';
            
            analytics.chipClicks[text] = (analytics.chipClicks[text] || 0) + 1;
            updateAnalytics();
            // Send as message
            sendMessage(text);
        });
        wrap.appendChild(btn);
    });
}

window.toggleSanza = function() {
    console.log('toggleSanza called');
    const widget = document.getElementById('sanza-widget');
    const btn = document.getElementById('sanza-toggle');
    if (!widget || !btn) {
        console.error('Sanza elements not found:', { widget: !!widget, btn: !!btn });
        return;
    }
    
    // Check computed style for better reliability
    const isCurrentlyOpen = window.getComputedStyle(widget).display !== 'none';
    
    if (isCurrentlyOpen) {
        widget.style.display = 'none';
        btn.innerHTML = '<span style="font-size:24px">✦</span>';
    } else {
        widget.style.display = 'flex';
        btn.innerHTML = '<span style="font-size:22px">✕</span>';
        unreadCount = 0;
        updateUnreadBadge();
        
        setTimeout(() => {
            const input = document.getElementById('sanza-input');
            if (input) input.focus();
            const msgs = document.getElementById('sanza-messages');
            if (msgs && msgs.children.length === 0) {
                addBotBubble(getGreeting());
                setChips(DEFAULT_CHIPS);
            }
            msgs.scrollTop = msgs.scrollHeight;
        }, 100);
    }
}

// --- Analytics ---
function updateAnalytics() {
    if (analytics.responseTimes.length > 0) {
        analytics.avgResponseTime = analytics.responseTimes.reduce((a, b) => a + b) / analytics.responseTimes.length;
    }
    localStorage.setItem('sanza_analytics', JSON.stringify(analytics));
}

window.getSanzaAnalytics = () => {
    console.table({
        "Total Messages": analytics.totalMessages,
        "Avg Response Time (ms)": Math.round(analytics.avgResponseTime),
        "Session Start": new Date(analytics.sessionStart).toLocaleString()
    });
    console.log("Most Clicked Chips:", analytics.chipClicks);
    return analytics;
};

// --- Utils ---
function getCSRF() {
    const match = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
    return match ? match.split('=')[1].trim() : '';
}

function escHtml(text) {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function getTime() {
    return new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}

function getGreeting() {
    const h = new Date().getHours();
    const greetings = {
        morning: currentLanguage === 'ta' ? 'காலை வணக்கம்! ☀️ இன்று நான் உங்களுக்கு எப்படி உதவ முடியும்?' : 'Good morning! ☀️ How can I help you today?',
        afternoon: currentLanguage === 'ta' ? 'மதிய வணக்கம்! 👋 நான் உங்களுக்காக என்ன செய்ய முடியும்?' : 'Good afternoon! 👋 What can I do for you?',
        evening: currentLanguage === 'ta' ? 'மாலை வணக்கம்! 🌙 நான் உங்களுக்கு எப்படி உதவ முடியும்?' : 'Good evening! 🌙 How can I assist you?',
        night: currentLanguage === 'ta' ? 'வணக்கம்! 🌟 இன்று இரவு நான் உங்களுக்கு எப்படி உதவ முடியும்?' : 'Hi there! 🌟 How can I help you tonight?'
    };
    if (h < 12) return greetings.morning;
    if (h < 17) return greetings.afternoon;
    if (h < 21) return greetings.evening;
    return greetings.night;
}

function splitReply(text) {
    const sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
    if (sentences.length < 2 || text.length < 100) return [text, null];
    const mid = Math.ceil(sentences.length / 2);
    return [sentences.slice(0, mid).join(' ').trim(), sentences.slice(mid).join(' ').trim()];
}

function disableInput() {
    const inp = document.getElementById('sanza-input');
    const btn = document.getElementById('sanza-send');
    if (inp) inp.disabled = true;
    if (btn) btn.disabled = true;
}

function enableInput() {
    const inp = document.getElementById('sanza-input');
    const btn = document.getElementById('sanza-send');
    if (inp) { inp.disabled = false; inp.focus(); }
    if (btn) btn.disabled = false;
}

function clearSanza() {
    conversationHistory = [];
    localStorage.removeItem('sanza_history');
    const msgs = document.getElementById('sanza-messages');
    if (msgs) msgs.innerHTML = '';
    addBotBubble(getGreeting());
    setChips(DEFAULT_CHIPS);
    enableInput();
}

// --- Entry Point ---
function initSanzaToggle() {
    const toggleBtn = document.getElementById('sanza-toggle');
    if (!toggleBtn) {
        console.warn('sanza-toggle not found, retrying...');
        setTimeout(initSanzaToggle, 200);
        return;
    }

    // Standard Toggle behavior
    const newBtn = toggleBtn.cloneNode(true);
    toggleBtn.parentNode.replaceChild(newBtn, toggleBtn);
    
    newBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        toggleSanza();
    });
    console.log('Sanza toggle ready ✓');
}

document.addEventListener('DOMContentLoaded', () => {
    initSanza();
    initSanzaToggle();
    
    const input = document.getElementById('sanza-input');
    const sendBtn = document.getElementById('sanza-send');
    const clearBtn = document.getElementById('sanza-clear');

    if (input) {
        input.addEventListener('input', () => {
            if (input.value.trim() !== '') {
                const wrap = document.getElementById('sanza-chips');
                if (wrap) wrap.innerHTML = '';
            }
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const text = input.value.trim();
                if (text) {
                    input.value = '';
                    sendMessage(text);
                }
            }
        });
    }

    if (sendBtn) sendBtn.onclick = () => {
        const text = input.value.trim();
        if (text) {
            input.value = '';
            sendMessage(text);
        }
    };

    if (clearBtn) clearBtn.onclick = clearSanza;
});

// Backup for slow loads
window.addEventListener('load', initSanzaToggle);

