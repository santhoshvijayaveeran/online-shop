import os
from django.conf import settings
from .models import Cart, CartItem, Notification

def notifications(request):
    if request.user.is_authenticated:
        notifs = Notification.objects.filter(user=request.user).order_by('-created_at')[:5]
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    else:
        notifs = []
        unread_count = 0
    return {
        'notifications': notifs,
        'unread_notifications_count': unread_count
    }

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

def chatbot_config(request):
    return {
        'gemini_api_key': settings.GEMINI_API_KEY,
        'GROQ_API_KEY': os.getenv('GROQ_API_KEY', '')
    }
