from flask import render_template, redirect, url_for, flash, request, jsonify, Response
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import case
import csv
from io import StringIO
from . import instructor_bp
from app.instructor_queries import AttendanceQueries
from app.models import Attendance, User, Batch
from app import db


def instructor_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.role != 'instructor':
            flash("Access denied: Instructors only.", "error")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_levels():
    """Return levels sorted beginner → intermediate → advanced."""
    level_order = case(
        {'beginner': 1, 'intermediate': 2, 'advanced': 3},
        value=User.level,
        else_=4
    )
    rows = db.session.query(User.level).filter(
        User.role == 'student',
        User.level != None
    ).distinct().order_by(level_order).all()
    return [r[0] for r in rows]


def _get_active_batches():
    """Return all active batches ordered by name."""
    return Batch.query.filter_by(is_active=True).order_by(Batch.name).all()


def _validate_days(raw):
    """Parse and whitelist the days parameter."""
    try:
        days = int(raw or 30)
        return days if days in [7, 14, 30, 60, 90] else 30
    except (ValueError, TypeError):
        return 30


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@instructor_bp.route('/dashboard')
@instructor_required
def dashboard():
    """
    Main instructor dashboard.
    Supports independent filtering by level, batch, and date range.
    """
    try:
        levels  = _get_levels()
        batches = _get_active_batches()

        # Empty state — no students with a level yet
        if not levels:
            return render_template('instructor/dashboard.html',
                                   level=None, days=30,
                                   levels=[], batches=batches,
                                   selected_batch=None,
                                   no_data=True)

        # -- Parse & validate filters --
        level    = request.args.get('level') or None
        batch_id = request.args.get('batch_id', type=int) or None
        days     = _validate_days(request.args.get('days'))

        # Reject unknown level values
        if level and level not in levels:
            level = None

        # Reject unknown batch_id values
        if batch_id and not any(b.id == batch_id for b in batches):
            batch_id = None

        # -- Run queries --
        today_checkins    = AttendanceQueries.total_checkins_today(level, batch_id)
        expected_students = AttendanceQueries.total_expected_students(level, batch_id)
        today_percentage  = AttendanceQueries.attendance_percentage_today(level, batch_id)
        avg_checkin_times = AttendanceQueries.student_average_checkin_time(level, days, batch_id)
        top_5_earliest    = AttendanceQueries.top_5_earliest_students(level, batch_id=batch_id)
        student_percentages = AttendanceQueries.attendance_percentage_per_student(level, days, batch_id)
        students_below_60   = AttendanceQueries.students_below_threshold(60, level, days, batch_id)

        return render_template('instructor/dashboard.html',
                               level=level,
                               days=days,
                               levels=levels,
                               batches=batches,
                               selected_batch=batch_id,
                               today_checkins=today_checkins,
                               expected_students=expected_students,
                               today_percentage=today_percentage,
                               avg_checkin_times=avg_checkin_times,
                               top_5_earliest=top_5_earliest,
                               student_percentages=student_percentages,
                               students_below_60=students_below_60,
                               no_data=False)

    except SQLAlchemyError as e:
        print(f"Database error in dashboard: {str(e)}")
        flash("A database error occurred. Please try again.", "error")
        return render_template('instructor/dashboard.html',
                               level=None, days=30, levels=[],
                               batches=[], selected_batch=None, error=True)

    except Exception as e:
        print(f"Unexpected error in dashboard: {str(e)}")
        flash("An unexpected error occurred. Please contact support.", "error")
        return render_template('instructor/dashboard.html',
                               level=None, days=30, levels=[],
                               batches=[], selected_batch=None, error=True)


# ---------------------------------------------------------------------------
# QR Generator
# ---------------------------------------------------------------------------

@instructor_bp.route('/generate-qr')
@instructor_required
def generate_qr():
    return render_template('instructor/generate_qr.html')


# ---------------------------------------------------------------------------
# API: aggregate stats
# ---------------------------------------------------------------------------

@instructor_bp.route('/api/stats')
@instructor_required
def get_stats_api():
    """
    API endpoint for AJAX requests.
    Accepts optional level and batch_id params.
    """
    try:
        level    = request.args.get('level') or None
        batch_id = request.args.get('batch_id', type=int) or None
        days     = _validate_days(request.args.get('days'))

        stats = AttendanceQueries.get_level_statistics(level, days, batch_id)

        return jsonify({
            'success':   True,
            'timestamp': datetime.now().isoformat(),
            'data':      stats
        }), 200

    except SQLAlchemyError:
        return jsonify({'error': 'Database error occurred', 'success': False}), 500
    except Exception:
        return jsonify({'error': 'Unexpected error occurred', 'success': False}), 500


