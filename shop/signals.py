from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.contrib.auth.models import User
from .models import Order, Product, Wishlist, Notification, StockNotification, ReturnRequest

@receiver(pre_save, sender=ReturnRequest)
def track_return_status(sender, instance, **kwargs):
    if instance.id:
        try:
            instance._previous_status = ReturnRequest.objects.get(id=instance.id).status
        except ReturnRequest.DoesNotExist:
            instance._previous_status = None
    else:
        instance._previous_status = None

@receiver(post_save, sender=ReturnRequest)
def send_return_notification(sender, instance, created, **kwargs):
    if created:
        Notification.objects.create(
            user=instance.user,
            notification_type='order',
            title='Return Requested 🔄',
            message=f'Your return request for order #{instance.order.id} has been received and is under review.',
            link=reverse('my_orders')
        )
    elif hasattr(instance, '_previous_status') and instance._previous_status != instance.status:
        status_display = instance.get_status_display()
        Notification.objects.create(
            user=instance.user,
            notification_type='order',
            title=f'Return Request {status_display} ✅',
            message=f'Your return request for order #{instance.order.id} has been {status_display}.',
            link=reverse('my_orders')
        )

@receiver(pre_save, sender=Order)
def track_order_status(sender, instance, **kwargs):
    if instance.id:
        try:
            instance._previous_status = Order.objects.get(id=instance.id).status
        except Order.DoesNotExist:
            instance._previous_status = None
    else:
        instance._previous_status = None

@receiver(post_save, sender=Order)
def send_order_notification(sender, instance, created, **kwargs):
    if created:
        Notification.objects.create(
            user=instance.user,
            notification_type='order',
            title='Order Placed! 🛍️',
            message=f'Your order #{instance.id} has been placed successfully. Thank you for shopping!',
            link=reverse('order_tracking', args=[instance.id])
        )
    elif hasattr(instance, '_previous_status') and instance._previous_status != instance.status:
        status_display = instance.get_status_display()
        Notification.objects.create(
            user=instance.user,
            notification_type='order',
            title=f'Order {status_display}! 📦',
            message=f'Your order #{instance.id} status has been updated to {status_display}.',
            link=reverse('order_tracking', args=[instance.id])
        )

@receiver(pre_save, sender=Product)
def track_product_changes(sender, instance, **kwargs):
    if instance.id:
        try:
            old_instance = Product.objects.get(id=instance.id)
            instance._previous_price = old_instance.price
            instance._previous_stock = old_instance.stock
        except Product.DoesNotExist:
            instance._previous_price = None
            instance._previous_stock = 0
    else:
        instance._previous_price = None
        instance._previous_stock = 0

@receiver(post_save, sender=Product)
def send_product_notifications(sender, instance, **kwargs):
    # Price Drop Notification
    if hasattr(instance, '_previous_price') and instance._previous_price and instance.price < instance._previous_price:
        wishlist_users = Wishlist.objects.filter(product=instance).select_related('user')
        for wish in wishlist_users:
            Notification.objects.create(
                user=wish.user,
                notification_type='price_drop',
                title='Price Drop! 📉',
                message=f'Good news! The price of {instance.name} has dropped from ${instance._previous_price} to ${instance.price}.',
                link=instance.get_absolute_url()
            )

    # Restock Notification
    if hasattr(instance, '_previous_stock') and instance._previous_stock == 0 and instance.stock > 0:
        stock_notifs = StockNotification.objects.filter(product=instance, notified=False).select_related('user')
        for sn in stock_notifs:
            Notification.objects.create(
                user=sn.user,
                notification_type='restock',
                title='Back in Stock! ✨',
                message=f'{instance.name} is now back in stock. Shop now before it sells out!',
                link=instance.get_absolute_url()
            )
            sn.notified = True
            sn.save()
