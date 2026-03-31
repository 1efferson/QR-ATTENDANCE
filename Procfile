# Procfile
web:    gunicorn --workers 4 --worker-class gevent --worker-connections 1000 \
                 --timeout 30 --bind 0.0.0.0:$PORT "app:create_app()"

worker: celery -A app.tasks.celery_app.celery worker \
               --loglevel=info \
               --queues=sheets,celery \
               --concurrency=4