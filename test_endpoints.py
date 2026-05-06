import os
import django
import traceback
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'online_shop.settings')
django.setup()

from django.test import Client
from shop.urls import urlpatterns
from django.urls import reverse

c = Client(SERVER_NAME='localhost')
urls = []
for p in urlpatterns:
    if p.name:
        urls.append(p.name)

print("Found urls:", len(urls))

errors = []
for name in urls:
    url = None
    try:
        url = reverse(name, args=[1] if 'int' in str(p.pattern) else None)
    except Exception as e:
        try:
            url = reverse(name)
        except Exception as e:
            try:
                url = reverse(name, args=[1])
            except:
                try:
                    url = reverse(name, kwargs={'slug': 'test'})
                except:
                    try:
                        url = reverse(name, kwargs={'email': 'test@example.com'})
                    except Exception as e:
                        print(f"Could not reverse {name}: {e}")
                        continue
    if url:
        try:
            response = c.get(url)
            if response.status_code >= 500:
                print(f"ERROR 500 on GET {name} ({url})")
                errors.append(name)
        except Exception as e:
            print(f"EXCEPTION on GET {name} ({url}): {e}")
            errors.append(name)

print("Errors found:", errors)
