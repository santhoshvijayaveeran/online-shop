#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py fix_migrations        # social_django fake mark பண்ணும்
python manage.py migrate               # --fake-initial தேவையில்ல இனி
python manage.py rebuild_sanza_index