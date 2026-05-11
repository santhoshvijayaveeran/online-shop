import os
import json
import requests
from django.conf import settings

class SanzCartAI:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        # Using gemini-2.0-flash as requested
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.api_key}"
        
    def generate_response(self, user_msg, context_data=None, chat_history=None, lang='en'):
        if not self.api_key:
            return self._fallback_logic(user_msg, context_data, lang)
            
        system_prompt = self._build_system_prompt(context_data, lang)
        
        # Format history for Gemini (keep last 10 messages for better context)
        contents = []
        if chat_history:
            for msg in chat_history[-10:]:
                role = "user" if msg['sender'] == 'user' else "model"
                contents.append({"role": role, "parts": [{"text": msg['message']}]})
        
        # Add the current user message if not already in history
        if not contents or contents[-1]['parts'][0]['text'] != user_msg:
            contents.append({"role": "user", "parts": [{"text": user_msg}]})
        
        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "temperature": 0.7,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 1024,
                "response_mime_type": "application/json",
            }
        }
        
        try:
            response = requests.post(self.api_url, json=payload, timeout=15)
            response.raise_for_status()
            result = response.json()
            
            ai_output = result['candidates'][0]['content']['parts'][0]['text']
            
            # Clean markdown if present
            if '```json' in ai_output:
                ai_output = ai_output.split('```json')[1].split('```')[0].strip()
            elif '```' in ai_output:
                ai_output = ai_output.split('```')[1].split('```')[0].strip()
                
            parsed_response = json.loads(ai_output)
            
            # Ensure required fields exist
            if 'reply' not in parsed_response:
                parsed_response['reply'] = "I'm here to help! Could you please rephrase that?"
            
            return parsed_response

        except Exception as e:
            import logging
            logging.error(f"SanzCart AI Error: {str(e)}")
            return self._fallback_logic(user_msg, context_data, lang)

    def _build_system_prompt(self, context, lang):
        faqs = context.get('faqs', [])
        # Only take top 8 relevant FAQs to keep prompt concise
        faq_text = "\n".join([f"Q: {f['q']}\nA: {f['a']}" for f in faqs[:8]])
        
        is_tamil = lang == 'ta'
        
        prompt = f"""
        You are the Antigravity AI Support Specialist (GravBot).
        Brand Identity: Modern, gravity-defying, helpful, and technologically advanced.
        Theme: Dark aesthetics with Red accents.
        
        LANGUAGE: Respond EXCLUSIVELY in {"Tamil (using clear, modern Tamil characters)" if is_tamil else "English"}.
        If the user asks in English but language is set to Tamil, respond in Tamil.
        
        CURRENT CUSTOMER CONTEXT:
        - Name: {context.get('username', 'Guest')}
        - Logged In: {context.get('is_logged_in', False)}
        - Recent Order Info: {context.get('latest_order', 'No recent orders found')}
        - Cart Items Count: {context.get('cart_count', 0)}
        
        KNOWLEDGE BASE (Top FAQs):
        {faq_text}
        
        CORE POLICIES:
        1. Returns: 30 days from delivery, item must be in original condition.
        2. Shipping: Free for orders > ₹999, otherwise ₹49 flat fee.
        3. Delivery: Typically 3-5 business days.
        4. Payments: Credit/Debit Cards, UPI, NetBanking, and Cash on Delivery (COD).
        
        INSTRUCTIONS:
        - Be concise but extremely helpful.
        - Use bold text for emphasis on key details (e.g., **Order ID**, **Refund Status**).
        - If a user is frustrated, be more empathetic.
        - If you can't answer from the context, suggest "Talk to Agent".
        - For order tracking queries, always check the USER CONTEXT first. If an Order ID exists, provide the "Track in Detail" link.
        
        OUTPUT FORMAT (Strict JSON):
        {{
            "reply": "Markdown formatted string",
            "category": "Tracking | Product | Shopping | Payment | Returns | Account | General",
            "priority": "low | medium | high",
            "quick_actions": [
                {{
                    "label": "Short Action Name", 
                    "type": "url | intent | action", 
                    "url": "/path/", 
                    "value": "full_intent_text", 
                    "action": "action_name"
                }}
            ]
        }}
        
        QUICK ACTIONS LOGIC:
        - Order Tracking: url: "/order/track/ORDER_ID/"
        - Return Issue: action: "show_ticket_form"
        - Empty Cart: url: "/search/"
        - Product Inquiry: intent: "Tell me more about [Product]"
        """
        return prompt

    def _fallback_logic(self, user_msg, context, lang):
        user_msg = user_msg.lower()
        is_tamil = lang == 'ta' or any(w in user_msg for w in ['வணக்கம்', 'ஆர்டர்', 'பணம்'])
        
        if is_tamil:
            reply = "மன்னிக்கவும், தற்போது என்னால் உங்கள் கோரிக்கையை முழுமையாகப் புரிந்துகொள்ள முடியவில்லை. தயவுசெய்து மீண்டும் முயற்சிக்கவும்."
            if 'ஆர்டர்' in user_msg or 'track' in user_msg:
                reply = f"உங்கள் ஆர்டர் விவரம்: {context.get('latest_order', 'கண்டுபிடிக்க முடியவில்லை')}."
            
            return {
                "reply": reply,
                "category": "General",
                "priority": "medium",
                "quick_actions": [{"label": "உதவி கோரவும்", "type": "action", "action": "show_ticket_form"}]
            }

        # Basic keyword matching for fallback
        if any(k in user_msg for k in ['track', 'where', 'order', 'status']):
            latest = context.get('latest_order', 'None')
            order_id = context.get('latest_order_id')
            if order_id:
                return {
                    "reply": f"Your latest order **{latest}**. You can track it here:",
                    "category": "Tracking",
                    "priority": "medium",
                    "quick_actions": [{"label": "Track Order", "url": f"/order/track/{order_id}/", "type": "url"}]
                }
            
        return {
            "reply": "I'm having a bit of trouble connecting to my brain right now! How else can I help you?",
            "category": "General",
            "priority": "medium",
            "quick_actions": [
                {"label": "Talk to Agent", "type": "action", "action": "show_ticket_form"},
                {"label": "Go to Shop", "url": "/search/", "type": "url"}
            ]
        }


