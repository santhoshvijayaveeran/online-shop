import time
from collections import defaultdict
from django.http import JsonResponse
from django.shortcuts import redirect
from django.contrib import messages


# ── In-memory store (small projects-க்கு போதும்) ──
_rate_store = defaultdict(list)


def get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def is_rate_limited(key, max_attempts=5, window=300):
    """
    key: unique string (ip + action)
    max_attempts:
    window: seconds (300 = 5 minutes)
    """
    now = time.time()
    attempts = _rate_store[key]

    # Window-க்கு வெளியே இருக்கற attempts remove பண்ணு
    _rate_store[key] = [t for t in attempts if now - t < window]

    if len(_rate_store[key]) >= max_attempts:
        return True

    _rate_store[key].append(now)
    return False


def get_remaining_time(key, window=300):
   
    now = time.time()
    attempts = _rate_store.get(key, [])
    if not attempts:
        return 0
    oldest = min(attempts)
    remaining = int(window - (now - oldest))
    return max(0, remaining)