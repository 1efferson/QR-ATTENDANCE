from celery import Celery

def make_celery(app) -> Celery:
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
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_routes={
            "app.tasks.sheet_tasks.*": {"queue": "sheets"},
        },
    )

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    
    # Save the celery instance to the Flask app
    app.extensions["celery"] = celery 
    return celery