import re

class IntentAnalyzer:
    INTENT_KEYWORDS = {
        'product_search': [
            'show me', 'find', 'looking for', 'do you have',
            'want to buy', 'available', 'paakanum', 'venum',
            'search', 'suggest', 'recommend'
        ],
        'product_comparison': [
            'compare', 'difference', 'vs', 'better than',
            'which one', 'yaar better', 'compare pannu'
        ],
        'order_tracking': [
            'where is my order', 'track', 'delivery status',
            'order status', 'eppo varum', 'order eppo'
        ],
        'return_request': [
            'return', 'refund', 'exchange', 'damaged',
            'wrong item', 'cancel', 'திரும்ப', 'wapas'
        ],
        'payment_issue': [
            'payment failed', 'charged twice', 'not paid',
            'double charge', 'transaction failed', 'money deducted'
        ],
        'shipping_query': [
            'delivery', 'shipping', 'how long', 'free delivery',
            'delivery charge', 'eppo deliver', 'pin code'
        ],
        'offer_inquiry': [
            'offer', 'discount', 'coupon', 'promo code',
            'deal', 'sale', 'cashback', 'free', 'off'
        ],
        'escalation': [
            'manager', 'human', 'real agent', 'complaint',
            'supervisor', 'not happy', 'talk to person'
        ],
        'greeting': [
            'hi', 'hello', 'hey', 'vanakkam', 'good morning',
            'good evening', 'good night', 'start'
        ]
    }

    THANGLISH_KEYWORDS = [
        'pannu', 'venum', 'eppo', 'varum', 'yaar', 'nalla', 'illa', 'iruka'
    ]

    ANGRY_WORDS = [
        'worst', 'bad', 'stupid', 'hate', 'annoying', 'useless', 'cheat', 'fraud'
    ]

    HAPPY_WORDS = [
        'good', 'great', 'thanks', 'happy', 'love', 'nice', 'awesome'
    ]

    @classmethod
    def detect_intent(cls, message):
        message = message.lower()
        scores = {intent: 0 for intent in cls.INTENT_KEYWORDS}
        
        for intent, keywords in cls.INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in message:
                    scores[intent] += 1
        
        max_score = max(scores.values())
        if max_score > 0:
            return max(scores, key=scores.get)
        return 'general'

    @classmethod
    def detect_language(cls, message):
        # Tamil unicode range \u0B80-\u0BFF
        if any('\u0b80' <= char <= '\u0bff' for char in message):
            return 'tamil'
        
        message_lower = message.lower()
        if any(kw in message_lower for kw in cls.THANGLISH_KEYWORDS):
            return 'thanglish'
        
        return 'english'

    @classmethod
    def detect_sentiment(cls, message):
        message = message.lower()
        if any(w in message for w in cls.ANGRY_WORDS):
            return 'angry'
        if any(w in message for w in cls.HAPPY_WORDS):
            return 'happy'
        return 'neutral'
