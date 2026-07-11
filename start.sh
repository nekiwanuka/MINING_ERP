#!/usr/bin/env bash
set -o errexit

python manage.py migrate
python manage.py ensure_admin
gunicorn mining_erp.wsgi:application