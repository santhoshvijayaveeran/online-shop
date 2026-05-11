import os
import json
import time
import logging
import google.generativeai as genai
from django.conf import settings
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are Sanza, a helpful and friendly AI customer support assistant for SanzCart, an e-commerce platform.
Your goal is to provide accurate, concise, and helpful information to customers.

GUIDELINES:
1. Tone: Professional yet warm and empathetic.
2. Structure: Use clear formatting. If suggesting products, use the 'product_cards' type.
3. Capabilities: You can help with product info, order status, return policies, and general store questions.
4. Human Escalation: If you can't answer or the user is very frustrated, suggest talking to a human agent.
5. Response Format: ALWAYS respond in valid JSON format.

EXAMPLE JSON RESPONSES:

{
  "type": "text",
  "message": "Hello! How can I help you today?",
  "suggested_followups": ["Show me new products", "Check my order"]
}

{
  "type": "product_cards",
  "message": "Here are some products you might like:",
  "products": [
    {"name": "Blue Denim", "price": "1200", "url": "/product/1", "image": "/media/p1.jpg"}
  ],
  "suggested_followups": ["Filter by price", "Contact support"]
}
"""

class GeminiClient:
    def __init__(self):
        # Try different environment variable names
        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('VITE_GEMINI_API_KEY')
        if not api_key:
            logger.error("GEMINI_API_KEY not found in environment")
        
        genai.configure(api_key=api_key)
        # Using gemini-1.5-flash as it's more stable for free tier
        self.model = genai.GenerativeModel(
            model_name='gemini-1.5-flash',
            system_instruction=SYSTEM_PROMPT
        )

    def _build_valid_history(self, messages):
        """Ensures roles alternate between user and model."""
        history = []
        expected_role = 'user'
        for m in messages[:-1]:
            role = m['role']
            if role == 'assistant':
                role = 'model'
            
            # Skip if wrong role order for Gemini
            if role != expected_role:
                continue
                
            content = m['parts']
            if isinstance(content, list):
                content = content[0] if content else ""
            
            if not content:
                continue

            history.append({
                'role': role,
                'parts': [content]
            })
            # Toggle expected role
            expected_role = 'model' if expected_role == 'user' else 'user'
        return history

    def chat(self, messages: list, context: str,
             max_tokens: int = 1000) -> dict:
        try:
            start = time.time()

            # 1. Validate Input
            last_msg = messages[-1]['parts']
            if isinstance(last_msg, list):
                last_msg = last_msg[0] if last_msg else ""
            
            if not last_msg.strip():
                return {
                    'text': json.dumps({
                        'type': 'text',
                        'message': 'Please type a message!',
                        'suggested_followups': []
                    }),
                    'response_time_ms': 0,
                    'tokens_used': 0
                }

            # 2. Build Valid History
            history = self._build_valid_history(messages)

            # 3. Augment with Context
            augmented_query = f"""CONTEXT FROM WEBSITE:
{context}

USER QUESTION:
{last_msg}

Reply in JSON format as per your instructions."""

            # 4. Generate Content
            chat_session = self.model.start_chat(history=history)
            response = chat_session.send_message(augmented_query)

            # 5. Extract text safely
            raw_text = ''
            if hasattr(response, 'text'):
                raw_text = response.text
            elif hasattr(response, 'parts'):
                raw_text = ' '.join(p.text for p in response.parts if hasattr(p, 'text'))

            elapsed = int((time.time() - start) * 1000)
            tokens = 0
            if hasattr(response, 'usage_metadata'):
                tokens = getattr(response.usage_metadata, 'total_token_count', 0)

            print(f"Gemini raw response: {raw_text[:200]}")
            return {
                'text': raw_text,
                'response_time_ms': elapsed,
                'tokens_used': tokens
            }

        except Exception as e:
            import traceback
            print("=" * 50)
            print("GEMINI EXACT ERROR:")
            print(traceback.format_exc())
            print("=" * 50)
            
            # Friendly fallback if quota hit
            friendly_msg = "I'm a bit busy right now. Could you please try again in a minute?"
            if "429" in str(e):
                friendly_msg = "Quota exceeded. Please try again later or wait for a minute."

            return {
                'text': json.dumps({
                    'type': 'text',
                    'message': friendly_msg,
                    'error': str(e),
                    'suggested_followups': ["Retry"]
                }),
                'response_time_ms': 0,
                'tokens_used': 0
            }
