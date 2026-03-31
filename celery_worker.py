from app import create_app
from app.tasks.celery_app import make_celery
from celery.schedules import crontab

flask_app = create_app()
celery = make_celery(flask_app)

# without this import the worker starts
# with an empty [tasks] list and rejects everything it receives
import app.tasks.sheet_tasks 

# Periodic tasks — Celery Beat fires these automatically
celery.conf.beat_schedule = {
    "sync-unsynced-students-every-5-min": {
        "task": "app.tasks.sheet_tasks.sync_unsynced_students_task",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": "sheets"},
    },
}
celery.conf.timezone = "Africa/Accra"