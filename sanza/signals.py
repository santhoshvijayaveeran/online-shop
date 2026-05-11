import threading
from django.db.models.signals import post_save
from django.dispatch import receiver
from shop.models import Product, FAQ, ReturnPolicy, ShippingPolicy
from sanza.data.indexer import build_index

def trigger_rebuild(sender, **kwargs):
    """Call build_index in background to avoid blocking the main thread"""
    t = threading.Thread(target=build_index)
    t.daemon = True
    t.start()

@receiver(post_save, sender=Product)
def product_saved(sender, instance, **kwargs):
    trigger_rebuild(sender)

@receiver(post_save, sender=FAQ)
def faq_saved(sender, instance, **kwargs):
    trigger_rebuild(sender)

@receiver(post_save, sender=ReturnPolicy)
def policy_saved(sender, instance, **kwargs):
    trigger_rebuild(sender)

@receiver(post_save, sender=ShippingPolicy)
def shipping_saved(sender, instance, **kwargs):
    trigger_rebuild(sender)
