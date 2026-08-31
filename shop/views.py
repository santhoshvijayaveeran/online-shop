import os
import json
import requests
import random
import time
import logging
from datetime import timedelta, date

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django.db.models import Q, Avg, Count
from django.core.mail import send_mail

import razorpay
from pywebpush import webpush, WebPushException

from .email_utils import (
    send_welcome_email,
    send_wishlist_email,
    send_review_email,
    send_order_confirmation_email
)
from .models import (
    Category, Product, ProductVariant, Review, Wishlist, Cart, CartItem,
    Order, OrderItem, Payment, ReturnRequest,
    Profile, Coupon, CouponUsage, RecentlyViewed, BulkDiscount,
    StockNotification, Question, Answer, Newsletter, PushSubscription,
    SupportTicket, FAQ, ChatSession, ChatMessage, ChatLog, Notification
)

@login_required
def mark_all_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect(request.META.get('HTTP_REFERER', 'home'))

@login_required
def notifications_view(request):
    notifs = Notification.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'shop/notifications.html', {'all_notifications': notifs})

@login_required
def mark_as_read(request, notif_id):
    notif = get_object_or_404(Notification, id=notif_id, user=request.user)
    notif.is_read = True
    notif.save()
    if notif.link:
        return redirect(notif.link)
    return redirect(request.META.get('HTTP_REFERER', 'home'))
from .rate_limit import is_rate_limited, get_client_ip, get_remaining_time
from .ai_assistant import SanzCartAI
from fpdf import FPDF
import io

# ── LOGGING ──
logger = logging.getLogger(__name__)

# ── RAZORPAY CLIENT ──
try:
    razorpay_client = razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )
except Exception as e:
    logger.error(f"Razorpay Client initialization failed: {e}")
    razorpay_client = None

# ── VAPID CONFIG ──
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY')
VAPID_CLAIMS = {"sub": f"mailto:{os.getenv('VAPID_CLAIMS_EMAIL', '')}"}

def get_shipping_charge(total):
    if total >= settings.FREE_SHIPPING_THRESHOLD:
        return 0
    return settings.SHIPPING_CHARGE


# ---------------- HOME ----------------
def home(request):
    products = Product.objects.filter(is_active=True)
    trending = Product.objects.annotate(
        avg_rating=Avg('reviews__rating'),
        review_count=Count('reviews'),
        wishlist_count=Count('wishlist')
    ).order_by('-wishlist_count', '-avg_rating')[:8]
    categories = Product.objects.values_list('category__name', flat=True).distinct()

    # Recently Viewed
    recently_viewed = []
    if request.user.is_authenticated:
        recently_viewed = RecentlyViewed.objects.filter(
            user=request.user
        ).select_related('product').exclude(
            product__id__in=[p.id for p in products[:4]]
        )[:6]

    return render(request, 'shop/home.html', {
        'products': products,
        'trending': trending,
        'categories': categories,
        'recently_viewed': recently_viewed,
    })


# ---------------- ABOUT ----------------
def about(request):
    return render(request, 'shop/about.html')


# ---------------- INFO PAGES ----------------
def info_page(request, slug):
    pages = {
        'faq': {'title': 'Frequently Asked Questions', 'content': '<p>Here you will find answers to the most commonly asked questions about our products, shipping, returns, and more. If you cannot find what you are looking for, please contact our support team.</p><br><strong>How do I track my order?</strong><p>You can track your order by navigating to My Orders or using the Track Order link in the footer.</p><strong>What is your return policy?</strong><p>We offer a 30-day return window for all unused items in their original packaging.</p>'},
        'privacy-policy': {'title': 'Privacy Policy', 'content': '<p>Your privacy is important to us. This Privacy Policy outlines how SANZCART collects, uses, and protects your personal information when you use our website and services.</p><p>We implement security measures to maintain the safety of your personal information. We do not sell or trade your data to third parties.</p>'},
        'terms': {'title': 'Terms of Service', 'content': '<p>Welcome to SANZCART. By using our website, you agree to these Terms of Service. Please read them carefully.</p><p>All content included on this site is the property of SANZCART and protected by copyright laws.</p>'},
        'shipping': {'title': 'Shipping Information', 'content': '<p>We offer standard and expedited shipping options. Standard shipping is free on orders above our designated threshold. Once your order is dispatched, you will receive a tracking number via email.</p>'},
        'returns': {'title': 'Returns & Exchanges', 'content': '<p>If you are not completely satisfied with your purchase, you may return it within 30 days of receipt. Items must be unworn, unwashed, and have original tags attached.</p>'},
        'careers': {'title': 'Careers at SANZCART', 'content': '<p>Join our dynamic team and help us redefine fashion and e-commerce. We are always looking for passionate individuals. Currently, we have open positions in marketing, software engineering, and customer support.</p>'},
    }
    page = pages.get(slug)
    if not page:
        return redirect('home')
    return render(request, 'shop/info_page.html', {'page': page})


# ---------------- CONTACT US ----------------
def contact_us(request):
    if request.method == 'POST':
        messages.success(request, 'Your message has been sent successfully. Our support team will get back to you shortly.')
        return redirect('contact_us')
    return render(request, 'shop/contact.html')


# ---------------- ADD TO CART ----------------
@login_required
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    variant = None
    variant_id = request.POST.get('variant_id') or request.GET.get('variant_id')

    if variant_id:
        variant = get_object_or_404(ProductVariant, id=variant_id, product=product)
        if variant.stock <= 0:
            messages.error(request, f'This variant is out of stock!')
            return redirect(request.META.get('HTTP_REFERER', 'home'))
    else:
        if product.is_out_of_stock():
            messages.error(request, f'"{product.name}" is out of stock!')
            return redirect(request.META.get('HTTP_REFERER', 'home'))

    cart, _ = Cart.objects.get_or_create(user=request.user)
    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        variant=variant,
        defaults={'quantity': 1}
    )

    if not created:
        max_stock = variant.stock if variant else product.stock
        if cart_item.quantity >= max_stock:
            messages.error(request, f'Only {max_stock} items available!')
            return redirect(request.META.get('HTTP_REFERER', 'home'))
        cart_item.quantity += 1
        cart_item.save()

    messages.success(request, f'"{product.name}" added to cart!')
    return redirect(request.META.get('HTTP_REFERER', 'home'))


# ---------------- CART VIEW ----------------
@login_required
def cart_view(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
    cart_items = CartItem.objects.filter(cart=cart).select_related('product')
    total = cart.get_total()
    return render(request, 'shop/cart.html', {
        'cart_items': cart_items,
        'total': total
    })


# ---------------- LOGIN ----------------
# (see user_login below)


# ---------------- LOGOUT ----------------
def logout_view(request):
    logout(request)
    messages.success(request, 'Logged out successfully!')
    return redirect('login')


# ---------------- REGISTER ----------------
def register_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        username = request.POST.get('username')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')
        email = request.POST.get('email')
        if password1 != password2:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'shop/register.html')
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already taken.')
            return render(request, 'shop/register.html')
        user = User.objects.create_user(
            username=username, password=password1, email=email
        )
        send_welcome_email(user)
        messages.success(request, 'Account created! Please login.')
        return redirect('login')
    return render(request, 'shop/register.html')


