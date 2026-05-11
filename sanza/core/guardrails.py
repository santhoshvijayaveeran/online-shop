BLOCKED_TOPICS = [
    'amazon', 'flipkart', 'snapdeal', 'meesho', 'jiomart', # Competitors
    'porn', 'adult', 'sex', 'naked', # Adult
    'kill', 'murder', 'bomb', 'attack', # Violence
    'hack', 'crack', 'exploit', 'phish', # Hacking
    'drugs', 'illegal', 'stolen' # Illegal
]

def validate_input(message):
    if not message or len(message) < 2:
        return {'valid': False, 'reason': 'too_short'}
    if len(message) > 1000:
        return {'valid': False, 'reason': 'too_long'}
    
    msg_lower = message.lower()
    for topic in BLOCKED_TOPICS:
        if topic in msg_lower:
            return {'valid': False, 'reason': 'blocked_topic'}
            
    return {'valid': True}

def needs_escalation(intent, sentiment):
    if intent == 'payment_issue':
        return True
    if sentiment == 'angry' and intent in ['return_request', 'order_tracking']:
        return True
    return False

def validate_response(response_text):
    hallucination_indicators = ['₹0', '100% off', 'guaranteed same day']
    for indicator in hallucination_indicators:
        if indicator in response_text:
            return "I'm checking the latest information on that for you. One moment please, or could you share your order ID for more specific help?"
    return response_text
