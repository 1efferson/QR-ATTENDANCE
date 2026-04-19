from app import create_app
from celery.schedules import crontab

# Initialize the Flask App
flask_app = create_app()

# Retrieve the Celery instance we saved in extensions
celery = flask_app.extensions["celery"]

# Import tasks so the worker registers them
import app.tasks.sheet_tasks 

# Configure the Beat Schedule
celery.conf.beat_schedule = {
    "sync-unsynced-students-every-5-min": {
        "task": "app.tasks.sheet_tasks.sync_unsynced_students_task",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": "sheets"},
    },
    "daily-attendance-sync-9pm": {
        "task": "app.tasks.sheet_tasks.trigger_daily_attendance",
        "schedule": crontab(hour=21, minute=0), # 9:00 PM
        "options": {"queue": "sheets"},
    }
}