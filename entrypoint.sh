#!/bin/sh
set -e

echo "Waiting for database..."
while ! python -c "import psycopg2; psycopg2.connect(host='$DB_HOST', dbname='$DB_NAME', user='$DB_USER', password='$DB_PASSWORD')" 2>/dev/null; do
  sleep 1
done
echo "Database ready."

python manage.py migrate --noinput
python manage.py backfill_vacancy_profiles
python manage.py collectstatic --noinput

exec gunicorn prep_mate.wsgi:application \
  --bind 0.0.0.0:8000 \
  --worker-class gevent \
  --workers 2 \
  --worker-connections 20 \
  --timeout 120