# ---------------- SEARCH ----------------
def search(request):
    query = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '')
    min_price = request.GET.get('min_price', '')
    max_price = request.GET.get('max_price', '')
    sort = request.GET.get('sort', '')

    products = Product.objects.filter(is_active=True)

    if query:
        products = products.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query) |
            Q(category__name__icontains=query)
        )
    if category_id:
        # category_id may be a numeric PK or a category name/slug string
        try:
            products = products.filter(category_id=int(category_id))
        except (ValueError, TypeError):
            # Fall back to filtering by name or slug
            products = products.filter(
                Q(category__name__iexact=category_id) |
                Q(category__slug__iexact=category_id)
            )
    if min_price:
        products = products.filter(price__gte=min_price)
    if max_price:
        products = products.filter(price__lte=max_price)
    if sort == 'price_low':
        products = products.order_by('price')
    elif sort == 'price_high':
        products = products.order_by('-price')
    elif sort == 'newest':
        products = products.order_by('-id')
    elif sort == 'popular':
        products = products.annotate(avg_rating=Avg('reviews__rating')).order_by('-avg_rating')

    ai_suggestions = None
    if products.count() == 0 and query:
        ai = SanzCartAI()
        ai_res = ai.generate_response(f"The user searched for '{query}' but found no results. Suggest 3 related categories or product types we might have in our high-end fashion/electronics store. Format as a brief helpful message.", context_data={'username': request.user.username if request.user.is_authenticated else 'Guest'})
        ai_suggestions = ai_res.get('reply', '')

    categories = Category.objects.all()
    context = {
        'products': products,
        'query': query,
        'categories': categories,
        'selected_category': category_id,
        'min_price': min_price,
        'max_price': max_price,
        'sort': sort,
        'result_count': products.count(),
        'ai_suggestions': ai_suggestions,
    }
    return render(request, 'shop/search.html', context)


def search_autocomplete(request):
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'results': []})
    products = Product.objects.filter(
        is_active=True, name__icontains=query
    ).values('id', 'name', 'price')[:8]
    categories = Category.objects.filter(
        name__icontains=query
    ).values('id', 'name')[:3]
    return JsonResponse({'products': list(products), 'categories': list(categories)})


def search_suggestions(request):
    popular = Product.objects.filter(
        is_active=True
    ).values_list('name', flat=True)[:6]
    return JsonResponse({'suggestions': list(popular)})


# ---------------- WISHLIST ----------------
@login_required
def wishlist_view(request):
    wishlist_items = Wishlist.objects.filter(user=request.user).select_related('product')
    return render(request, 'shop/wishlist.html', {'wishlist_items': wishlist_items})


