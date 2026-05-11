import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'online_shop.settings')
django.setup()

from shop.models import FAQ

faqs = [
    ("How do I track my order?", "You can track your order by clicking the 'Track Order' button in the chat or going to 'My Orders' in your profile. You will see live updates on your shipment."),
    ("What is your return policy?", "We offer a 30-day hassle-free return policy. Items must be in original packaging. You can initiate a return from the 'My Orders' page."),
    ("How can I pay for my order?", "We accept all major Credit/Debit cards, UPI, and NetBanking via Razorpay. Cash on Delivery (COD) is available for eligible pin codes."),
    ("Do you offer free shipping?", "Yes! We offer free standard shipping on all orders above ₹999. For orders below that, a nominal shipping fee of ₹49 applies."),
    ("How long does delivery take?", "Most orders are delivered within 3-5 business days. Express shipping (1-2 days) is available for select metro cities."),
    ("My payment failed but money was deducted.", "Don't worry! This is usually a temporary issue with the bank. The amount will be automatically refunded to your original payment method within 5-7 business days."),
    ("Are your products genuine?", "Absolutely. SanzCart only sources directly from authorized distributors and brands. We guarantee 100% authenticity on all items."),
]

for q, a in faqs:
    FAQ.objects.get_or_create(question=q, defaults={'answer': a, 'is_active': True})

print(f"Seeded {len(faqs)} FAQs successfully.")
