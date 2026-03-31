import logging
from app import celery

logger = logging.getLogger(__name__)


def _do_batch_sync_unsynced_students() -> dict:
    """
    Finds every student where is_synced_to_sheets=False,
    groups them by batch, and pushes each batch in a single
    2-API-call operation. Marks them synced after success.

    Called by Celery Beat every 5 minutes automatically.
    """
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

            # Mark all as synced in a single bulk UPDATE
            user_ids = [u.id for u in unsynced]
            User.query.filter(User.id.in_(user_ids)).update(
                {"is_synced_to_sheets": True},
                synchronize_session=False,
            )
            db.session.commit()

            count = result.get("appended", 0)
            total_synced += count
            logger.info(
                "Batch sync complete for '%s': %d students appended, %d already existed.",
                batch.name, count, len(unsynced) - count,
            )

        except Exception as e:
            db.session.rollback()
            logger.error("Batch sheet sync failed for '%s': %s", batch.name, e)
            # Exception bubbles up — Celery's autoretry_for handles the retry

    return {"total_synced": total_synced}


def _do_batch_attendance_sync(batch_id: int, date_str: str) -> None:
    """Daily attendance sync — called by the 9 PM scheduler."""
    from app.models import Batch, User, Attendance
    from app.sheets_sync import sync_daily_attendance, _worksheet_name
    from app import db
    from sqlalchemy import not_
    from datetime import date, datetime

    batch = Batch.query.get(batch_id)
    if not batch:
        logger.error("sync_batch_attendance: batch_id=%s not found — skipping", batch_id)
        return

    today = date.fromisoformat(date_str)
    today_start = datetime.combine(today, datetime.min.time())
    tomorrow_start = datetime.combine(today, datetime.max.time())

    present_subquery = db.session.query(Attendance.user_id).filter(
        Attendance.timestamp >= today_start,
        Attendance.timestamp < tomorrow_start,
        Attendance.is_personal_time == False,
        Attendance.student_level == batch.current_level,
    ).subquery()

    present_names = [
        s.name for s in User.query.filter(User.id.in_(present_subquery)).all()
    ]
    absent_names = [
        s.name for s in User.query.filter(
            User.batch_id == batch.id,
            User.role == 'student',
            not_(User.id.in_(present_subquery)),
        ).all()
    ]

    sync_daily_attendance(
        present_names=present_names,
        absent_names=absent_names,
        worksheet_name=_worksheet_name(batch),
        target_date=today,
    )
    logger.info("Batch attendance synced for '%s' on %s", batch.name, date_str)


# ── Register tasks with Celery if available ───────────────────────────────

if celery is not None:
    sync_unsynced_students_task = celery.task(
        max_retries=3,
        autoretry_for=(Exception,),
        retry_backoff=True,
        retry_backoff_max=120,
        retry_jitter=True,
        acks_late=True,
        name="app.tasks.sheet_tasks.sync_unsynced_students_task",
    )(_do_batch_sync_unsynced_students)

    sync_batch_attendance_task = celery.task(
        max_retries=3,
        autoretry_for=(Exception,),
        retry_backoff=True,
        retry_backoff_max=300,
        retry_jitter=True,
        acks_late=True,
        name="app.tasks.sheet_tasks.sync_batch_attendance_task",
    )(_do_batch_attendance_sync)

else:
    sync_unsynced_students_task = None
    sync_batch_attendance_task = None

# Keep this name available so any old import references don't break
sync_student_to_sheet_task = None