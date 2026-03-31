from celery import Celery


def make_celery(app) -> Celery:
    """
    Creates a Celery instance bound to the Flask app context.
    Every task automatically runs inside `with app.app_context()`,
    so SQLAlchemy sessions, config, and extensions work normally.
    """
    celery = Celery(
        app.import_name,
        broker=app.config["CELERY_BROKER_URL"],
        backend=app.config["CELERY_RESULT_BACKEND"],
    )

    celery.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Africa/Accra",
        enable_utc=True,
        # ── Reliability settings ──────────────────────────────────────────
        task_acks_late=True,           # Only mark task done AFTER it completes
        worker_prefetch_multiplier=1,  # Fair dispatch; prevents one worker hoarding
        task_routes={
            # Isolate Sheets tasks onto a dedicated queue so a Sheets outage
            # or quota burst does NOT delay any other background work.
            "app.tasks.sheet_tasks.*": {"queue": "sheets"},
        },
    )
    

    class ContextTask(celery.Task):
        """Wraps every task execution in the Flask app context."""
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
            
            

    celery.Task = ContextTask
    return celery