import logging
from sqlalchemy import not_, select
from datetime import date, datetime
from celery import shared_task

logger = logging.getLogger(__name__)

@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    acks_late=True,
    name="app.tasks.sheet_tasks.sync_unsynced_students_task",
)
def sync_unsynced_students_task(self):
    """Called by Celery Beat every 5 minutes automatically."""
    from app import db
    from app.models import User, Batch
    from app.sheets_sync import append_students_to_sheet_batch

    active_batches = Batch.query.filter_by(is_active=True).all()
    total_synced = 0

    for batch in active_batches:
        unsynced = User.query.filter_by(
            batch_id=batch.id,
            role='student',
            is_synced_to_sheets=False,
        ).all()

        if not unsynced:
            continue

        try:
            result = append_students_to_sheet_batch(batch, unsynced)

            user_ids = [u.id for u in unsynced]
            User.query.filter(User.id.in_(user_ids)).update(
                {"is_synced_to_sheets": True},
                synchronize_session=False,
            )
            db.session.commit()

            count = result.get("appended", 0)
            total_synced += count
            logger.info("Batch sync complete for '%s': %d students appended.", batch.name, count)

        except Exception as e:
            db.session.rollback()
            logger.error("Batch sheet sync failed for '%s': %s", batch.name, e)
            raise e # Triggers the autoretry

    return {"total_synced": total_synced}


@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    acks_late=True,
    name="app.tasks.sheet_tasks.sync_batch_attendance_task",
)
def sync_batch_attendance_task(self, batch_id: int, date_str: str):
    """Performs the actual Daily attendance sync for a specific batch."""
    from app.models import Batch, User, Attendance
    from app.sheets_sync import sync_daily_attendance, _worksheet_name
    from app import db

    batch = Batch.query.get(batch_id)
    if not batch:
        return

    today = date.fromisoformat(date_str)
    today_start = datetime.combine(today, datetime.min.time())
    tomorrow_start = datetime.combine(today, datetime.max.time())

    present_stmt = db.session.query(Attendance.user_id).filter(
        Attendance.timestamp >= today_start,
        Attendance.timestamp < tomorrow_start,
        Attendance.is_personal_time == False,
        Attendance.student_level == batch.current_level,
    )

    present_names = [s.name for s in User.query.filter(User.id.in_(present_stmt)).all()]
    absent_names = [s.name for s in User.query.filter(
        User.batch_id == batch.id,
        User.role == 'student',
        not_(User.id.in_(present_stmt)),
    ).all()]

    sync_daily_attendance(
        present_names=present_names,
        absent_names=absent_names,
        worksheet_name=_worksheet_name(batch),
        target_date=today,
    )


@shared_task(name="app.tasks.sheet_tasks.trigger_daily_attendance")
def trigger_daily_attendance():
    """Master Task: Runs at 9:00 PM. Finds all active batches and queues a sync task for today."""
    from app.models import Batch
    
    active_batches = Batch.query.filter_by(is_active=True).all()
    today_str = date.today().isoformat()
    
    for batch in active_batches:
        # .delay() pushes the job to the worker queue asynchronously
        sync_batch_attendance_task.delay(batch.id, today_str)