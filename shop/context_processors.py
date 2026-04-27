from .models import Cart, CartItem

def cart_data(request):
    if request.user.is_authenticated:
        cart, created = Cart.objects.get_or_create(user=request.user)
        items = CartItem.objects.filter(cart=cart)
        count = sum(item.quantity for item in items)
    else:
        items = []
        count = 0

    return {
        'cart_items': items,
        'cart_count': count
    }