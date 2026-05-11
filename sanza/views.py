import json
import time
import os
import logging
import traceback
import requests as http_requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.conf import settings
from django.db.models import Count, Avg

from sanza.models import Conversation, Message, MessageFeedback, SanzaAnalytics
from sanza.core.intent import IntentAnalyzer
from sanza.core.memory import get_conversation, get_history, save_message
from sanza.core.guardrails import validate_input, needs_escalation

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are Sanza, a friendly and helpful AI customer support agent for SanzCart, an e-commerce platform.
Write like a warm human support agent, not an AI.
- Use casual short sentences. Occasionally use filler words: "sure!", "of course!", "let me check that".
- Never say 'I am an AI'. You are Sanza, a human support agent.
- Use 'we' for the company and 'I' for personal actions.
- End replies with a natural follow-up question when relevant.
"""

def _call_groq(messages, language='en'):
    """Call Groq API and return the reply text."""
    api_key = os.environ.get('GROQ_API_KEY') or getattr(settings, 'GROQ_API_KEY', '')
    if not api_key:
        print("SANZA: GROQ_API_KEY not found!")
        raise ValueError("GROQ_API_KEY missing")

    lang_instruction = 'Tamil' if language == 'ta' else 'English'
    full_messages = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\nLANGUAGE: Respond only in {lang_instruction}."}
    ] + messages

    resp = http_requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        json={
            "model": "llama-3.1-8b-instant",
            "messages": full_messages,
            "temperature": 0.7,
            "max_tokens": 512,
        },
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        timeout=20
    )

    if not resp.ok:
        print(f"SANZA: Groq API error {resp.status_code}: {resp.text[:200]}")
        raise ValueError(f"Groq API error {resp.status_code}: {resp.text[:200]}")

    return resp.json()['choices'][0]['message']['content']

@csrf_exempt
def chat(request):
    """Main Sanza chat endpoint — uses Groq (llama-3.1-8b-instant) as LLM backend."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)

        # Support both sanza/views.py format (message+session_id)
        # AND the sanza.js callGemini format (history+system_prompt+language)
        language = data.get('language', 'en')

        # --- sanza.js sends: {history, system_prompt, language} ---
        if 'history' in data:
            history_raw = data.get('history', [])
            # Convert Gemini-format history to OpenAI format for Groq
            groq_messages = []
            for msg in history_raw:
                role = msg.get('role', '')
                groq_role = 'assistant' if role == 'model' else 'user'
                parts = msg.get('parts', [])
                text = ''
                if isinstance(parts, list) and parts:
                    first = parts[0]
                    text = first.get('text', '') if isinstance(first, dict) else str(first)
                else:
                    text = str(parts)
                text = text.strip()
                if text:
                    groq_messages.append({'role': groq_role, 'content': text})

            if not groq_messages:
                return JsonResponse({'reply': 'Please type a message!'}, status=200)

            start = time.time()
            print(f"SANZA: Calling Groq with {len(groq_messages)} message(s), lang={language}")
            reply = _call_groq(groq_messages, language)
            elapsed = int((time.time() - start) * 1000)
            print(f"SANZA: Groq replied in {elapsed}ms: {reply[:100]}")
            return JsonResponse({'reply': reply})

        # --- Legacy format: {message, session_id} ---
        import uuid
        message = data.get('message', '').strip()
        raw_session = data.get('session_id', '')
        try:
            sanitized_session = str(raw_session).strip('\'" ')
            session_id = str(uuid.UUID(sanitized_session))
        except (ValueError, AttributeError):
            session_id = str(uuid.uuid4())

        # Rate Limiting
        from django.core.cache import cache
        cache_key = f"sanza_ratelimit_{session_id}"
        request_count = cache.get(cache_key, 0)
        if request_count >= 10:
            return JsonResponse({'error': 'Rate limit exceeded. Please wait.', 'type': 'error'}, status=429)
        cache.set(cache_key, request_count + 1, 60)

        # Validate input
        validation = validate_input(message)
        if not validation['valid']:
            return JsonResponse({'error': validation['reason'], 'type': 'error'}, status=400)

        # Conversation management
        conversation = get_conversation(session_id)
        if request.user.is_authenticated:
            conversation.user = request.user
            conversation.save()

        intent = IntentAnalyzer.detect_intent(message)
        language = IntentAnalyzer.detect_language(message)
        conversation.language = language
        conversation.save()
        sentiment = IntentAnalyzer.detect_sentiment(message)
        history = get_history(conversation)

        # Escalation check
        if needs_escalation(intent, sentiment):
            save_message(conversation, 'user', message, intent=intent)
            response_msg = "I understand this is frustrating. I'm connecting you with a human specialist who can help with this issue immediately. One moment..."
            save_message(conversation, 'assistant', response_msg, intent='escalation')
            conversation.is_escalated = True
            conversation.save()
            return JsonResponse({
                'type': 'escalation',
                'message': response_msg,
                'intent': intent,
                'language': language,
                'response_time_ms': 0
            })

        # Build Groq message history
        groq_messages = []
        for h in history:
            role = h.get('role', '')
            groq_role = 'assistant' if role in ('model', 'assistant') else 'user'
            parts = h.get('parts', [])
            text = parts[0] if isinstance(parts, list) and parts else ''
            if isinstance(text, dict):
                text = text.get('text', '')
            if text:
                groq_messages.append({'role': groq_role, 'content': str(text)})
        groq_messages.append({'role': 'user', 'content': message})

        start = time.time()
        print(f"SANZA: Calling Groq (legacy path) with message: {message[:80]}")
        reply = _call_groq(groq_messages, language)
        elapsed = int((time.time() - start) * 1000)
        print(f"SANZA: Groq replied in {elapsed}ms")

        save_message(conversation, 'user', message, intent=intent)
        save_message(conversation, 'assistant', reply, response_time=elapsed)

        return JsonResponse({
            'type': 'text',
            'message': reply,
            'reply': reply,
            'intent': intent,
            'language': language,
            'response_time_ms': elapsed
        })

    except http_requests.Timeout:
        print("SANZA: Groq timeout!")
        return JsonResponse({'error': 'timeout', 'reply': 'Sorry, taking too long. Please try again!'}, status=504)

    except http_requests.ConnectionError as e:
        print(f"SANZA: Connection error: {e}")
        return JsonResponse({'error': 'connection_error', 'reply': 'Connection issue. Please try again!'}, status=503)

    except Exception as e:
        print("SANZA FULL ERROR:")
        print(traceback.format_exc())
        logger.error(f"Chat View Error: {str(e)}\n{traceback.format_exc()}", exc_info=True)
        return JsonResponse({
            'error': str(e),
            'reply': 'Something went wrong. Please try again!',
            'type': 'error'
        }, status=500)

