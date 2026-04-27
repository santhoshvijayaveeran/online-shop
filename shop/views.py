from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Avg, Count
from django.contrib.auth.models import User
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import timedelta, date
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
    StockNotification, Question, Answer, Newsletter
)
from .email_utils import (
    send_welcome_email,
    send_wishlist_email,
    send_review_email,
    send_order_confirmation_email
)

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
def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f'Welcome back, {user.username}!')
            return redirect('home')
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'shop/login.html')


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
def search_view(request):
    query = request.GET.get('q', '')
    category = request.GET.get('category', '')
    min_price = request.GET.get('min_price', '')
    max_price = request.GET.get('max_price', '')
    products = Product.objects.all()
    if query:
        products = products.filter(name__icontains=query)
    if category:
        products = products.filter(category__name__icontains=category)
    if min_price:
        products = products.filter(price__gte=min_price)
    if max_price:
        products = products.filter(price__lte=max_price)
    categories = Product.objects.values_list('category__name', flat=True).distinct()
    return render(request, 'shop/search.html', {
        'products': products,
        'query': query,
        'category': category,
        'min_price': min_price,
        'max_price': max_price,
        'categories': categories,
    })


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
    total_products = Product.objects.count()
    total_reviews = Review.objects.count()
    total_wishlists = Wishlist.objects.count()
    total_users = User.objects.count()
    out_of_stock = Product.objects.filter(stock=0)
    low_stock = Product.objects.filter(stock__gt=0, stock__lte=5)
    top_products = Product.objects.annotate(
        avg_rating=Avg('reviews__rating'),
        review_count=Count('reviews')
    ).filter(review_count__gt=0).order_by('-avg_rating')[:5]
    most_wishlisted = Product.objects.annotate(
        wishlist_count=Count('wishlist')
    ).order_by('-wishlist_count')[:5]
    recent_reviews = Review.objects.select_related(
        'user', 'product'
    ).order_by('-created_at')[:10]
    rating_distribution = Review.objects.values('rating').annotate(
        count=Count('rating')
    ).order_by('rating')
    return render(request, 'shop/admin_dashboard.html', {
        'total_products': total_products,
        'total_reviews': total_reviews,
        'total_wishlists': total_wishlists,
        'total_users': total_users,
        'out_of_stock': out_of_stock,
        'low_stock': low_stock,
        'top_products': top_products,
        'most_wishlisted': most_wishlisted,
        'recent_reviews': recent_reviews,
        'rating_distribution': rating_distribution,
    })


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
        tracking_id = request.POST.get('tracking_id', '')
        if new_status in dict(Order.STATUS_CHOICES):
            order.status = new_status
            if tracking_id:
                order.tracking_id = tracking_id
            order.save()
            messages.success(request, f'Order #{order.id} updated to {new_status}.')
    return redirect(request.META.get('HTTP_REFERER', 'admin_dashboard'))


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
    products = Product.objects.all()
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
                    subject='🎉 Welcome to Our Newsletter!',
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
