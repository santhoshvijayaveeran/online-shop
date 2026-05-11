(function() {
    const generateUUID = () => {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'
            .replace(/[xy]/g, function(c) {
                const r = Math.random() * 16 | 0;
                const v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
    };

    let history = [];
    try {
        history = JSON.parse(localStorage.getItem('sanza_history') || '[]');
    } catch (e) {
        console.warn("Sanza: Failed to parse history", e);
        localStorage.removeItem('sanza_history');
    }

    const storedSession = localStorage.getItem('sanza_session');
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    const isValidSession = storedSession && uuidRegex.test(storedSession);

    const sanzaState = {
        isOpen: false,
        sessionId: isValidSession ? storedSession : generateUUID(),
        language: 'auto',
        isTyping: false,
        messageCount: 0,
        unreadCount: 0,
        lastFailedMessage: null,
        history: history,
        isMuted: localStorage.getItem('sanza_muted') === 'true'
    };

    if (!isValidSession) {
        localStorage.setItem('sanza_session', sanzaState.sessionId);
    }

    localStorage.setItem('sanza_session', sanzaState.sessionId);

    // Audio for notification
    function playNotification() {
        if (sanzaState.isMuted) return;
        try {
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioCtx.createOscillator();
            const gainNode = audioCtx.createGain();
            oscillator.type = 'sine';
            oscillator.frequency.setValueAtTime(520, audioCtx.currentTime);
            gainNode.gain.setValueAtTime(0.1, audioCtx.currentTime);
            oscillator.connect(gainNode);
            gainNode.connect(audioCtx.destination);
            oscillator.start();
            oscillator.stop(audioCtx.currentTime + 0.3);
        } catch (e) { console.warn("Audio play failed", e); }
    }

    function toggleSanza() {
        const widget = document.getElementById('sanza-widget');
        if (!widget) {
            console.error("Sanza: Widget element not found");
            return;
        }
        
        sanzaState.isOpen = !sanzaState.isOpen;
        
        if (sanzaState.isOpen) {
            widget.style.display = 'flex';
            setTimeout(() => { widget.classList.add('open'); }, 10);
            sanzaState.unreadCount = 0;
            updateBadge();
            
            const input = document.getElementById('sanza-input');
            if (input) input.focus();
            
            if (sanzaState.messageCount === 0 && sanzaState.history.length === 0) {
                showGreeting();
            }
        } else {
            widget.classList.remove('open');
            setTimeout(() => { widget.style.display = 'none'; }, 300);
        }
    }

    // Export globally immediately
    window.toggleSanza = toggleSanza;

    function updateBadge() {
        const badge = document.getElementById('sanza-badge');
        if (sanzaState.unreadCount > 0) {
            badge.textContent = sanzaState.unreadCount;
            badge.style.display = 'flex';
        } else {
            badge.style.display = 'none';
        }
    }

    function showGreeting() {
        const hour = new Date().getHours();
        let greeting = "";
        if (sanzaState.history.length > 0) {
            greeting = "Welcome back! 👋 How can I help you today?";
        } else {
            if (hour < 12) greeting = "Good morning! ☀️ How can I help?";
            else if (hour < 17) greeting = "Good afternoon! 👋 What can I do?";
            else greeting = "Good evening! 🌙 How can I assist?";
        }
        appendMessage('assistant', greeting);
    }

    function appendMessage(role, content, type = 'text', extra = {}) {
        const container = document.getElementById('sanza-messages');
        const bubble = document.createElement('div');
        bubble.className = `sanza-bubble ${role}-bubble`;
        
        if (type === 'text') {
            bubble.innerHTML = `<div class="content">${content}</div>`;
        } else if (type === 'product_cards') {
            bubble.innerHTML = `<div class="content">${content}</div><div class="sanza-products-grid"></div>`;
            const grid = bubble.querySelector('.sanza-products-grid');
            extra.products.forEach(p => {
                const card = document.createElement('div');
                card.className = 'sanza-product-card';
                card.innerHTML = `
                    <img src="${p.image || '/static/images/placeholder.png'}" alt="${p.name}">
                    <div class="p-info">
                        <div class="p-name">${p.name}</div>
                        <div class="p-price">₹${p.price}</div>
                        <div class="p-stock ${p.stock > 0 ? 'in' : 'out'}">${p.stock > 0 ? 'In Stock' : 'Out of Stock'}</div>
                        <a href="${p.url}" class="p-btn">View Product</a>
                    </div>
                `;
                grid.appendChild(card);
            });
        } else if (type === 'bullet_list') {
            let listHtml = `<ul>${extra.bullets.map(b => `<li>${b}</li>`).join('')}</ul>`;
            bubble.innerHTML = `<div class="content">${content}${listHtml}</div>`;
        } else if (type === 'escalation') {
            bubble.innerHTML = `
                <div class="content">${content}</div>
                <div class="sanza-escalation-form">
                    <input type="text" id="esc-name" placeholder="Your Name">
                    <input type="email" id="esc-email" placeholder="Your Email">
                    <button id="esc-submit">Submit Details</button>
                </div>
            `;
            setTimeout(() => {
                bubble.querySelector('#esc-submit').onclick = () => {
                    const name = bubble.querySelector('#esc-name').value;
                    const email = bubble.querySelector('#esc-email').value;
                    if (name && email) {
                        const refId = '#SZ' + Date.now().toString().slice(-5);
                        bubble.innerHTML = `<div class="content">Thanks ${name}! A specialist will contact you at ${email}. Reference ID: <b>${refId}</b></div>`;
                        saveEscalation({name, email, refId});
                    }
                };
            }, 100);
        }

        // Feedback icons for bot
        if (role === 'assistant') {
            const feedback = document.createElement('div');
            feedback.className = 'sanza-feedback';
            feedback.innerHTML = `<span class="fb-up">👍</span><span class="fb-down">👎</span>`;
            bubble.appendChild(feedback);
            const msgId = extra.id || Date.now();
            feedback.querySelector('.fb-up').onclick = () => sendFeedback(msgId, 'up', feedback);
            feedback.querySelector('.fb-down').onclick = () => sendFeedback(msgId, 'down', feedback);
        }

        // Ticks for user
        if (role === 'user') {
            const ticks = document.createElement('span');
            ticks.className = 'sanza-ticks';
            ticks.innerHTML = '✓';
            bubble.appendChild(ticks);
            bubble.dataset.ticks = '1';
        }

        container.appendChild(bubble);
        container.scrollTop = container.scrollHeight;
        
        if (role === 'assistant' && !sanzaState.isOpen) {
            sanzaState.unreadCount++;
            updateBadge();
            playNotification();
        }
    }

    async function sendFeedback(id, rating, element) {
        element.style.pointerEvents = 'none';
        element.style.opacity = '0.5';
        showToast("Thanks for your feedback!");
        try {
            await fetch('/api/sanza/feedback/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message_id: id, rating: rating })
            });
        } catch (e) {}
    }

    function showToast(text) {
        const toast = document.createElement('div');
        toast.className = 'sanza-toast';
        toast.textContent = text;
        document.body.appendChild(toast);
        setTimeout(() => toast.classList.add('show'), 10);
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, 2000);
    }

    function showTyping() {
        if (document.getElementById('sanza-typing')) return;
        const container = document.getElementById('sanza-messages');
        const typing = document.createElement('div');
        typing.id = 'sanza-typing';
        typing.className = 'sanza-bubble assistant-bubble typing';
        typing.innerHTML = `<span></span><span></span><span></span>`;
        container.appendChild(typing);
        container.scrollTop = container.scrollHeight;
        
        document.getElementById('sanza-status').textContent = "Typing...";
        
        // Long typing message
        typing.dataset.timer = setTimeout(() => {
            const slow = document.createElement('div');
            slow.className = 'sanza-typing-slow';
            slow.textContent = "Taking a bit longer than usual...";
            typing.appendChild(slow);
        }, 10000);
    }

    function removeTyping() {
        const typing = document.getElementById('sanza-typing');
        if (typing) {
            clearTimeout(typing.dataset.timer);
            typing.remove();
        }
        document.getElementById('sanza-status').textContent = "Online";
    }

    async function sendMessage(text) {
        if (!text || sanzaState.isTyping) return;
        
        // Rate limiting
        if (sanzaState.messageCount >= 10) {
            appendMessage('assistant', "Please wait a moment before sending more messages.");
            return;
        }

        appendMessage('user', text);
        document.getElementById('sanza-input').value = '';
        sanzaState.isTyping = true;
        sanzaState.messageCount++;
        
        // Update ticks to double
        const lastUser = document.querySelector('.user-bubble:last-child .sanza-ticks');
        if (lastUser) lastUser.innerHTML = '✓✓';

        showTyping();
        
        try {
            const start = Date.now();
            const getCookie = (name) => {
                const val = document.cookie.split(';')
                    .find(c => c.trim().startsWith(name + '='));
                return val ? val.split('=')[1] : null;
            };

            const response = await fetch('/api/sanza/chat/', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({ message: text, session_id: sanzaState.sessionId })
            });
            const data = await response.json();
            console.log('Sanza raw response:', data); // debug
            
            // Artificial delay
            const elapsed = Date.now() - start;
            if (elapsed < 800) await new Promise(r => setTimeout(r, 800 - elapsed));
            
            removeTyping();
            
            // Check for error type
            if (data.type === 'error' || data.error) {
                console.error('Sanza API error:', data.error);
                appendMessage('assistant', "Sorry, I'm having trouble right now. Please try again!");
                return;
            }

            // Parse message from response
            const botReply = data.message      // primary field
                || data.text                     // fallback 1
                || data.response                 // fallback 2
                || data.content                  // fallback 3
                || "I couldn't process that. Please try again.";

            // Blue ticks
            if (lastUser) lastUser.style.color = '#2196f3';

            // Render based on type
            switch(data.type) {
                case 'product_cards':
                    appendMessage('assistant', botReply, 'product_cards', { products: data.products });
                    break;
                case 'bullet_list':
                    appendMessage('assistant', botReply, 'bullet_list', { bullets: data.bullets });
                    break;
                case 'escalation':
                    appendMessage('assistant', botReply, 'escalation');
                    break;
                default:
                    // Handle multi-bubble split
                    if (data.bubbles && data.bubbles.length > 1) {
                        for (let i = 0; i < data.bubbles.length; i++) {
                            if (i > 0) showTyping();
                            await new Promise(r => setTimeout(r, 700));
                            if (i > 0) removeTyping();
                            appendMessage('assistant', data.bubbles[i]);
                        }
                    } else {
                        // Original splitting logic as fallback
                        if (botReply.length > 120) {
                            const bubbles = splitText(botReply);
                            appendMessage('assistant', bubbles[0]);
                            if (bubbles[1]) {
                                setTimeout(() => showTyping(), 700);
                                setTimeout(() => {
                                    removeTyping();
                                    appendMessage('assistant', bubbles[1]);
                                    renderChips(data.suggested_followups);
                                }, 2100);
                                return; // Handle chips in setTimeout
                            }
                        } else {
                            appendMessage('assistant', botReply);
                        }
                    }
            }

            // Render suggested followups
            if (data.suggested_followups && data.suggested_followups.length > 0) {
                renderChips(data.suggested_followups);
            }

        } catch (e) {
            removeTyping();
            console.error('Sanza full error:', e);
            appendMessage('assistant', `Network error: ${e.message}. <button class="sanza-retry">Retry</button>`);
            sanzaState.lastFailedMessage = text;
        } finally {
            sanzaState.isTyping = false;
            setTimeout(() => { sanzaState.messageCount = Math.max(0, sanzaState.messageCount - 1); }, 60000);
        }
    }

    function splitText(text) {
        if (text.length <= 120) return [text];
        const sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
        if (sentences.length <= 1) return [text];
        const mid = Math.ceil(sentences.length / 2);
        return [sentences.slice(0, mid).join(' '), sentences.slice(mid).join(' ')];
    }

    function renderChips(chips) {
        const container = document.getElementById('sanza-chips');
        container.innerHTML = '';
        if (!chips) return;
        chips.forEach(text => {
            const chip = document.createElement('button');
            chip.className = 'sanza-chip';
            chip.textContent = text;
            chip.onclick = () => {
                sendMessage(text);
                container.innerHTML = '';
            };
            container.appendChild(chip);
        });
    }

    function saveEscalation(data) {
        const escs = JSON.parse(localStorage.getItem('sanza_escalations') || '[]');
        escs.push(data);
        localStorage.setItem('sanza_escalations', JSON.stringify(escs));
    }

    // Initialization
    window.addEventListener('DOMContentLoaded', () => {
        const toggleBtn = document.getElementById('sanza-toggle');
        if (toggleBtn) {
            toggleBtn.onclick = toggleSanza;
            console.log("Sanza toggle ready ✓");
        }

        const input = document.getElementById('sanza-input');
        if (input) {
            input.onkeydown = (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage(input.value);
                }
            };
        }

        const sendBtn = document.getElementById('sanza-send');
        if (sendBtn) {
            sendBtn.onclick = () => sendMessage(input.value);
        }

        const muteBtn = document.getElementById('sanza-mute');
        if (muteBtn) {
            muteBtn.onclick = () => {
                sanzaState.isMuted = !sanzaState.isMuted;
                localStorage.setItem('sanza_muted', sanzaState.isMuted);
                muteBtn.textContent = sanzaState.isMuted ? '🔇' : '🔊';
            };
        }

        const clearBtn = document.getElementById('sanza-clear');
        if (clearBtn) {
            clearBtn.onclick = () => {
                if (confirm("Clear chat history?")) {
                    document.getElementById('sanza-messages').innerHTML = '';
                    localStorage.removeItem('sanza_history');
                    sanzaState.messageCount = 0;
                    showGreeting();
                }
            };
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && sanzaState.isOpen) toggleSanza();
        });

        console.log("Sanza Advanced Initialization Complete ✓");
        console.log(`Sanza session: ${sanzaState.sessionId}`);
    });

    window.getSanzaAnalytics = () => ({
        ...sanzaState,
        localStorageAnalytics: JSON.parse(localStorage.getItem('sanza_analytics') || '{}')
    });

})();
