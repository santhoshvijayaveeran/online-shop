from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings


def send_welcome_email(user):
    """Sent when a user registers"""
    subject = 'Welcome to Our Shop!'
    message = render_to_string('shop/emails/welcome.html', {
        'username': user.username,
    })
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True,
        html_message=message,
    )


def send_wishlist_email(user, product):
    """Sent when a user adds a product to wishlist"""
    subject = f'❤️ "{product.name}" saved to your Wishlist!'
    message = render_to_string('shop/emails/wishlist.html', {
        'username': user.username,
        'product': product,
    })
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True,
        html_message=message,
    )


def send_review_email(user, product, rating):
    """Sent when a user submits a review"""
    subject = f'⭐ Thanks for reviewing "{product.name}"!'
    message = render_to_string('shop/emails/review.html', {
        'username': user.username,
        'product': product,
        'rating': rating,
    })
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True,
        html_message=message,
    )


def send_order_confirmation_email(user, cart_items, total):
    """Sent when a user places an order"""
    subject = '🛒 Order Confirmation - Thank you for your purchase!'
    message = render_to_string('shop/emails/order_confirmation.html', {
        'username': user.username,
        'cart_items': cart_items,
        'total': total,
    })
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=True,
        html_message=message,
    )