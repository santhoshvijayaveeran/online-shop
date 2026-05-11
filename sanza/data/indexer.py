import logging
from shop.models import Product, FAQ, ReturnPolicy, ShippingPolicy, Coupon
from sanza.core.embeddings import EmbeddingEngine
from sanza.core.vector_store import VectorStore

logger = logging.getLogger(__name__)

def build_index():
    engine = EmbeddingEngine()
    store = VectorStore()
    
    texts = []
    metadata = []
    
    # 1. Products
    products = Product.objects.filter(is_active=True)
    for p in products:
        rating = p.get_average_rating()
        stock_status = "In Stock" if p.stock > 0 else "Out of Stock"
        text = f"""Product: {p.name}
Category: {p.category.name}
Price: ₹{p.price}
Stock: {stock_status}
Description: {p.description}
Specifications: {getattr(p, 'specifications', 'N/A')}
Rating: {rating}/5
Offers: {getattr(p, 'offers', 'Check coupons for best deals')}"""
        
        texts.append(text)
        metadata.append({
            'type': 'product',
            'id': p.id,
            'name': p.name,
            'price': float(p.price),
            'stock': p.stock,
            'category': p.category.name,
            'url': p.get_absolute_url(),
            'image': p.image.url if p.image else None,
            'content': text
        })

    # 2. FAQs
    faqs = FAQ.objects.filter(is_active=True)
    for f in faqs:
        text = f"Q: {f.question}\nA: {f.answer}"
        texts.append(text)
        metadata.append({
            'type': 'faq',
            'name': f.question,
            'content': text
        })

    # 3. Return Policy
    policies = ReturnPolicy.objects.all()[:1] # Usually only one
    for p in policies:
        text = f"Return Policy: {p.content}"
        texts.append(text)
        metadata.append({
            'type': 'policy',
            'name': 'Return Policy',
            'content': text
        })

    # 4. Shipping Policy
    shipping = ShippingPolicy.objects.all()[:1]
    for s in shipping:
        text = f"Shipping Info: {s.content}"
        texts.append(text)
        metadata.append({
            'type': 'policy',
            'name': 'Shipping Policy',
            'content': text
        })

    # 5. Coupons/Offers
    coupons = Coupon.objects.filter(is_active=True)
    for c in coupons:
        text = f"Offer: {c.code} — {c.discount_value}{'%' if c.discount_type == 'percentage' else ' OFF'} — Min order: ₹{c.min_order_amount}"
        texts.append(text)
        metadata.append({
            'type': 'offer',
            'name': c.code,
            'content': text
        })

    if texts:
        embeddings = engine.embed(texts)
        store.rebuild(embeddings, metadata)
        logger.info(f"Successfully indexed {len(texts)} documents.")
        print(f"Indexed {len(texts)} documents.")
    else:
        logger.warning("No documents found to index.")
        print("No documents found to index.")