@csrf_exempt
def feedback(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        data = json.loads(request.body)
        message_id = data.get('message_id')
        rating = data.get('rating')
        
        message = Message.objects.get(id=message_id)
        MessageFeedback.objects.update_or_create(message=message, defaults={'rating': rating})
        
        return JsonResponse({'status': 'saved'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

def history(request, session_id):
    try:
        conversation = Conversation.objects.get(session_id=session_id)
        messages = conversation.messages.all().order_by('timestamp')[:50]
        data = []
        for m in messages:
            data.append({
                'role': m.role,
                'content': m.content,
                'timestamp': m.timestamp.isoformat(),
                'intent': m.intent
            })
        return JsonResponse({'messages': data})
    except Conversation.DoesNotExist:
        return JsonResponse({'messages': []})

def analytics(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    total_convs = Conversation.objects.count()
    total_msgs = Message.objects.count()
    avg_res_time = Message.objects.filter(role='assistant').aggregate(Avg('response_time_ms'))['response_time_ms__avg'] or 0
    escalations = Conversation.objects.filter(is_escalated=True).count()
    
    # Top intents
    intents = Message.objects.values('intent').annotate(count=Count('intent')).order_by('-count')[:5]
    top_intents = {i['intent']: i['count'] for i in intents if i['intent']}
    
    # Satisfaction score
    feedbacks = MessageFeedback.objects.all()
    up = feedbacks.filter(rating='up').count()
    down = feedbacks.filter(rating='down').count()
    total_f = up + down
    satisfaction = (up / total_f * 100) if total_f > 0 else 0

    return JsonResponse({
        'total_conversations': total_convs,
        'total_messages': total_msgs,
        'avg_response_time_ms': round(avg_res_time, 2),
        'escalation_rate': round((escalations / total_convs * 100) if total_convs > 0 else 0, 2),
        'top_intents': top_intents,
        'satisfaction_score': round(satisfaction, 2),
        'messages_today': Message.objects.filter(timestamp__date=timezone.now().date()).count(),
        'avg_tokens_per_message': round(Message.objects.aggregate(Avg('tokens_used'))['tokens_used__avg'] or 0, 2)
    })
