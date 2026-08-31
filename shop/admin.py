from django.contrib import admin
from django.utils.html import format_html
from .models import ProductVariant
from .models import BulkDiscount
from .models import Newsletter, Question, Answer
from .models import (
    Category, Product, Review, Wishlist,
    Profile, Cart, CartItem, Order, OrderItem,
    Coupon, CouponUsage, ChatLog, Notification
)

@admin.register(ChatLog)
class ChatLogAdmin(admin.ModelAdmin):
    list_display = ('session_id', 'user', 'intent_detected', 'satisfaction_score', 'resolved', 'escalated', 'created_at')
    list_filter = ('resolved', 'escalated', 'created_at')
    search_fields = ('session_id', 'user__username', 'intent_detected')
    readonly_fields = ('session_id', 'created_at', 'updated_at')

# ── Basic Models ──────────────────────────────────────────
admin.site.register(Category)
admin.site.register(Profile)
admin.site.register(Cart)
admin.site.register(CartItem)
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(CouponUsage)
admin.site.register(Newsletter)
admin.site.register(Question)
admin.site.register(Answer)
admin.site.register(Notification)

# ── Product Admin ─────────────────────────────────────────
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'price', 'stock', 'is_active', 'category', 'thumbnail', 'total_reviews', 'avg_rating')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'category__name')
    list_editable = ('price', 'stock', 'is_active')
    ordering = ('-id',)

    def thumbnail(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" width="60" height="60" style="border-radius:6px;object-fit:cover;">',
                obj.image.url
            )
        return "No Image"

    def total_reviews(self, obj):
        return obj.reviews.count()

    def avg_rating(self, obj):
        reviews = obj.reviews.all()
        if reviews.exists():
            avg = sum(r.rating for r in reviews) / reviews.count()
            return f"⭐ {round(avg, 1)}"
        return "No ratings"

# ── Review Admin ──────────────────────────────────────────
@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'user', 'rating', 'short_comment', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('user__username', 'product__name', 'comment')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)

    def short_comment(self, obj):
        return obj.comment[:60] + '...' if len(obj.comment) > 60 else obj.comment

# ── Wishlist Admin ────────────────────────────────────────
@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'product', 'added_at')
    list_filter = ('added_at',)
    search_fields = ('user__username', 'product__name')
    ordering = ('-added_at',)

# ── Coupon Admin ──────────────────────────────────────────
@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ['code', 'discount_type', 'discount_value', 'used_count', 'max_uses', 'is_active', 'valid_to']
    list_filter = ['is_active', 'discount_type']
    search_fields = ['code']

class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    fields = ['size', 'color', 'stock', 'price_extra']

# Existing ProductAdmin
class ProductAdmin(admin.ModelAdmin):
    inlines = [ProductVariantInline]
    # ... மற்ற existing fields ...

# admin.py

class BulkDiscountInline(admin.TabularInline):
    model = BulkDiscount
    extra = 1

# ProductAdmin
class ProductAdmin(admin.ModelAdmin):
    inlines = [ProductVariantInline, BulkDiscountInline]