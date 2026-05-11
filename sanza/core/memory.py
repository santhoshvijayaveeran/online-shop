from sanza.models import Conversation, Message
import uuid

MAX_HISTORY = 10

def get_conversation(session_id):
    if not session_id:
        session_id = str(uuid.uuid4())
    conv, created = Conversation.objects.get_or_create(session_id=session_id)
    return conv

def get_history(conversation):
    messages = conversation.messages.order_by('-timestamp')[:MAX_HISTORY]
    messages = list(reversed(messages))
    
    formatted_history = []
    for msg in messages:
        # map 'assistant' → 'model' for Gemini API
        role = 'model' if msg.role == 'assistant' else msg.role
        formatted_history.append({
            'role': role,
            'parts': [msg.content]
        })
    return formatted_history

def save_message(conversation, role, content, intent=None, context=None, tokens=0, response_time=0):
    return Message.objects.create(
        conversation=conversation,
        role=role,
        content=content,
        intent=intent,
        retrieved_context=context if isinstance(context, list) else [],
        tokens_used=tokens,
        response_time_ms=response_time
    )
