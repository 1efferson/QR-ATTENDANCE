import logging
import time
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import not_, select
from sqlalchemy.dialects.postgresql import insert

from app import db
from app.models import Batch, User, Attendance, Absence, Holiday, BatchException

logger = logging.getLogger(__name__)


def _run_absence_sync(force=False):

    now = datetime.now()

    CUTOFF_HOUR = 20
    if not force and now.hour < CUTOFF_HOUR:
        logger.warning("Absence sync called before cutoff (%d:00). Skipping.", CUTOFF_HOUR)
        return {'skipped': True, 'reason': f'Too early — run after {CUTOFF_HOUR}:00'}

    today = date.today()
    today_weekday = today.weekday()
    today_start = datetime.combine(today, datetime.min.time())
    tomorrow_start = today_start + timedelta(days=1)

    logger.info("=== Absence Sync triggered for %s (force=%s) ===", today, force)

    # Holiday guard: skip entirely if today is a global holiday
    is_global_holiday = db.session.query(Holiday.id).filter(
        Holiday.date == today
    ).first()

    if is_global_holiday:
        logger.info("Skipping absence sync — global holiday today (%s).", today)
        return {'skipped': True, 'reason': 'Global holiday'}

    # Fetch batch exceptions for today in one query
    excepted_batch_ids = {
        row.batch_id for row in
        db.session.query(BatchException.batch_id).filter(
            BatchException.date == today
        ).all()
    }

    active_batches = Batch.query.filter_by(is_active=True).all()
    logger.info("Found %d active batch(es) total.", len(active_batches))

    batches_today = [
        b for b in active_batches
        if any(s.weekday == today_weekday for s in b.schedules)
        and b.id not in excepted_batch_ids
    ]

    logger.info("Found %d batch(es) scheduled for today (%s).", len(batches_today), today.strftime("%A"))

    if not batches_today:
        logger.info("No batches scheduled for today. Nothing to do.")
        return {'skipped': True, 'reason': 'No batches scheduled for today'}

    processed = 0
    for batch in batches_today:
        logger.info("Processing batch: '%s' [%s]", batch.name, batch.current_level)

        present_stmt = db.session.query(Attendance.user_id).filter(
            Attendance.timestamp >= today_start,
            Attendance.timestamp < tomorrow_start,
            Attendance.is_personal_time == False,
            Attendance.student_level == batch.current_level,
        )

        absent_students = User.query.filter(
            User.batch_id == batch.id,
            User.role == 'student',
            not_(User.id.in_(present_stmt)),
        ).all()

        logger.info(
            "Batch '%s': %d absent student(s) found.",
            batch.name, len(absent_students)
        )

        if absent_students:
            try:
                absence_data = [
                    {'user_id': s.id, 'batch_id': batch.id, 'date': today}
                    for s in absent_students
                ]
                stmt = insert(Absence).values(absence_data).on_conflict_do_nothing(
                    index_elements=['user_id', 'date']
                )
                db.session.execute(stmt)
                db.session.commit()
                logger.info("Bulk recorded %d absences for '%s'.", len(absent_students), batch.name)
            except Exception as e:
                db.session.rollback()
                logger.error("Failed to commit absences for '%s': %s", batch.name, e)

        # Enqueue sheet sync via Celery
        from app.tasks.sheet_tasks import sync_batch_attendance_task
        try:
            sync_batch_attendance_task.apply_async(
                args=[batch.id, str(today)],
                queue="sheets",
                countdown=5,
            )
            logger.info("Sheet sync enqueued for batch '%s'.", batch.name)
        except Exception as e:
            logger.error("Sheet sync enqueue failed for '%s': %s", batch.name, e)

        processed += 1

    logger.info("=== Absence sync complete — %d batch(es) processed ===", processed)
    return {'skipped': False, 'processed': processed}


# ─── Pulse job: remove after confirming scheduler works ─────────────────────

def _test_pulse():
    print(f">>> SCHEDULER PULSE: {datetime.now().strftime('%H:%M:%S')} — scheduler is alive", flush=True)
    logger.info("Scheduler pulse check at %s", datetime.now().strftime('%H:%M:%S'))


# ─── Init ────────────────────────────────────────────────────────────────────

def init_scheduler(app):
    scheduler = BackgroundScheduler(timezone="Africa/Accra")

    def job_with_context():
        with app.app_context():
            try:
                logger.info(">>> 9PM cron fired — starting absence sync job")
                _run_absence_sync(force=True)
            except Exception as e:
                logger.exception("Absence sync job failed: %s", e)

    # Main 9pm job
    scheduler.add_job(
        func=job_with_context,
        trigger=CronTrigger(hour=21, minute=0),
        id="daily_absence_sync",
        name="Daily 9 PM Absence Sync",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # ── TEMPORARY: pulse every 1 minute to confirm scheduler is ticking ──
    # Delete this block once confirmed working
    scheduler.add_job(
        func=_test_pulse,
        trigger="interval",
        minutes=1,
        id="test_pulse_job",
        name="Temporary Pulse Check",
        replace_existing=True,
    )
    # ─────────────────────────────────────────────────────────────────────

    scheduler.start()
    logger.info("APScheduler started — sync at 21:00 Africa/Accra daily.")
    print(">>> APScheduler started — waiting for jobs", flush=True)

    import atexit
    atexit.register(lambda: scheduler.shutdown(wait=False))
    return scheduler