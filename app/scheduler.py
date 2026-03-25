"""
scheduler.py
============
APScheduler configuration for QR-Attend.

Responsible for the 9 PM daily absence sync:
  1. Finds every active batch scheduled for today.
  2. Identifies students who did NOT scan via a database-level anti-join.
  3. Writes Absence records to DB using an atomic UPSERT (PostgreSQL).
  4. Pushes 0 (Absent) to Google Sheet with exponential backoff retry.
"""

import logging
import time
from datetime import date
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, not_
from sqlalchemy.dialects.postgresql import insert

logger = logging.getLogger(__name__)

# Retry config for Google Sheet sync
SHEET_RETRIES = 3      
SHEET_BACKOFF = 5.0    

def _run_absence_sync():
    """
    Core logic for the 9 PM job.
    Uses an Anti-Join subquery to identify absences at the DB level for maximum speed.
    """
    from app import db
    from app.models import Batch, User, Attendance, Absence
    from app.sheets_sync import mark_batch_absences, _worksheet_name
    from gspread.exceptions import APIError

    today = date.today()
    today_weekday = today.weekday()

    logger.info("=== Absence sync started for %s ===", today)

    # 1. Find batches active today
    active_batches = Batch.query.filter_by(is_active=True).all()
    batches_today = [
        b for b in active_batches
        if any(s.weekday == today_weekday for s in b.schedules)
    ]

    if not batches_today:
        logger.info("No batches scheduled for today. Nothing to do.")
        return

    for batch in batches_today:
        logger.info("Processing batch: '%s' [%s]", batch.name, batch.current_level)

        # 2. Database-level Anti-Join: Find students who DID NOT scan today at this level
        # This subquery finds the 'Present' students
        present_subquery = db.session.query(Attendance.user_id).filter(
            func.date(Attendance.timestamp) == today,
            Attendance.is_personal_time == False,
            Attendance.student_level == batch.current_level
        ).subquery()

        # This query finds students in the batch NOT in the 'Present' list
        absent_students = User.query.filter(
            User.batch_id == batch.id,
            User.role == 'student',
            not_(User.id.in_(present_subquery))
        ).all()

        if not absent_students:
            logger.info("All students in '%s' were present.", batch.name)
            continue

        absent_names = [s.name for s in absent_students]
        
        # 3. Atomic Batch Insert (PostgreSQL 'ON CONFLICT DO NOTHING')
        # This is significantly faster than checking 'if exists' for every student
        try:
            for student in absent_students:
                stmt = insert(Absence).values(
                    user_id=student.id,
                    batch_id=batch.id,
                    date=today
                ).on_conflict_do_nothing(index_elements=['user_id', 'date'])
                db.session.execute(stmt)
            
            db.session.commit()
            logger.info("Recorded absences in DB for batch '%s'.", batch.name)
        except Exception as e:
            db.session.rollback()
            logger.error("Failed to commit absences to DB for '%s': %s", batch.name, e)

        # 4. Sync to Google Sheet with retry
        worksheet_name = _worksheet_name(batch)
        for attempt in range(1, SHEET_RETRIES + 1):
            try:
                sync_result = mark_batch_absences(
                    absent_student_names=absent_names,
                    worksheet_name=worksheet_name,
                )
                logger.info("Sheet sync '%s' success (Attempt %d).", batch.name, attempt)
                break 
            except (APIError, Exception) as e:
                if isinstance(e, APIError) and e.response.status_code == 429:
                    logger.error("API quota exceeded for '%s'. Skipping sync.", batch.name)
                    break
                
                if attempt < SHEET_RETRIES:
                    wait = SHEET_BACKOFF * attempt
                    logger.warning("Retry %d/%d for '%s' in %ds...", attempt, SHEET_RETRIES, batch.name, wait)
                    time.sleep(wait)
                else:
                    logger.error("Sheet sync failed for '%s' after %d attempts.", batch.name, SHEET_RETRIES)

    logger.info("=== Absence sync complete ===")

def init_scheduler(app):
    """Initializes and starts the BackgroundScheduler."""
    scheduler = BackgroundScheduler(timezone="Africa/Accra")

    def job_with_context():
        with app.app_context():
            try:
                _run_absence_sync()
            except Exception as e:
                logger.exception("Absence sync job failed: %s", e)

    scheduler.add_job(
        func=job_with_context,
        trigger=CronTrigger(hour=21, minute=0),
        id="daily_absence_sync",
        name="Daily 9 PM Absence Sync",
        replace_existing=True,
        misfire_grace_time=600,
    )

    scheduler.start()
    logger.info("APScheduler started — sync at 21:00 Africa/Accra daily.")

    import atexit
    atexit.register(lambda: scheduler.shutdown(wait=False))
    return scheduler