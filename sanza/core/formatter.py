import json, re

def format_response(raw_text: str,
                    retrieved_docs: list) -> dict:
    # Strip markdown code blocks if present
    clean = raw_text.strip()
    clean = re.sub(r'^```json\s*', '', clean)
    clean = re.sub(r'^```\s*', '', clean)
    clean = re.sub(r'\s*```$', '', clean)
    clean = clean.strip()

    # Try full JSON parse
    try:
        parsed = json.loads(clean)
        if isinstance(parsed, dict) and 'message' in parsed:
            return parsed
    except Exception:
        pass

    # Try extracting JSON object from mixed text
    try:
        match = re.search(
            r'\{[^{}]*"message"[^{}]*\}',
            clean, re.DOTALL
        )
        if match:
            parsed = json.loads(match.group())
            if 'message' in parsed:
                return parsed
    except Exception:
        pass

    # Fallback — treat entire response as plain text
    product_docs = [
        d for d in retrieved_docs
        if d.get('type') == 'product'
    ]

    if product_docs and len(product_docs) >= 2:
        return {
            'type': 'product_cards',
            'message': clean,
            'products': [{
                'name': d['name'],
                'price': d['price'],
                'url': d.get('url', ''),
                'image': d.get('image', ''),
            } for d in product_docs[:3]],
            'suggested_followups': []
        }

    return {
        'type': 'text',
        'message': clean,
        'suggested_followups': []
    }

def split_into_bubbles(text):
    if len(text) > 120:
        # Split at sentence boundary near the middle
        sentences = re.split(r'(?<=[.!?]) +', text)
        if len(sentences) > 1:
            mid = len(sentences) // 2
            return [" ".join(sentences[:mid]), " ".join(sentences[mid:])]
    return [text]
