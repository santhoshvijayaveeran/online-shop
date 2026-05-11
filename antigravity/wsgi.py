"""
WSGI config for online_shop project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""
# online_shop/wsgi.py
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'antigravity.settings')

application = get_wsgi_application()
app = application  # some platforms (e.g. Vercel) need it named "app"