# ---------------------------------------------------------------------------
# API: individual student attendance (modal)
# ---------------------------------------------------------------------------

@instructor_bp.route('/api/student/<int:student_id>/attendance')
@instructor_required
def get_student_attendance_api(student_id):
    """
    Returns attendance records for a single student.
    If level or batch_id are provided, the student must match both.
    """
    try:
        days     = _validate_days(request.args.get('days'))
        level    = request.args.get('level') or None
        batch_id = request.args.get('batch_id', type=int) or None

        student_query = User.query.filter_by(id=student_id, role='student')
        if level:
            student_query = student_query.filter_by(level=level)
        if batch_id:
            student_query = student_query.filter_by(batch_id=batch_id)

        student = student_query.first()
        if not student:
            return jsonify({
                'error': 'Student not found for the selected filters',
                'success': False
            }), 404

        cutoff_date = datetime.now() - timedelta(days=days)
        attendance_records = Attendance.query.filter(
            Attendance.user_id == student_id,
            Attendance.timestamp >= cutoff_date
        ).order_by(Attendance.timestamp.desc()).all()

        records = [{
            'date':       record.timestamp.strftime('%Y-%m-%d'),
            'time':       record.timestamp.strftime('%H:%M:%S'),
            'level':      student.level,
            'ip_address': record.ip_address
        } for record in attendance_records]

        return jsonify({
            'success': True,
            'student': {
                'id':       student.id,
                'name':     student.name,
                'email':    student.email,
                'level':    student.level,
                'batch_id': student.batch_id
            },
            'attendance_records': records,
            'total_records':      len(records)
        }), 200

    except Exception:
        return jsonify({'error': 'Error fetching student attendance', 'success': False}), 500


# ---------------------------------------------------------------------------
# Export CSV
# ---------------------------------------------------------------------------

@instructor_bp.route('/api/export/attendance')
@instructor_required
def export_attendance_csv():
    """
    Export attendance data as CSV.
    Filtered by level and/or batch_id independently.
    """
    try:
        level    = request.args.get('level') or None
        batch_id = request.args.get('batch_id', type=int) or None
        days     = _validate_days(request.args.get('days'))

        student_data = AttendanceQueries.attendance_percentage_per_student(level, days, batch_id)

        si = StringIO()
        writer = csv.writer(si)
        writer.writerow([
            'Student ID', 'Student Name', 'Email', 'Level', 'Batch ID',
            'Days Attended', 'Total Days', 'Attendance %', 'Status'
        ])

        for s in student_data:
            writer.writerow([
                s['student_id'],
                s['student_name'],
                s['student_email'],
                s['student_level'] or 'N/A',
                s['student_batch_id'] or 'N/A',
                s['days_attended'],
                s['total_days'],
                f"{s['attendance_pct']}%",
                'At Risk' if s['is_below_threshold'] else 'Good'
            ])

        output = si.getvalue()
        si.close()

        level_label = level or 'all_levels'
        batch_label = str(batch_id) if batch_id else 'all_batches'
        filename = f"attendance_{level_label}_{batch_label}_{days}days.csv"

        return Response(
            output,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )

    except Exception:
        flash('Error exporting attendance data', 'error')
        return redirect(url_for('instructor.dashboard'))


# ---------------------------------------------------------------------------
# Level detail page
# ---------------------------------------------------------------------------

@instructor_bp.route('/level/<string:level>')
@instructor_required
def level_detail(level):
    """Detailed view for a specific student level."""
    try:
        days     = _validate_days(request.args.get('days'))
        batch_id = request.args.get('batch_id', type=int) or None

        level_exists = db.session.query(User.id).filter(
            User.role == 'student',
            User.level == level
        ).first()

        if not level_exists:
            flash(f"No students found for level: {level}", "error")
            return redirect(url_for('instructor.dashboard'))

        stats = AttendanceQueries.get_level_statistics(level, days, batch_id)

        return render_template('instructor/level_detail.html',
                               level=level, days=days, stats=stats)

    except Exception:
        flash('Error loading level details', 'error')
        return redirect(url_for('instructor.dashboard'))