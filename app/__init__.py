import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from config import Config
from flask_migrate import Migrate

# Initialize extensions globally, but unattached to app
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()

def create_app(config_class=Config):
    """Application Factory to create and configure the Flask app."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions with the app
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # Configure Login Manager
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'

    os.makedirs(app.instance_path, exist_ok=True)

    # Register Blueprints
    # These imports are inside the factory to avoid circular dependencies
    from app.routes.auth import auth_bp
    from app.routes.instructor import instructor_bp
    from app.routes.student import student_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(instructor_bp, url_prefix='/instructor')
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin') 
    # -----------------------------------------------------------------------
    # Scheduled job — marks absences at end of each class day
    # Runs at 8pm every day. Only writes absences for batches whose
    # schedule includes today's weekday.
    # -----------------------------------------------------------------------
    _start_absence_scheduler(app)

    return app


def _start_absence_scheduler(app):
    """
    Start APScheduler background job to mark absent students.
    Runs daily at 20:00 (8pm). Safe to call multiple times — checks
    for existing scheduler to avoid duplicate jobs in debug/reload mode.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            func=_mark_absences_job,
            trigger=CronTrigger(hour=21, minute=0),
            args=[app],
            id='mark_absences',
            replace_existing=True
        )
        scheduler.start()

        import atexit
        atexit.register(lambda: scheduler.shutdown(wait=False))

    except Exception as e:
        print(f"[Scheduler] Failed to start: {e}")


def _mark_absences_job(app):
    """
    Runs inside the app context at 8pm every day.
    For every active batch that has class today, finds all students
    who did not scan and creates an Absence record for each one.
    Skips students who already have an absence record for today
    (UniqueConstraint prevents duplicates regardless).
    """
    from datetime import date
    from sqlalchemy import func

    with app.app_context():
        try:
            from app.models import Batch, User, Attendance, Absence

            today = date.today()
            today_weekday = today.weekday()  # 0=Monday ... 6=Sunday

            # Get all active batches that have class today
            active_batches = Batch.query.filter_by(is_active=True).all()
            class_batches = [
                b for b in active_batches
                if any(s.weekday == today_weekday for s in b.schedules)
            ]

            if not class_batches:
                print(f"[Scheduler] No batches have class today ({today}). No absences recorded.")
                return

            for batch in class_batches:
                # Get all students in this batch
                students = User.query.filter_by(
                    batch_id=batch.id,
                    role='student'
                ).all()

                # Get IDs of students who scanned today (any scan counts as present)
                present_ids = {
                    row[0] for row in db.session.query(Attendance.user_id).filter(
                        Attendance.user_id.in_([s.id for s in students]),
                        func.date(Attendance.timestamp) == today,
                        Attendance.is_personal_time == False
                    ).all()
                }

                # Create absence record for each student who didn't scan
                absences_created = 0
                for student in students:
                    if student.id not in present_ids:
                        # Check if absence already exists (safety check)
                        existing = Absence.query.filter_by(
                            user_id=student.id,
                            date=today
                        ).first()

                        if not existing:
                            absence = Absence(
                                user_id=student.id,
                                batch_id=batch.id,
                                date=today
                            )
                            db.session.add(absence)
                            absences_created += 1

                db.session.commit()
                print(f"[Scheduler] Batch '{batch.name}': {absences_created} absences recorded for {today}")

        except Exception as e:
            print(f"[Scheduler] Error marking absences: {e}")
            db.session.rollback()