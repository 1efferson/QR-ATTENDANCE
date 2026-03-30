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
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

# Retry config for Google Sheet sync
SHEET_RETRIES = 3      
SHEET_BACKOFF = 5.0    

def _run_absence_sync():
    """
    Core logic for the 9 PM job.
    Optimized with index-friendly date ranges and true DB bulk inserts.
    """
    from app import db
    from app.models import Batch, User, Attendance, Absence
    from app.sheets_sync import sync_daily_attendance, _worksheet_name # Note the changed sync function
    from gspread.exceptions import APIError

    today = date.today()
    today_weekday = today.weekday()
    
    # Calculate datetime boundaries for index-friendly querying
    today_start = datetime.combine(today, datetime.min.time())
    tomorrow_start = today_start + timedelta(days=1)

    logger.info("=== Daily Sync started for %s ===", today)

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

        # 2. Database-level Anti-Join (Optimized Date Range)
        present_subquery = db.session.query(Attendance.user_id).filter(
            Attendance.timestamp >= today_start,
            Attendance.timestamp < tomorrow_start,
            Attendance.is_personal_time == False,
            Attendance.student_level == batch.current_level
        ).subquery()

        # Get Present Students (for Google Sheets Sync)
        present_students = User.query.filter(
            User.id.in_(present_subquery)
        ).all()
        present_names = [s.name for s in present_students]

        # Get Absent Students
        absent_students = User.query.filter(
            User.batch_id == batch.id,
            User.role == 'student',
            not_(User.id.in_(present_subquery))
        ).all()
        absent_names = [s.name for s in absent_students]
        
        # 3. True Atomic Bulk Insert for Absences
        if absent_students:
            try:
                # Create a list of dictionaries for a single bulk insert
                absence_data = [
                    {'user_id': student.id, 'batch_id': batch.id, 'date': today} 
                    for student in absent_students
                ]
                
                stmt = insert(Absence).values(absence_data).on_conflict_do_nothing(
                    index_elements=['user_id', 'date']
                )
                db.session.execute(stmt)
                db.session.commit()
                logger.info("Bulk recorded %d absences in DB for batch '%s'.", len(absent_students), batch.name)
            except Exception as e:
                db.session.rollback()
                logger.error("Failed to commit absences to DB for '%s': %s", batch.name, e)

        # 4. Sync BOTH Presents and Absences to Google Sheet
        worksheet_name = _worksheet_name(batch)
        for attempt in range(1, SHEET_RETRIES + 1):
            try:
                # You will need to update your sheets_sync.py to accept both lists
                # and do a single batch_update to the sheet.
                sync_result = sync_daily_attendance(
                    present_names=present_names,
                    absent_names=absent_names,
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