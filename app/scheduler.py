"""
scheduler.py
============
APScheduler configuration for QR-Attend.

Registers the 9 PM daily job that:
  1. Finds every active batch scheduled for today
  2. Identifies which students in each batch did NOT scan in
  3. Writes Absence records to the local DB
  4. Pushes "Absent" to the Google Sheet for those students

Usage — call init_scheduler(app) once inside create_app():

    from app.scheduler import init_scheduler
    init_scheduler(app)
"""

import logging
from datetime import date, datetime
from app.sheets_sync import mark_batch_absences, _worksheet_name

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# Spreadsheet config — set these in your Flask app config or .env

def _run_absence_sync():
    """
    Core logic for the 9 PM job.
    Runs inside the Flask app context (pushed by the wrapper below).
    """
    from app import db
    from app.models import Batch, User, Attendance, Absence
    from app.sheets_sync import mark_batch_absences

    today = date.today()
    logger.info("=== Absence sync started for %s ===", today)

    # Find all active batches scheduled for today
    active_batches = Batch.query.filter_by(is_active=True).all()
    batches_today  = [b for b in active_batches if b.is_class_day(today)]

    if not batches_today:
        logger.info("No batches scheduled for today (%s). Nothing to do.", today.strftime("%A"))
        return

    for batch in batches_today:
        logger.info("Processing batch: %s", batch.name)

        # Students in this batch
        all_students = User.query.filter_by(batch_id=batch.id, role='student').all()

        # Students who scanned in today (non-personal-time scans only)
        present_ids = {
            row.user_id
            for row in Attendance.query.filter(
                Attendance.user_id.in_([s.id for s in all_students]),
                db.func.date(Attendance.timestamp) == today,
                Attendance.is_personal_time == False,
            ).all()
        }

        # Absent = all students minus those present
        absent_students = [s for s in all_students if s.id not in present_ids]

        if not absent_students:
            logger.info("All students in '%s' were present today.", batch.name)
            continue

        # Write Absence records to local DB (skip duplicates)
        newly_absent = []
        for student in absent_students:
            exists = Absence.query.filter_by(user_id=student.id, date=today).first()
            if not exists:
                db.session.add(Absence(
                    user_id  = student.id,
                    batch_id = batch.id,
                    date     = today,
                ))
                newly_absent.append(student)

        db.session.commit()
        logger.info(
            "Recorded %d new absences for batch '%s'.",
            len(newly_absent), batch.name
        )

        # Push to Google Sheet
        absent_names   = [s.name for s in absent_students]  # includes already-DB-recorded too

        sync_result = mark_batch_absences(
            absent_student_names = absent_names,
            worksheet_name       = _worksheet_name(batch),  # "CodeCamp 3&4 - Beginner"
        )

        logger.info(
            "Sheet sync for '%s': marked=%s, not_found=%s, already_set=%s, errors=%s",
            batch.name,
            sync_result.get("marked"),
            sync_result.get("not_found"),
            sync_result.get("already_set"),
            sync_result.get("errors"),
        )

        if sync_result.get("not_found"):
            logger.warning(
                "These students are absent but NOT in the sheet for batch '%s': %s",
                batch.name, sync_result["not_found"]
            )

    logger.info("=== Absence sync complete ===")


def init_scheduler(app):
    """
    Create and start the APScheduler. Call this once inside create_app().

    The job fires daily at 21:00 (9 PM) server time.
    If your server runs UTC and you're in a different timezone,
    set timezone= below, e.g. timezone="Africa/Accra"
    """
    scheduler = BackgroundScheduler(timezone="Africa/Accra")

    def job_with_context():
        """Push Flask app context so models and db are accessible."""
        with app.app_context():
            try:
                _run_absence_sync()
            except Exception as e:
                logger.exception("Absence sync job failed: %s", e)

    scheduler.add_job(
        func    = job_with_context,
        trigger = CronTrigger(hour=21, minute=0),   # 9:00 PM
        id      = "daily_absence_sync",
        name    = "Daily 9 PM Absence Sync",
        replace_existing = True,
        misfire_grace_time = 600,   # Allow up to 10 min late if server was busy
    )

    scheduler.start()
    logger.info("APScheduler started — absence sync scheduled for 21:00 Africa/Accra daily.")

    # Graceful shutdown when Flask exits
    import atexit
    atexit.register(lambda: scheduler.shutdown(wait=False))

    return scheduler