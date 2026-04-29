from django.shortcuts import render
from django.http import JsonResponse


def manifest(request):
    data = {
        "name": "Online Shop",
        "short_name": "Shop",
        "description": "Best Online Shop - Buy products online",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#111111",
        "orientation": "portrait",
        "icons": [
            {
                "src": "/static/images/logo.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable"
            },
            {
                "src": "/static/images/logo.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ],
        "screenshots": [],
        "categories": ["shopping", "ecommerce"]
    }
    return JsonResponse(data)


def serviceworker(request):
    return render(
        request,
        'progressive/serviceworker.js',
        content_type='application/javascript'
    )


def offline(request):
    return render(request, 'progressive/offline.html')