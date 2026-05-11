#!/usr/bin/env bash
# Exit on error
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py fix_migrations
python manage.py migrate social_django --fake-initial
python manage.py migrate --fake-initial
python manage.py rebuild_sanza_index