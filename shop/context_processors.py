import os
from django.conf import settings
from .models import Cart, CartItem

def cart_data(request):
    if request.user.is_authenticated:
        try:
            cart, created = Cart.objects.get_or_create(user=request.user)
            items = CartItem.objects.filter(cart=cart).select_related('product')
            count = sum(item.quantity for item in items)
        except Exception:
            items = []
            count = 0
    else:
        items = []
        count = 0
    return {
        'cart_items': items,
        'cart_count': count
    }

def vapid_key(request):
    return {
        'VAPID_PUBLIC_KEY': os.getenv('VAPID_PUBLIC_KEY', '')
    }

def social_links(request):
    return {
        'social_links': getattr(settings, 'SOCIAL_LINKS', {})
    }
