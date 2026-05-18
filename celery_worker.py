from app import create_app
from celery.schedules import crontab

# Initialize the Flask app
flask_app = create_app()

# Retrieve the Celery instance saved in extensions
celery = flask_app.extensions["celery"]

# Import tasks AFTER make_celery() has run so @shared_task binds correctly
import app.tasks.sheet_tasks

# Only the 5-minute student sync runs via Beat.
# The 9 PM attendance sync is owned by APScheduler (scheduler.py) which
# also handles absence recording — running both would cause double sheet syncs.
celery.conf.beat_schedule = {
    "sync-unsynced-students-every-5-min": {
        "task": "app.tasks.sheet_tasks.sync_unsynced_students_task",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": "sheets"},
    },
}