@login_required
def add_to_wishlist(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    wishlist_item, created = Wishlist.objects.get_or_create(
        user=request.user, product=product
    )
    if created:
        send_wishlist_email(request.user, product)
        messages.success(request, f'"{product.name}" added to wishlist!')
    else:
        messages.info(request, f'"{product.name}" already in wishlist.')
    return redirect(request.META.get('HTTP_REFERER', 'home'))


@login_required
def remove_from_wishlist(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    Wishlist.objects.filter(user=request.user, product=product).delete()
    messages.success(request, f'"{product.name}" removed from wishlist.')
    return redirect('wishlist')


# ---------------- PRODUCT DETAIL ----------------
def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if request.user.is_authenticated:
        rv, created = RecentlyViewed.objects.get_or_create(
            user=request.user, product=product
        )
        if not created:
            rv.save()
        recent_ids = RecentlyViewed.objects.filter(
            user=request.user
        ).values_list('id', flat=True).order_by('-viewed_at')[:10]
        RecentlyViewed.objects.filter(
            user=request.user
        ).exclude(id__in=recent_ids).delete()

    reviews = Review.objects.filter(product=product).order_by('-created_at')
    avg_rating = reviews.aggregate(avg=Avg('rating'))['avg']
    avg_rating = round(avg_rating, 1) if avg_rating else 0

    user_reviewed = False
    if request.user.is_authenticated:
        user_reviewed = Review.objects.filter(
            user=request.user, product=product
        ).exists()

    
    user_purchased = False
    if request.user.is_authenticated:
        user_purchased = Order.objects.filter(
            user=request.user,
            orderitem__product=product,
            status__in=['delivered','shipped','out_for_delivery']
        ).exists()
    related_products = Product.objects.filter(
        category=product.category
    ).exclude(id=product.id)[:4]

    bulk_discounts = product.bulk_discounts.all()

    # AI Sentiment Mock
    sentiment_score = 90 + (product.id % 10)
    
    return render(request, 'shop/product_detail.html', {
        'product': product,
        'reviews': reviews,
        'avg_rating': avg_rating,
        'user_reviewed': user_reviewed,
        'user_purchased': user_purchased,
        'related_products': related_products,
        'bulk_discounts': bulk_discounts,
        'questions': questions,
        'star_range': range(1, 6),
        'sentiment_score': sentiment_score,
    })


# ---------------- ADD REVIEW ----------------
@login_required
def add_review(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        rating = request.POST.get('rating')
        comment = request.POST.get('comment')
        image = request.FILES.get('review_image')

        if Review.objects.filter(user=request.user, product=product).exists():
            messages.error(request, 'You already reviewed this product.')
            return redirect('product_detail', product_id=product.id)

        Review.objects.create(
            user=request.user,
            product=product,
            rating=rating,
            comment=comment,
            image=image
        )
        send_review_email(request.user, product, rating)
        messages.success(request, 'Review submitted!')
    return redirect('product_detail', product_id=product.id)


# ---------------- DELETE REVIEW ----------------
@login_required
def delete_review(request, review_id):
    review = get_object_or_404(Review, id=review_id, user=request.user)
    product_id = review.product.id
    review.delete()
    messages.success(request, 'Review deleted.')
    return redirect('product_detail', product_id=product_id)


# ---------------- UPDATE CART ----------------
@login_required
def update_cart(request, item_id):
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    if request.method == 'POST':
        quantity = int(request.POST.get('quantity', 1))
        if quantity > 0:
            cart_item.quantity = quantity
            cart_item.save()
    return redirect('cart')


# ---------------- REMOVE FROM CART ----------------
@login_required
def remove_from_cart(request, item_id):
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    cart_item.delete()
    messages.success(request, 'Item removed from cart.')
    return redirect('cart')




# ---------------- CHECKOUT ----------------
@login_required
def checkout(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
    cart_items = CartItem.objects.filter(cart=cart).select_related('product')
    if not cart_items.exists():
        messages.error(request, 'Your cart is empty!')
        return redirect('cart')
    subtotal = cart.get_total()
    shipping = get_shipping_charge(subtotal)
    coupon = None
    discount = 0
    coupon_code = request.session.get('coupon_code')
    if coupon_code:
        try:
            coupon = Coupon.objects.get(code=coupon_code)
            if coupon.is_valid():
                discount = coupon.get_discount_amount(subtotal)
            else:
                del request.session['coupon_code']
                coupon = None
        except Coupon.DoesNotExist:
            del request.session['coupon_code']
    total = subtotal + shipping - discount
    return render(request, 'shop/checkout.html', {
        'cart_items': cart_items,
        'subtotal': subtotal,
        'shipping': shipping,
        'discount': discount,
        'coupon': coupon,
        'total': total,
        'free_shipping_threshold': settings.FREE_SHIPPING_THRESHOLD,
        'razorpay_key': settings.RAZORPAY_KEY_ID,
    })


# ---------------- CREATE RAZORPAY ORDER ----------------
@login_required
def create_payment(request):
    if request.method != 'POST':
        return redirect('checkout')
    cart, _ = Cart.objects.get_or_create(user=request.user)
    cart_items = CartItem.objects.filter(cart=cart).select_related('product')
    if not cart_items.exists():
        messages.error(request, 'Your cart is empty!')
        return redirect('cart')
    subtotal = cart.get_total()
    shipping = get_shipping_charge(subtotal)
    coupon = None
    discount = 0
    coupon_code = request.session.get('coupon_code')
    if coupon_code:
        try:
            coupon = Coupon.objects.get(code=coupon_code)
            if coupon.is_valid():
                discount = coupon.get_discount_amount(subtotal)
        except Coupon.DoesNotExist:
            pass
    total = subtotal + shipping - discount
    order = Order.objects.create(
        user=request.user, total_price=total, status='pending'
    )
    for item in cart_items:
        OrderItem.objects.create(
            order=order, product=item.product,
            quantity=item.quantity, price=item.product.price
        )
    if coupon:
        CouponUsage.objects.get_or_create(coupon=coupon, user=request.user)
        coupon.used_count += 1
        coupon.save()
        del request.session['coupon_code']
    amount_paise = int(total * 100)
    razorpay_order = razorpay_client.order.create({
        'amount': amount_paise,
        'currency': 'INR',
        'payment_capture': 1,
    })
    Payment.objects.create(
        order=order,
        razorpay_order_id=razorpay_order['id'],
        amount=total,
        status='created'
    )
    return render(request, 'shop/payment.html', {
        'order': order,
        'razorpay_order_id': razorpay_order['id'],
        'razorpay_key': settings.RAZORPAY_KEY_ID,
        'amount': amount_paise,
        'total': total,
        'user': request.user,
    })


# ---------------- PAYMENT SUCCESS ----------------
@csrf_exempt
def payment_success(request):
    if request.method == 'POST':
        payment_id = request.POST.get('razorpay_payment_id')
        razorpay_order_id = request.POST.get('razorpay_order_id')
        signature = request.POST.get('razorpay_signature')
        try:
            razorpay_client.utility.verify_payment_signature({
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': payment_id,
                'razorpay_signature': signature,
            })
            payment = Payment.objects.get(razorpay_order_id=razorpay_order_id)
            payment.razorpay_payment_id = payment_id
            payment.razorpay_signature = signature
            payment.status = 'paid'
            payment.save()
            order = payment.order
            order.status = 'processing'
            order.save()
            order_items = OrderItem.objects.filter(order=order)
            for item in order_items:
                product = item.product
                product.stock -= item.quantity
                if product.stock < 0:
                    product.stock = 0
                product.save()
            cart = Cart.objects.get(user=request.user)
            CartItem.objects.filter(cart=cart).delete()
            send_order_confirmation_email(request.user, order_items, order.total_price)
            messages.success(request, f'Payment successful! Order #{order.id} confirmed.')
            return redirect('order_confirmation', order_id=order.id)
        except Exception as e:
            messages.error(request, 'Payment verification failed!')
            return redirect('cart')
    return redirect('home')


# ---------------- PAYMENT FAILED ----------------
def payment_failed(request):
    messages.error(request, 'Payment failed! Please try again.')
    return redirect('cart')


# ---------------- PLACE ORDER (COD) ----------------
@login_required
def place_order(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
    cart_items = CartItem.objects.filter(cart=cart).select_related('product')
    if not cart_items.exists():
        messages.error(request, 'Your cart is empty!')
        return redirect('cart')
    subtotal = cart.get_total()
    shipping = get_shipping_charge(subtotal)
    coupon = None
    discount = 0
    coupon_code = request.session.get('coupon_code')
    if coupon_code:
        try:
            coupon = Coupon.objects.get(code=coupon_code)
            if coupon.is_valid():
                discount = coupon.get_discount_amount(subtotal)
        except Coupon.DoesNotExist:
            pass
    total = subtotal + shipping - discount
    order = Order.objects.create(
        user=request.user, total_price=total, status='pending'
    )
    for item in cart_items:
        OrderItem.objects.create(
            order=order, product=item.product,
            quantity=item.quantity, price=item.product.price
        )
    if coupon:
        CouponUsage.objects.get_or_create(coupon=coupon, user=request.user)
        coupon.used_count += 1
        coupon.save()
        del request.session['coupon_code']
    order_items = OrderItem.objects.filter(order=order)
    try:
        send_order_confirmation_email(request.user, order_items, total)
    except Exception:
        pass

    for item in cart_items:
        product = item.product
        product.stock -= item.quantity
        if product.stock < 0:
            product.stock = 0
        product.save()
    
    cart_items.delete()
    messages.success(request, f'Order #{order.id} placed successfully!')
    return redirect('order_confirmation', order_id=order.id)


# ---------------- ORDER CONFIRMATION ----------------
@login_required
def order_confirmation(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    order_items = OrderItem.objects.filter(order=order).select_related('product')
    return render(request, 'shop/order_confirmation.html', {
        'order': order,
        'order_items': order_items,
    })


# ---------------- MY ORDERS ----------------
@login_required
def my_orders(request):
    orders = Order.objects.filter(user=request.user).prefetch_related(
        'orderitem_set__product', 'returns'
    ).order_by('-created_at')
    return render(request, 'shop/my_orders.html', {'orders': orders})


# ---------------- RETURN REQUEST ----------------
@login_required
def request_return(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return_deadline = order.created_at + timedelta(days=settings.RETURN_WINDOW_DAYS)
    if timezone.now() > return_deadline:
        messages.error(request, f'Return window of {settings.RETURN_WINDOW_DAYS} days has expired.')
        return redirect('my_orders')
    if order.status not in ['delivered', 'processing']:
        messages.error(request, 'Only delivered orders can be returned.')
        return redirect('my_orders')
    if ReturnRequest.objects.filter(order=order).exists():
        messages.info(request, 'Return request already submitted.')
        return redirect('my_orders')
    if request.method == 'POST':
        reason = request.POST.get('reason')
        description = request.POST.get('description', '')
        ReturnRequest.objects.create(
            order=order, user=request.user,
            reason=reason, description=description,
        )
        messages.success(request, 'Return request submitted!')
        return redirect('my_orders')
    return render(request, 'shop/return_request.html', {
        'order': order,
        'return_deadline': return_deadline,
    })


# ---------------- PROFILE ----------------
@login_required
def profile_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    orders = Order.objects.filter(user=request.user).order_by('-created_at')
    total_orders = orders.count()
    total_spent = sum(o.total_price for o in orders)
    wishlist_count = Wishlist.objects.filter(user=request.user).count()
    reviews_count = Review.objects.filter(user=request.user).count()
    return render(request, 'shop/profile.html', {
        'profile': profile,
        'orders': orders[:5],
        'total_orders': total_orders,
        'total_spent': total_spent,
        'wishlist_count': wishlist_count,
        'reviews_count': reviews_count,
    })


# ---------------- EDIT PROFILE ----------------
@login_required
def edit_profile(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        request.user.first_name = request.POST.get('first_name', '')
        request.user.last_name = request.POST.get('last_name', '')
        request.user.email = request.POST.get('email', '')
        request.user.save()
        profile.phone = request.POST.get('phone', '')
        profile.address = request.POST.get('address', '')
        profile.city = request.POST.get('city', '')
        profile.state = request.POST.get('state', '')
        profile.pincode = request.POST.get('pincode', '')
        profile.bio = request.POST.get('bio', '')
        if 'avatar' in request.FILES:
            profile.avatar = request.FILES['avatar']
        profile.save()
        messages.success(request, 'Profile updated successfully!')
        return redirect('profile')
    return render(request, 'shop/edit_profile.html', {'profile': profile})


# ---------------- CHANGE PASSWORD ----------------
@login_required
def change_password(request):
    if request.method == 'POST':
        old_password = request.POST.get('old_password')
        new_password1 = request.POST.get('new_password1')
        new_password2 = request.POST.get('new_password2')
        if not request.user.check_password(old_password):
            messages.error(request, 'Current password is incorrect.')
            return redirect('change_password')
        if new_password1 != new_password2:
            messages.error(request, 'New passwords do not match.')
            return redirect('change_password')
        if len(new_password1) < 6:
            messages.error(request, 'Password must be at least 6 characters.')
            return redirect('change_password')
        request.user.set_password(new_password1)
        request.user.save()
        update_session_auth_hash(request, request.user)
        messages.success(request, 'Password changed successfully!')
        return redirect('profile')
    return render(request, 'shop/change_password.html')


# ---------------- ORDER TRACKING ----------------
@login_required
def order_tracking(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    order_items = OrderItem.objects.filter(order=order).select_related('product')
    status_steps = order.get_status_steps()
    if not order.estimated_delivery:
        order.estimated_delivery = (order.created_at + timedelta(days=5)).date()
        order.save()
    return render(request, 'shop/order_tracking.html', {
        'order': order,
        'order_items': order_items,
        'status_steps': status_steps,
        'progress': order.get_status_percentage(),
	'status_choices': Order.STATUS_CHOICES,
    })


# ---------------- CANCEL ORDER ----------------
@login_required
def cancel_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    if order.status in ['pending', 'processing']:
        order.status = 'cancelled'
        order.save()
        messages.success(request, f'Order #{order.id} cancelled successfully.')
    else:
        messages.error(request, 'Order cannot be cancelled at this stage.')
    return redirect('order_tracking', order_id=order.id)


# ---------------- UPDATE ORDER STATUS (Admin) ----------------


# ---------------- APPLY COUPON ----------------
@login_required
def apply_coupon(request):
    if request.method == 'POST':
        code = request.POST.get('coupon_code', '').strip().upper()
        try:
            coupon = Coupon.objects.get(code=code)
        except Coupon.DoesNotExist:
            messages.error(request, 'Invalid coupon code.')
            return redirect('checkout')
        if not coupon.is_valid():
            messages.error(request, 'This coupon has expired or is no longer valid.')
            return redirect('checkout')
        cart = Cart.objects.get(user=request.user)
        subtotal = cart.get_total()
        if subtotal < coupon.min_order_amount:
            messages.error(request, f'Minimum order amount ₹{coupon.min_order_amount} required.')
            return redirect('checkout')
        if CouponUsage.objects.filter(coupon=coupon, user=request.user).exists():
            messages.error(request, 'You have already used this coupon.')
            return redirect('checkout')
        request.session['coupon_code'] = coupon.code
        discount = coupon.get_discount_amount(subtotal)
        messages.success(request, f'Coupon applied! You saved ₹{discount}.')
        return redirect('checkout')
    return redirect('checkout')


# ---------------- REMOVE COUPON ----------------
@login_required
def remove_coupon(request):
    if 'coupon_code' in request.session:
        del request.session['coupon_code']
        messages.success(request, 'Coupon removed.')
    return redirect('checkout')

def product_list(request):
    return redirect('search')






# ---------------- NOTIFY ME ----------------
@login_required
def notify_me(request, product_id):
    product = get_object_or_404(Product, id=product_id)

    if product.is_in_stock():
        messages.info(request, 'Product is already in stock!')
        return redirect('product_detail', product_id=product.id)

    notif, created = StockNotification.objects.get_or_create(
        user=request.user, product=product
    )

    if created:
        messages.success(request, f'We\'ll notify you when "{product.name}" is back in stock!')
    else:
        messages.info(request, 'You\'re already on the notification list.')

    return redirect('product_detail', product_id=product.id)



# ---------------- ASK QUESTION ----------------
@login_required
def ask_question(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        question_text = request.POST.get('question', '').strip()
        if question_text:
            Question.objects.create(
                product=product,
                user=request.user,
                question=question_text
            )
            messages.success(request, 'Your question has been submitted!')
        else:
            messages.error(request, 'Question cannot be empty.')
    return redirect('product_detail', product_id=product.id)


# ---------------- ANSWER QUESTION ----------------
@login_required
def answer_question(request, question_id):
    question = get_object_or_404(Question, id=question_id)
    if request.method == 'POST':
        answer_text = request.POST.get('answer', '').strip()
        if answer_text:
            Answer.objects.update_or_create(
                question=question,
                defaults={
                    'user': request.user,
                    'answer': answer_text
                }
            )
            messages.success(request, 'Answer submitted!')
    return redirect('product_detail', product_id=question.product.id)


# ---------------- DELETE QUESTION ----------------
@login_required
def delete_question(request, question_id):
    question = get_object_or_404(Question, id=question_id, user=request.user)
    product_id = question.product.id
    question.delete()
    messages.success(request, 'Question deleted.')
    return redirect('product_detail', product_id=product_id)

# ---------------- NEWSLETTER ----------------
def newsletter_subscribe(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()

        if not email:
            messages.error(request, 'Please enter a valid email.')
            return redirect(request.META.get('HTTP_REFERER', 'home'))

        sub, created = Newsletter.objects.get_or_create(email=email)

        if created:
            # Welcome email
            try:
                send_mail(
                    subject='Welcome to Our Newsletter!',
                    message=f'Hi!\n\nThank you for subscribing to our newsletter.\nYou\'ll receive the latest deals and offers.\n\nUnsubscribe anytime at our website.',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=True,
                )
            except:
                pass
            messages.success(request, 'Successfully subscribed! Check your email.')
        else:
            if not sub.is_active:
                sub.is_active = True
                sub.save()
                messages.success(request, 'You\'ve been re-subscribed!')
            else:
                messages.info(request, 'You\'re already subscribed!')

    return redirect(request.META.get('HTTP_REFERER', 'home'))


def newsletter_unsubscribe(request, email):
    try:
        sub = Newsletter.objects.get(email=email)
        sub.is_active = False
        sub.save()
        messages.success(request, 'Successfully unsubscribed.')
    except Newsletter.DoesNotExist:
        messages.error(request, 'Email not found.')
    return redirect('home')




# ── OTP Store (in-memory) ──
_otp_store = {}


def generate_otp():
    return str(random.randint(100000, 999999))


def send_otp_email(email, otp):
    send_mail(
        subject='Your Login OTP - Online Shop',
        message=f'''
Your OTP for login is: {otp}

This OTP is valid for 5 minutes.
Do not share this with anyone.

- Online Shop Team
        ''',
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )



# ── Login View with Rate Limiting ──
@ensure_csrf_cookie
def user_login(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        ip = get_client_ip(request)

        # Rate limiting check
        rate_key = f'login:{ip}:{username}'
        if is_rate_limited(rate_key, max_attempts=5, window=300):
            remaining = get_remaining_time(rate_key)
            minutes = remaining // 60
            seconds = remaining % 60
            messages.error(
                request,
                f'Too many login attempts! Try again in {minutes}m {seconds}s.'
            )
            return render(request, 'shop/login.html', {'locked': True})

        user = authenticate(request, username=username, email=email, password=password)

        if user is not None:
            # Admin-க்கு 2FA
            if user.is_staff:
                otp = generate_otp()
                _otp_store[username] = {
                    'otp': otp,
                    'expires': time.time() + 300,
                    'user_id': user.id,
                }
                try:
                    send_otp_email(user.email, otp)
                    request.session['pending_2fa_user'] = username
                    messages.info(request, f'OTP sent to {user.email[:3]}***@{user.email.split("@")[1]}')
                    return redirect('verify_2fa')
                except Exception:
                    # Email fail-ஆனா console-ல் print பண்ணு (dev mode)
                    print(f'[DEV] OTP for {username}: {otp}')
                    request.session['pending_2fa_user'] = username
                    messages.warning(request, f'[DEV MODE] OTP: {otp}')
                    return redirect('verify_2fa')
            else:
                # Normal user — direct login
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                messages.success(request, f'Welcome back, {user.username}!')
                next_url = request.GET.get('next', 'home')
                return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'shop/login.html')


def send_otp(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        if not email:
            return JsonResponse({'status': 'error', 'message': 'Email is required.'})

        try:
            user = User.objects.get(email=email)
            otp = generate_otp()
            _otp_store[user.username] = {
                'otp': otp,
                'expires': time.time() + 300,
                'user_id': user.id,
            }
            try:
                send_otp_email(email, otp)
            except Exception:
                # Fallback for dev mode
                print(f'[DEV] Login OTP for {email}: {otp}')
            
            return JsonResponse({'status': 'success', 'message': 'OTP sent!'})
        except User.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'User with this email not found.'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request.'})


def otp_login(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        otp = request.POST.get('otp', '').strip()

        try:
            user = User.objects.get(email=email)
            username = user.username
            otp_data = _otp_store.get(username)

            if not otp_data:
                messages.error(request, 'OTP expired or not requested. Please try again.')
                return redirect('login')

            if time.time() > otp_data['expires']:
                del _otp_store[username]
                messages.error(request, 'OTP expired! Please request a new one.')
                return redirect('login')

            if otp == otp_data['otp']:
                del _otp_store[username]
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                messages.success(request, f'Welcome back, {user.username}!')
                return redirect('home')
            else:
                messages.error(request, 'Invalid OTP.')
                return redirect('login')
        except User.DoesNotExist:
            messages.error(request, 'User not found.')
            return redirect('login')

    return redirect('login')


# ── 2FA Verify View ──
def verify_2fa(request):
    username = request.session.get('pending_2fa_user')

    if not username:
        return redirect('login')

    if request.method == 'POST':
        entered_otp = request.POST.get('otp', '').strip()
        ip = get_client_ip(request)

        # OTP rate limiting
        otp_key = f'otp:{ip}:{username}'
        if is_rate_limited(otp_key, max_attempts=5, window=300):
            remaining = get_remaining_time(otp_key)
            messages.error(request, f'Too many OTP attempts! Wait {remaining}s.')
            return render(request, 'shop/verify_2fa.html')

        otp_data = _otp_store.get(username)

        if not otp_data:
            messages.error(request, 'OTP expired. Please login again.')
            return redirect('login')

        if time.time() > otp_data['expires']:
            del _otp_store[username]
            messages.error(request, 'OTP expired! Please login again.')
            return redirect('login')

        if entered_otp == otp_data['otp']:
            user = User.objects.get(id=otp_data['user_id'])
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            del _otp_store[username]
            del request.session['pending_2fa_user']
            messages.success(request, f'Welcome, {user.username}!')
            return redirect('/admin/')
        else:
            messages.error(request, 'Invalid OTP. Try again.')

    return render(request, 'shop/verify_2fa.html')


# ── Resend OTP ──
def resend_otp(request):
    username = request.session.get('pending_2fa_user')
    if not username:
        return redirect('login')

    ip = get_client_ip(request)
    resend_key = f'resend:{ip}:{username}'

    if is_rate_limited(resend_key, max_attempts=3, window=300):
        messages.error(request, 'Too many resend attempts! Wait 5 minutes.')
        return redirect('verify_2fa')

    try:
        user = User.objects.get(username=username)
        otp = generate_otp()
        _otp_store[username] = {
            'otp': otp,
            'expires': time.time() + 300,
            'user_id': user.id,
        }
        send_otp_email(user.email, otp)
        messages.success(request, 'New OTP sent!')
    except Exception:
        print(f'[DEV] New OTP for {username}: {_otp_store[username]["otp"]}')
        messages.warning(request, f'[DEV] OTP resent to console.')

    return redirect('verify_2fa')

# Subscribe endpoint
def save_push_subscription(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        PushSubscription.objects.update_or_create(
            endpoint=data['endpoint'],
            defaults={
                'user': request.user,
                'p256dh': data['keys']['p256dh'],
                'auth': data['keys']['auth'],
            }
        )
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'method not allowed'}, status=405)


def order_status_api(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return JsonResponse({
        'status': order.status,
        'progress': order.get_status_percentage(),
        'status_display': order.get_status_display(),
        'estimated_delivery': order.estimated_delivery.strftime('%A, %b %d, %Y') if order.estimated_delivery else None,
    })

# ---------------- CHATBOT ENGINE ----------------

@csrf_exempt
def chatbot_query(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        user_msg = data.get('message', '').strip()
        lang = data.get('language', 'en')
    except:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not user_msg:
        return JsonResponse({'reply': "I'm listening! How can I assist you today?"})

    # Get or create session
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key
    
    chat_session, created = ChatSession.objects.get_or_create(
        session_key=session_key,
        defaults={'user': request.user if request.user.is_authenticated else None, 'language': lang}
    )
    
    # Sync user and language
    if not created:
        if chat_session.language != lang:
            chat_session.language = lang
            chat_session.save()
        if request.user.is_authenticated and chat_session.user != request.user:
            chat_session.user = request.user
            chat_session.save()
    
    # Get chat history for context (last 15 messages for AI logic)
    history = ChatMessage.objects.filter(session=chat_session).order_by('-timestamp')[:15]
    history_list = [{'sender': m.sender, 'message': m.message} for m in reversed(history)]
    
    # Contextual data for AI
    user = request.user
    latest_order_info = "No recent orders found."
    latest_order_id = None
    cart_count = 0
    if user.is_authenticated:
        latest_order = Order.objects.filter(user=user).order_by('-created_at').first()
        if latest_order:
            latest_order_id = latest_order.id
            latest_order_info = f"Order #{latest_order.id} - Status: {latest_order.get_status_display()} (Placed: {latest_order.created_at.strftime('%Y-%m-%d')})"
        
        cart = Cart.objects.filter(user=user).first()
        if cart:
            cart_count = cart.cartitem_set.count()

    # Get top 10 relevant FAQs
    faqs = FAQ.objects.filter(is_active=True)[:10]
    faq_data = [{'q': f.question, 'a': f.answer} for f in faqs]

    context_data = {
        'username': user.first_name or user.username if user.is_authenticated else 'Guest',
        'latest_order': latest_order_info,
        'latest_order_id': latest_order_id,
        'cart_count': cart_count,
        'is_logged_in': user.is_authenticated,
        'faqs': faq_data
    }

    # Save user message first to ensure it's in history if AI takes long
    ChatMessage.objects.create(session=chat_session, sender='user', message=user_msg)

    # Use AI Assistant
    try:
        ai = SanzCartAI()
        ai_response = ai.generate_response(user_msg, context_data, history_list, lang)
        
        # Save bot response
        ChatMessage.objects.create(session=chat_session, sender='bot', message=ai_response.get('reply', ''))

        return JsonResponse({
            'reply': ai_response.get('reply', ''),
            'quick_actions': ai_response.get('quick_actions', []),
            'category': ai_response.get('category', 'General'),
            'priority': ai_response.get('priority', 'medium')
        })
    except Exception as e:
        logger.error(f"Chatbot View Error: {str(e)}")
        return JsonResponse({
            'reply': "I'm having a brief connection issue. Could you try again in a moment?",
            'category': 'General',
            'priority': 'medium',
            'quick_actions': []
        })

@csrf_exempt
def clear_chatbot_history(request):
    session_key = request.session.session_key
    if session_key:
        ChatSession.objects.filter(session_key=session_key).delete()
    return JsonResponse({'status': 'cleared'})

@csrf_exempt

@login_required
def create_support_ticket(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            subject = data.get('subject', 'Support Request from Chat')
            message = data.get('message', '')
            category = data.get('category', 'General')
            priority = data.get('priority', 'medium')
            order_id = data.get('order_id')
            
            if not message:
                return JsonResponse({'error': 'Message is required'}, status=400)
            
            order = None
            if order_id:
                order = Order.objects.filter(id=order_id, user=request.user).first()

            ticket = SupportTicket.objects.create(
                user=request.user,
                email=request.user.email,
                subject=subject,
                message=message,
                category=category,
                priority=priority,
                order=order
            )
            return JsonResponse({
                'success': True,
                'message': f'Ticket #{ticket.id} created successfully! Our team will contact you soon.'
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    return JsonResponse({'error': 'POST allowed'}, status=405)



 
 
@login_required
def download_invoice(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    
    # Security check
    if order.user != request.user and not request.user.is_staff:
        messages.error(request, "You are not authorized to access this invoice.")
        return redirect('my_orders')

    # Create PDF (A4)
    # fpdf2 allows using a unicode-capable font if we have one, but we'll use helvetica 
    # and "Rs." for maximum compatibility unless we can get the symbol to work.
    # We'll try to use the symbol but fallback if needed.
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margin(0)
    pdf.add_page()
    pdf.alias_nb_pages()

    # Colors
    c_dark = (26, 26, 26)      # #1a1a1a
    c_red = (230, 57, 70)       # #e63946
    c_bg = (247, 244, 239)      # #f7f4ef
    c_border = (232, 228, 222)  # #e8e4de
    c_muted = (154, 149, 144)   # #9a9590
    c_white = (255, 255, 255)

    # --- SECTION 1: HEADER BAR ---
    pdf.set_fill_color(*c_dark)
    pdf.rect(0, 0, 210, 35, "F")
    
    # Logo
    pdf.set_xy(15, 10)
    pdf.set_font("helvetica", "B", 26)
    pdf.set_text_color(*c_white)
    pdf.cell(pdf.get_string_width("SANZ"), 12, "SANZ", ln=0)
    pdf.set_text_color(*c_red)
    pdf.cell(50, 12, "CART", ln=0)
    
    pdf.set_xy(15, 22)
    pdf.set_font("helvetica", "", 8)
    pdf.set_text_color(*c_muted)
    pdf.cell(0, 5, "PREMIUM FASHION & LIFESTYLE", ln=0)
    
    # Invoice Title
    pdf.set_xy(0, 10)
    pdf.set_font("helvetica", "B", 18)
    pdf.set_text_color(*c_white)
    pdf.cell(195, 12, "INVOICE", ln=1, align="R")
    
    pdf.set_xy(0, 21)
    pdf.set_font("helvetica", "B", 11)
    pdf.set_text_color(*c_red)
    pdf.cell(195, 5, f"NO: SC-{order.id:05d}", ln=1, align="R")

    # --- SECTION 2: STATUS BADGE ---
    pdf.set_y(42)
    status_colors = {
        'delivered': (34, 197, 94),   # Green
        'processing': (245, 158, 11), # Orange
        'cancelled': (230, 57, 70),  # Red
        'pending': (154, 149, 144),   # Gray
        'shipped': (59, 130, 246),    # Blue
    }
    status_bg = status_colors.get(order.status, (154, 149, 144))
    
    pdf.set_fill_color(*status_bg)
    # Draw pill badge
    # fpdf2 rect supports round_corners as radius in mm
    pdf.rect(160, 42, 35, 7, "F")
    
    pdf.set_xy(160, 42)
    pdf.set_font("helvetica", "B", 7)
    pdf.set_text_color(*c_white)
    pdf.cell(35, 7, f" {order.status.upper()}", align="C")

    # --- SECTION 3: INFO CARDS ---
    pdf.set_y(58)
    
    # Card background boxes
    pdf.set_fill_color(*c_bg)
    pdf.rect(15, 58, 87, 40, "F")
    pdf.rect(108, 58, 87, 40, "F")
    
    # Left Card: Billed To
    pdf.set_xy(20, 62)
    pdf.set_font("helvetica", "B", 7)
    pdf.set_text_color(*c_red)
    pdf.cell(75, 4, "BILLED TO", ln=1)
    
    pdf.set_x(20)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*c_dark)
    pdf.cell(75, 6, f"{order.user.get_full_name() or order.user.username}".upper(), ln=1)
    
    pdf.set_font("helvetica", "", 8)
    pdf.set_text_color(*c_muted)
    pdf.set_x(20)
    pdf.cell(75, 4, f"{order.user.email}", ln=1)
    
    if hasattr(order.user, 'profile') and order.user.profile.phone:
        pdf.set_x(20)
        pdf.cell(75, 4, f"Ph: {order.user.profile.phone}", ln=1)
    
    if order.shipping_address:
        pdf.set_x(20)
        pdf.multi_cell(75, 3.5, f"Address: {order.shipping_address}", border=0)
        
    # Right Card: Order Info
    pdf.set_xy(113, 62)
    pdf.set_font("helvetica", "B", 7)
    pdf.set_text_color(*c_red)
    pdf.cell(75, 4, "ORDER INFORMATION", ln=1)
    
    pdf.set_font("helvetica", "B", 9)
    pdf.set_text_color(*c_dark)
    pdf.set_x(113)
    pdf.cell(35, 6, "Order ID:", ln=0)
    pdf.cell(42, 6, f"#{order.id}", ln=1, align="R")
    
    pdf.set_font("helvetica", "", 8)
    pdf.set_text_color(*c_muted)
    pdf.set_x(113)
    pdf.cell(35, 4, "Order Date:", ln=0)
    pdf.cell(42, 4, f"{order.created_at.strftime('%d %b %Y')}", ln=1, align="R")
    
    pdf.set_x(113)
    pdf.cell(35, 4, "Payment Method:", ln=0)
    pdf.cell(42, 4, "Prepaid / Razorpay", ln=1, align="R")
    
    if order.estimated_delivery:
        pdf.set_x(113)
        pdf.cell(35, 4, "Delivery Est:", ln=0)
        pdf.cell(42, 4, f"{order.estimated_delivery.strftime('%d %b %Y')}", ln=1, align="R")

    # --- SECTION 4: DIVIDER ---
    pdf.set_y(105)
    pdf.set_draw_color(*c_red)
    pdf.set_line_width(0.3)
    pdf.line(15, 105, 195, 105)
    
    # --- SECTION 5: ITEMS TABLE ---
    pdf.set_y(112)
    
    # Header
    pdf.set_fill_color(*c_dark)
    pdf.set_text_color(*c_white)
    pdf.set_font("helvetica", "B", 8)
    
    pdf.set_x(15)
    pdf.cell(10, 10, "#", border=0, fill=True, align="C")
    pdf.cell(90, 10, "  PRODUCT DETAILS", border=0, fill=True)
    pdf.cell(25, 10, "PRICE", border=0, fill=True, align="C")
    pdf.cell(20, 10, "QTY", border=0, fill=True, align="C")
    pdf.cell(35, 10, "SUBTOTAL  ", border=0, fill=True, align="R")
    pdf.ln()
    
    # Rows
    pdf.set_text_color(*c_dark)
    pdf.set_font("helvetica", "", 8)
    
    items = order.orderitem_set.all()
    for i, item in enumerate(items, 1):
        bg = c_bg if i % 2 == 0 else c_white
        pdf.set_fill_color(*bg)
        
        pdf.set_x(15)
        # We use a rect for the row background to have more control
        curr_y = pdf.get_y()
        pdf.rect(15, curr_y, 180, 10, "F")
        
        pdf.cell(10, 10, str(i), align="C")
        pdf.set_font("helvetica", "B", 8)
        pdf.cell(90, 10, f"  {item.product.name}")
        pdf.set_font("helvetica", "", 8)
        pdf.cell(25, 10, f"Rs. {item.price}", align="C")
        pdf.cell(20, 10, str(item.quantity), align="C")
        pdf.cell(35, 10, f"Rs. {item.get_subtotal()}  ", align="R")
        pdf.ln()
        
        # Row bottom divider
        pdf.set_draw_color(*c_border)
        pdf.set_line_width(0.1)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())

    # --- SECTION 6: TOTALS BOX ---
    pdf.ln(5)
    pdf.set_x(130)
    pdf.set_fill_color(*c_bg)
    pdf.rect(130, pdf.get_y(), 65, 30, "F")
    
    pdf.set_font("helvetica", "", 8)
    pdf.set_text_color(*c_muted)
    
    curr_total_y = pdf.get_y() + 2
    pdf.set_xy(135, curr_total_y)
    pdf.cell(30, 6, "Subtotal:", ln=0)
    pdf.cell(25, 6, f"Rs. {order.get_total()}", ln=1, align="R")
    
    items_total = order.get_total()
    shipping = order.total_price - items_total
    if shipping > 0:
        pdf.set_x(135)
        pdf.cell(30, 6, "Shipping:", ln=0)
        pdf.cell(25, 6, f"Rs. {shipping}", ln=1, align="R")
    
    pdf.set_draw_color(*c_border)
    pdf.line(135, pdf.get_y() + 1, 190, pdf.get_y() + 1)
    pdf.ln(3)
    
    pdf.set_x(135)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*c_red)
    pdf.cell(30, 8, "TOTAL AMOUNT:", ln=0)
    pdf.cell(25, 8, f"Rs. {order.total_price}", ln=1, align="R")

    # --- SECTION 7: THANK YOU BANNER ---
    pdf.set_y(-45)
    pdf.set_fill_color(*c_red)
    pdf.rect(0, pdf.get_y(), 210, 18, "F")
    
    pdf.set_y(pdf.get_y() + 3)
    pdf.set_font("helvetica", "B", 10)
    pdf.set_text_color(*c_white)
    pdf.cell(0, 6, "Thank you for shopping with SanzCart! ", ln=1, align="C")
    
    pdf.set_font("helvetica", "", 7)
    pdf.cell(0, 4, "For support: support@sanzcart.com  |  1800-SANZ-001", ln=1, align="C")

    # --- SECTION 8: FOOTER ---
    pdf.set_y(-18)
    pdf.set_fill_color(*c_bg)
    pdf.rect(0, 279, 210, 18, "F")
    
    pdf.set_y(283)
    pdf.set_font("helvetica", "", 6)
    pdf.set_text_color(*c_muted)
    
    pdf.set_x(15)
    pdf.cell(50, 4, "SANZCART PREMIUM LIFESTYLE", ln=0)
    pdf.cell(80, 4, "This is a computer-generated invoice. No signature required.", ln=0, align="C")
    pdf.cell(50, 4, f"Page {pdf.page_no()} of {{nb}}", ln=1, align="R")

    # Output
    # In fpdf2, output() without arguments returns bytes or bytearray
    try:
        pdf_bytes = pdf.output()
        if isinstance(pdf_bytes, bytearray):
            pdf_bytes = bytes(pdf_bytes)
        
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Invoice_SC_{order.id}.pdf"'
        return response
    except Exception as e:
        # Fallback to simple PDF if premium fails
        print(f"Premium PDF Error: {e}")
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("helvetica", "B", 16)
        pdf.cell(0, 10, f"Invoice SC-{order.id}", ln=1)
        pdf.set_font("helvetica", "", 12)
        pdf.cell(0, 10, f"Order Status: {order.status}", ln=1)
        pdf.cell(0, 10, f"Total: Rs. {order.total_price}", ln=1)
        pdf_bytes = bytes(pdf.output())
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Invoice_SC_{order.id}.pdf"'
        return response


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI CHATBOT APIs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@login_required
def order_status_api(request, order_id):
    try:
        order = Order.objects.get(id=order_id, user=request.user)
        items = [{
            'name': item.product.name,
            'quantity': item.quantity,
            'price': float(item.price)
        } for item in order.orderitem_set.all()]
        
        return JsonResponse({
            'order_id': order.id,
            'status': order.get_status_display(),
            'items': items,
            'placed_on': str(order.created_at),
            'expected_delivery': str(order.estimated_delivery) if order.estimated_delivery else "Processing",
            'tracking_number': order.tracking_id or "Not assigned",
            'courier': "SanzCart Express"
        })
    except Order.DoesNotExist:
        return JsonResponse({'error': 'Order not found'}, status=404)

@login_required
def my_orders_api(request):
    orders = Order.objects.filter(user=request.user).order_by('-created_at')[:5]
    data = [{
        'id': o.id,
        'status': o.get_status_display(),
        'total': float(o.total_price),
        'date': o.created_at.strftime('%Y-%m-%d')
    } for o in orders]
    return JsonResponse({'orders': data})

@csrf_exempt
def verify_order_api(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        order_id = data.get('order_id')
        email = data.get('email')
        try:
            order = Order.objects.get(id=order_id, user__email=email)
            return JsonResponse({'status': 'verified', 'order_id': order.id})
        except Order.DoesNotExist:
            return JsonResponse({'status': 'failed', 'message': 'Invalid Order ID or Email'}, status=400)
    return JsonResponse({'error': 'Invalid request'}, status=400)

def product_search_api(request):
    q = request.GET.get('q', '')
    products = Product.objects.filter(
        name__icontains=q, is_active=True
    ).values(
        'name', 'price', 'stock'
    )[:5]
    # Add rating and discount mock for now as they aren't directly in model as fields but methods
    product_list = []
    for p in products:
        # Get actual product object for methods
        obj = Product.objects.get(name=p['name'])
        p['rating'] = obj.get_average_rating()
        p['discount'] = "10% Off" # Mock or fetch from BulkDiscount
        product_list.append(p)
    return JsonResponse({'products': product_list})

def active_offers_api(request):
    now = timezone.now()
    offers = Coupon.objects.filter(
        is_active=True,
        valid_to__gte=now
    ).values(
        'code', 'discount_value', 'min_order_amount', 'valid_to'
    )
    return JsonResponse({'offers': list(offers)})

@login_required
def return_status_api(request, order_id):
    try:
        ret = ReturnRequest.objects.get(order_id=order_id, user=request.user)
        return JsonResponse({
            'status': ret.get_status_display(),
            'reason': ret.get_reason_display(),
            'created_at': str(ret.created_at),
            'refund_date': "7 days after approval"
        })
    except ReturnRequest.DoesNotExist:
        return JsonResponse({'error': 'No return request found for this order'}, status=404)

@csrf_exempt
@login_required
def create_return_api(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        order_id = data.get('order_id')
        reason = data.get('reason')
        description = data.get('description', '')
        try:
            order = Order.objects.get(id=order_id, user=request.user)
            if ReturnRequest.objects.filter(order=order).exists():
                return JsonResponse({'error': 'Return already requested'}, status=400)
            
            ReturnRequest.objects.create(
                order=order, user=request.user,
                reason=reason, description=description
            )
            return JsonResponse({'status': 'success', 'message': 'Return request submitted'})
        except Order.DoesNotExist:
            return JsonResponse({'error': 'Order not found'}, status=404)
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
def log_chat_api(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        import uuid
        ChatLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_id=data.get('session_id', uuid.uuid4()),
            messages=data.get('messages', []),
            intent_detected=data.get('intent', ''),
            satisfaction_score=data.get('score', 0),
            resolved=data.get('resolved', False),
            escalated=data.get('escalated', False)
        )
        return JsonResponse({'status': 'logged'})
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
def sanza_chat_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    try:
        body = json.loads(request.body)
        history = body.get('history', [])
        language = body.get('language', 'en')
        system_prompt = body.get('system_prompt', 'You are Sanza, a friendly customer support agent at SanzCart.')

        # Groq API Configuration
        api_key = os.environ.get('GROQ_API_KEY') or getattr(settings, 'GROQ_API_KEY', '')
        if not api_key:
            return JsonResponse({'error': 'GROQ_API_KEY missing'}, status=500)

        # Build messages for Groq (OpenAI format)
        messages = [{"role": "system", "content": f"{system_prompt}\nLANGUAGE: Respond only in {'Tamil' if language == 'ta' else 'English'}."}]
        
        for msg in history:
            role = msg.get('role', '')
            # Map 'model' to 'assistant' for Groq/OpenAI compatibility
            groq_role = 'assistant' if role == 'model' else 'user'
            text = msg.get('parts', [{}])[0].get('text', '').strip()
            if text:
                messages.append({"role": groq_role, "content": text})

        url = "https://api.groq.com/openai/v1/chat/completions"
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 512,
            "top_p": 1
        }

        resp = requests.post(
            url, 
            json=payload, 
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=20
        )
        
        if not resp.ok:
            return JsonResponse({'error': f'Groq Error: {resp.text}'}, status=resp.status_code)

        resp_json = resp.json()
        reply = resp_json['choices'][0]['message']['content']

        return JsonResponse({'reply': reply})

    except requests.Timeout:
        return JsonResponse({'error': 'Groq timeout'}, status=504)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

