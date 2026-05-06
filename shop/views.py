import os
import json
import random
import time
from datetime import timedelta, date

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.db.models import Q, Sum, Avg, Count
from django.db.models.functions import TruncDay, TruncMonth
from django.core.mail import send_mail

import razorpay

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
    StockNotification, Question, Answer, Newsletter, PushSubscription
)
from .rate_limit import is_rate_limited, get_client_ip, get_remaining_time



# Razorpay client
razorpay_client = razorpay.Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
)

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

    # Q&A
    questions = Question.objects.filter(
        product=product
    ).select_related('user', 'answer__user').order_by('-created_at')

    return render(request, 'shop/product_detail.html', {
        'product': product,
        'reviews': reviews,
        'avg_rating': avg_rating,
        'user_reviewed': user_reviewed,
        'star_range': range(1, 6),
        'related_products': related_products,
        'bulk_discounts': bulk_discounts,
        'questions': questions,
        'user_purchased': user_purchased,
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


# ---------------- ADMIN DASHBOARD ----------------
@staff_member_required
def admin_dashboard(request):
    today = timezone.now()
    last_30_days = today - timedelta(days=30)
    last_7_days = today - timedelta(days=7)
 
    # ── Summary Cards ──
    total_revenue = Order.objects.filter(
        status='delivered'
    ).aggregate(total=Sum('total_price'))['total'] or 0
 
    total_orders = Order.objects.count()
 
    pending_orders = Order.objects.filter(status='pending').count()
 
    total_products = Product.objects.filter(is_active=True).count()
 
    monthly_revenue = Order.objects.filter(
        status='delivered',
        created_at__gte=last_30_days
    ).aggregate(total=Sum('total_price'))['total'] or 0
 
    # ── Daily Revenue Chart (last 7 days) ──
    daily_revenue = Order.objects.filter(
        created_at__gte=last_7_days,
        status__in=['delivered', 'processing', 'shipped']
    ).annotate(
        day=TruncDay('created_at')
    ).values('day').annotate(
        revenue=Sum('total_price'),
        orders=Count('id')
    ).order_by('day')
 
    chart_labels = []
    chart_revenue = []
    chart_orders = []
 
    for i in range(7):
        day = (today - timedelta(days=6 - i)).date()
        chart_labels.append(day.strftime('%d %b'))
        day_data = next(
            (d for d in daily_revenue if d['day'].date() == day), None
        )
        chart_revenue.append(float(day_data['revenue']) if day_data else 0)
        chart_orders.append(day_data['orders'] if day_data else 0)
 
    # ── Monthly Revenue Chart (last 6 months) ──
    monthly_data = Order.objects.filter(
        status='delivered',
        created_at__gte=today - timedelta(days=180)
    ).annotate(
        month=TruncMonth('created_at')
    ).values('month').annotate(
        revenue=Sum('total_price')
    ).order_by('month')
 
    monthly_labels = [d['month'].strftime('%b %Y') for d in monthly_data]
    monthly_values = [float(d['revenue']) for d in monthly_data]
 
    # ── Top Products ──
    top_products = OrderItem.objects.values(
        'product__name'
    ).annotate(
        total_sold=Sum('quantity'),
        revenue=Sum('price')
    ).order_by('-total_sold')[:5]
 
    top_product_labels = [p['product__name'][:20] for p in top_products]
    top_product_values = [p['total_sold'] for p in top_products]
 
    # ── Orders by Status ──
    status_data = Order.objects.values('status').annotate(
        count=Count('id')
    )
    status_labels = [s['status'].title() for s in status_data]
    status_values = [s['count'] for s in status_data]
 
    # ── Category Sales ──
    category_sales = OrderItem.objects.values(
        'product__category__name'
    ).annotate(
        total=Sum('quantity')
    ).order_by('-total')[:5]
 
    cat_labels = [c['product__category__name'] for c in category_sales]
    cat_values = [c['total'] for c in category_sales]
 
    # ── Recent Orders ──
    recent_orders = Order.objects.select_related(
        'user'
    ).order_by('-created_at')[:10]
 
    # ── Low Stock Products ──
    low_stock = Product.objects.filter(
        stock__lte=5, is_active=True
    ).order_by('stock')[:5]
 
    context = {
        'total_revenue': total_revenue,
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'total_products': total_products,
        'monthly_revenue': monthly_revenue,
 
        'chart_labels': json.dumps(chart_labels),
        'chart_revenue': json.dumps(chart_revenue),
        'chart_orders': json.dumps(chart_orders),
 
        'monthly_labels': json.dumps(monthly_labels),
        'monthly_values': json.dumps(monthly_values),
 
        'top_product_labels': json.dumps(top_product_labels),
        'top_product_values': json.dumps(top_product_values),
 
        'status_labels': json.dumps(status_labels),
        'status_values': json.dumps(status_values),
 
        'cat_labels': json.dumps(cat_labels),
        'cat_values': json.dumps(cat_values),
 
        'recent_orders': recent_orders,
        'low_stock': low_stock,
    }
    return render(request, 'shop/admin_dashboard.html', context)



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
    send_order_confirmation_email(request.user, cart_items, total)
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
@staff_member_required
def update_order_status(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        tracking_id = request.POST.get('tracking_id', '').strip()
        order.status = new_status
        if tracking_id:
            order.tracking_id = tracking_id
        order.save()
        # ✅ இங்க add பண்ணு
        send_push_notification(
            order.user,
            title=f'Order #{order.id} Update',
            body=f'உங்க order status: {new_status}',
            url=f'/order/track/{order.id}/'
        )
        if order.user.email:
            send_mail(
                f'Order #{order.id} Update',
                f'உங்க order status {new_status} ஆச்சு!',
                settings.DEFAULT_FROM_EMAIL,
                [order.user.email]
            )

        messages.success(request, 'Order status updated!')
        return redirect('manage_orders')


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
    products = Product.objects.filter(is_active=True)
    return render(request, 'shop/product_list.html', {'products': products})

# ---------------- ADD PRODUCT (Admin) ----------------
@staff_member_required
def add_product(request):
    categories = Category.objects.all()
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description')
        price = request.POST.get('price')
        stock = request.POST.get('stock')
        category_id = request.POST.get('category')
        image = request.FILES.get('image')

        category = get_object_or_404(Category, id=category_id)

        Product.objects.create(
            name=name,
            description=description,
            price=price,
            stock=stock,
            category=category,
            image=image,
            is_active=True
        )
        messages.success(request, f'Product "{name}" added successfully!')
        return redirect('manage_products')

    return render(request, 'shop/add_product.html', {'categories': categories})


# ---------------- EDIT PRODUCT (Admin) ----------------
@staff_member_required
def edit_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    categories = Category.objects.all()
    old_stock = product.stock

    if request.method == 'POST':
        product.name = request.POST.get('name')
        product.description = request.POST.get('description')
        product.price = request.POST.get('price')
        new_stock = int(request.POST.get('stock', 0))
        product.stock = new_stock
        product.is_active = request.POST.get('is_active') == 'on'
        category_id = request.POST.get('category')
        product.category = get_object_or_404(Category, id=category_id)

        if 'image' in request.FILES:
            product.image = request.FILES['image']

        product.save()

        # Stock back in stock — notify users
        if old_stock == 0 and new_stock > 0:
            send_stock_notifications(product)

        messages.success(request, f'Product "{product.name}" updated!')
        return redirect('manage_products')

    return render(request, 'shop/edit_product.html', {
        'product': product,
        'categories': categories
    })

# ---------------- DELETE PRODUCT (Admin) ----------------
@staff_member_required
def delete_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        name = product.name
        product.delete()
        messages.success(request, f'Product "{name}" deleted!')
    return redirect('manage_products')


# ---------------- MANAGE PRODUCTS (Admin) ----------------

@staff_member_required
def manage_products(request):
    products = Product.objects.select_related('category').order_by('-id')
    categories = Category.objects.all()

    # Filter
    category_filter = request.GET.get('category', '')
    stock_filter = request.GET.get('stock', '')
    search = request.GET.get('q', '')

    if search:
        products = products.filter(name__icontains=search)
    if category_filter:
        products = products.filter(category__id=category_filter)
    if stock_filter == 'out':
        products = products.filter(stock=0)
    elif stock_filter == 'low':
        products = products.filter(stock__gt=0, stock__lte=5)

    return render(request, 'shop/manage_products.html', {
        'products': products,
        'categories': categories,
        'category_filter': category_filter,
        'stock_filter': stock_filter,
        'search': search,
    })


# ---------------- ADD CATEGORY (Admin) ----------------
@staff_member_required
def add_category(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            Category.objects.get_or_create(name=name)
            messages.success(request, f'Category "{name}" added!')
    return redirect('manage_products')

# ---------------- MANAGE ORDERS (Admin) ----------------
@staff_member_required
def manage_orders(request):
    orders = Order.objects.select_related('user').prefetch_related(
        'orderitem_set__product', 'payment'
    ).order_by('-created_at')

    # Filters
    status_filter = request.GET.get('status', '')
    search = request.GET.get('q', '')
    date_filter = request.GET.get('date', '')

    if status_filter:
        orders = orders.filter(status=status_filter)
    if search:
        orders = orders.filter(user__username__icontains=search)
    if date_filter == 'today':
        from django.utils import timezone
        today = timezone.now().date()
        orders = orders.filter(created_at__date=today)
    elif date_filter == 'week':
        from django.utils import timezone
        week_ago = timezone.now() - timedelta(days=7)
        orders = orders.filter(created_at__gte=week_ago)

    # Stats
    total_revenue = sum(o.total_price for o in Order.objects.all())
    pending_count = Order.objects.filter(status='pending').count()
    processing_count = Order.objects.filter(status='processing').count()
    delivered_count = Order.objects.filter(status='delivered').count()

    return render(request, 'shop/manage_orders.html', {
        'orders': orders,
        'status_filter': status_filter,
        'search': search,
        'date_filter': date_filter,
        'total_revenue': total_revenue,
        'pending_count': pending_count,
        'processing_count': processing_count,
        'delivered_count': delivered_count,
        'status_choices': Order.STATUS_CHOICES,
    })


# ---------------- ORDER DETAIL (Admin) ----------------
@staff_member_required
def admin_order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    order_items = OrderItem.objects.filter(order=order).select_related('product')
    return_requests = ReturnRequest.objects.filter(order=order)

    if request.method == 'POST':
        new_status = request.POST.get('status')
        tracking_id = request.POST.get('tracking_id', '')
        note = request.POST.get('note', '')

        if new_status in dict(Order.STATUS_CHOICES):
            order.status = new_status
            if tracking_id:
                order.tracking_id = tracking_id
            order.save()
            messages.success(request, f'Order #{order.id} updated to "{new_status}".')
        return redirect('admin_order_detail', order_id=order.id)

    return render(request, 'shop/admin_order_detail.html', {
        'order': order,
        'order_items': order_items,
        'return_requests': return_requests,
        'status_choices': Order.STATUS_CHOICES,
    })


# ---------------- HANDLE RETURN (Admin) ----------------
@staff_member_required
def handle_return(request, return_id):
    return_req = get_object_or_404(ReturnRequest, id=return_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'approve':
            return_req.status = 'approved'
            messages.success(request, f'Return #{return_id} approved.')
        elif action == 'reject':
            return_req.status = 'rejected'
            messages.success(request, f'Return #{return_id} rejected.')
        elif action == 'complete':
            return_req.status = 'completed'
            messages.success(request, f'Return #{return_id} completed.')
        return_req.save()
    return redirect('admin_order_detail', order_id=return_req.order.id)

# ---------------- MANAGE RETURNS (Admin) ----------------
@staff_member_required
def manage_returns(request):
    returns = ReturnRequest.objects.select_related(
        'user', 'order'
    ).order_by('-created_at')

    status_filter = request.GET.get('status', '')
    if status_filter:
        returns = returns.filter(status=status_filter)

    pending_count = ReturnRequest.objects.filter(status='pending').count()
    approved_count = ReturnRequest.objects.filter(status='approved').count()
    completed_count = ReturnRequest.objects.filter(status='completed').count()
    rejected_count = ReturnRequest.objects.filter(status='rejected').count()

    return render(request, 'shop/manage_returns.html', {
        'returns': returns,
        'status_filter': status_filter,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'completed_count': completed_count,
        'rejected_count': rejected_count,
    })


# ---------------- SALES REPORT (Admin) ----------------
@staff_member_required
def sales_report(request):
    from django.db.models.functions import TruncDate, TruncMonth
    from django.utils import timezone

    period = request.GET.get('period', 'week')

    if period == 'today':
        start_date = timezone.now().replace(hour=0, minute=0, second=0)
    elif period == 'week':
        start_date = timezone.now() - timedelta(days=7)
    elif period == 'month':
        start_date = timezone.now() - timedelta(days=30)
    elif period == 'year':
        start_date = timezone.now() - timedelta(days=365)
    else:
        start_date = timezone.now() - timedelta(days=7)

    # Orders in period
    orders = Order.objects.filter(
        created_at__gte=start_date
    ).exclude(status='cancelled')

    # Daily sales data
    daily_sales = orders.annotate(
        date=TruncDate('created_at')
    ).values('date').annotate(
        revenue=Sum('total_price'),
        count=Count('id')
    ).order_by('date')

    # Top selling products
    top_products = OrderItem.objects.filter(
        order__created_at__gte=start_date
    ).exclude(
        order__status='cancelled'
    ).values(
        'product__name'
    ).annotate(
        total_qty=Sum('quantity'),
        total_revenue=Sum('price')
    ).order_by('-total_qty')[:10]

    # Category wise sales
    category_sales = OrderItem.objects.filter(
        order__created_at__gte=start_date
    ).exclude(
        order__status='cancelled'
    ).values(
        'product__category__name'
    ).annotate(
        total_revenue=Sum('price'),
        total_qty=Sum('quantity')
    ).order_by('-total_revenue')

    # Summary stats
    total_revenue = orders.aggregate(total=Sum('total_price'))['total'] or 0
    total_orders = orders.count()
    avg_order_value = round(total_revenue / total_orders, 2) if total_orders > 0 else 0
    total_items_sold = OrderItem.objects.filter(
        order__in=orders
    ).aggregate(total=Sum('quantity'))['total'] or 0

    # Chart data for JS
    chart_labels = [str(d['date']) for d in daily_sales]
    chart_revenue = [float(d['revenue']) for d in daily_sales]
    chart_orders = [d['count'] for d in daily_sales]

    return render(request, 'shop/sales_report.html', {
        'period': period,
        'total_revenue': total_revenue,
        'total_orders': total_orders,
        'avg_order_value': avg_order_value,
        'total_items_sold': total_items_sold,
        'daily_sales': daily_sales,
        'top_products': top_products,
        'category_sales': category_sales,
        'chart_labels': chart_labels,
        'chart_revenue': chart_revenue,
        'chart_orders': chart_orders,
    })

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


# ---------------- SEND STOCK NOTIFICATIONS ----------------
def send_stock_notifications(product):
    """Call this when product stock is updated"""
    notifications = StockNotification.objects.filter(
        product=product, notified=False
    ).select_related('user')

    for notif in notifications:
        try:
            from django.core.mail import send_mail
            send_mail(
                subject=f'✅ "{product.name}" is back in stock!',
                message=f'Hi {notif.user.username},\n\nGood news! "{product.name}" is now back in stock.\n\nShop now!',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[notif.user.email],
                fail_silently=True,
            )
            notif.notified = True
            notif.save()
        except:
            pass

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
            from django.core.mail import send_mail
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


# ---------------- MANAGE NEWSLETTER (Admin) ----------------
@staff_member_required
def manage_newsletter(request):
    subscribers = Newsletter.objects.filter(
        is_active=True
    ).order_by('-subscribed_at')

    # Send broadcast
    if request.method == 'POST':
        subject = request.POST.get('subject')
        message = request.POST.get('message')
        emails = list(subscribers.values_list('email', flat=True))

        if subject and message and emails:
            from django.core.mail import send_mail
            try:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=emails,
                    fail_silently=True,
                )
                messages.success(request, f'Newsletter sent to {len(emails)} subscribers!')
            except Exception as e:
                messages.error(request, f'Error sending: {str(e)}')
        return redirect('manage_newsletter')

    return render(request, 'shop/manage_newsletter.html', {
        'subscribers': subscribers,
        'total': subscribers.count(),
    })


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

        user = authenticate(request, username=username, password=password)

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
                login(request, user)
                messages.success(request, f'Welcome back, {user.username}!')
                next_url = request.GET.get('next', 'home')
                return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')
            return render(request, 'shop/login.html')

    return render(request, 'shop/login.html')


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
            login(request, user)
            del _otp_store[username]
            del request.session['pending_2fa_user']
            messages.success(request, f'Welcome, {user.username}!')
            return redirect('admin_dashboard')
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

from pywebpush import webpush, WebPushException

VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY')
VAPID_CLAIMS = {"sub": f"mailto:{os.getenv('VAPID_CLAIMS_EMAIL', '')}"}

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

# Send push to one user
def send_push_notification(user, title, body, url='/'):
    subscriptions = PushSubscription.objects.filter(user=user)
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth}
                },
                data=json.dumps({"title": title, "body": body, "url": url}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
        except WebPushException:
            sub.delete()

# Admin Broadcast
def admin_broadcast(request):
    if not request.user.is_staff:
        return redirect('home')
    if request.method == 'POST':
        title = request.POST.get('title')
        body = request.POST.get('body')
        url = request.POST.get('url', '/')
        # Email + Push — எல்லா user-க்கும்
        users = User.objects.filter(is_active=True)
        for user in users:
            send_push_notification(user, title, body, url)
            if user.email:
                send_mail(title, body, settings.DEFAULT_FROM_EMAIL, [user.email])
        messages.success(request, f'{users.count()} users-க்கு notification அனுப்பினோம்!')
        return redirect('admin_broadcast')
    return render(request, 'shop/admin_broadcast.html')

def order_status_api(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return JsonResponse({
        'status': order.status,
        'progress': order.get_status_percentage(),
        'status_display': order.get_status_display(),
        'estimated_delivery': order.estimated_delivery.strftime('%A, %b %d, %Y') if order.estimated_delivery else None,
    })

def notify_back_in_stock(product):
    from .models import StockNotification
    notifications = StockNotification.objects.filter(product=product, notified=False)
    for notif in notifications:
        send_push_notification(
            notif.user,
            title=f'{product.name} Back in Stock!',
            body='உங்களுக்கு பிடிச்ச product திரும்ப வந்துடுச்சு!',
            url=f'/product/{product.id}/'
        )
        if notif.user.email:
            send_mail(
                f'{product.name} is Back!',
                f'{product.name} திரும்ப available ஆச்சு. இப்பவே வாங்குங்க!',
                settings.DEFAULT_FROM_EMAIL,
                [notif.user.email]
            )
        notif.notified = True
        notif.save()
