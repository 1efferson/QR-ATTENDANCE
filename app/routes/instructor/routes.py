from flask import render_template, redirect, url_for, flash, request, jsonify, Response
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy.exc import SQLAlchemyError
import csv
from io import StringIO
from . import instructor_bp
from app.instructor_queries import AttendanceQueries
from app.models import Attendance, User
from app import db
from sqlalchemy import case


def instructor_required(f):
    """
    Decorator to ensure only instructors can access certain routes.
    """
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.role != 'instructor':
            flash("Access denied: Instructors only.", "error")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@instructor_bp.route('/dashboard')
@instructor_required
def dashboard():
    """
    Main instructor dashboard with all analytics.
    Filtered by student level (beginner / intermediate / advanced).
    Passing level=None shows all students across all levels.
    """
    try:
        # Get all distinct levels from registered students
        levels_query = db.session.query(
            User.level
        ).filter(
            User.role == 'student',
            User.level != None
        ).distinct().order_by(User.level).all()
        levels = [row[0] for row in levels_query]

        # If no students with a level exist, show empty state
        if not levels:
            return render_template('instructor/dashboard.html',
                                   level=None,
                                   days=30,
                                   levels=[],
                                   no_data=True)

        # Get level from query params — empty string or missing means "All Levels"
        level = request.args.get('level') or None
        # If a level was passed but it's not in the known list, reset to None (all)
        if level and level not in levels:
            level = None


        # Define the custom sort order logic
        level_order = case(
            {
                'beginner': 1,
                'intermediate': 2,
                'advanced': 3
            },
            value=User.level,
            else_=4  # Any unexpected level goes to the end
        )

        # Updated query using our custom order
        levels_query = db.session.query(
            User.level
        ).filter(
            User.role == 'student',
            User.level != None
        ).distinct().order_by(level_order).all() # Use level_order instead of User.level

        levels = [row[0] for row in levels_query]

        # Validate days parameter — only allow specific values
        try:
            days = int(request.args.get('days', 30))
            if days not in [7, 14, 30, 60, 90]:
                days = 30
        except (ValueError, TypeError):
            days = 30

        # Query 1: Total check-ins today (filtered by level if selected)
        today_checkins = AttendanceQueries.total_checkins_today(level)

        # Query 2: Total expected students (filtered by level if selected)
        expected_students = AttendanceQueries.total_expected_students(level)

        # Query 3: Attendance percentage today (filtered by level if selected)
        today_percentage = AttendanceQueries.attendance_percentage_today(level)

        # Query 4: Average check-in times per student
        avg_checkin_times = AttendanceQueries.student_average_checkin_time(level, days)

        # Query 5: Top 5 earliest students today
        top_5_earliest = AttendanceQueries.top_5_earliest_students(level)

        # Query 6: Attendance percentage per student
        student_percentages = AttendanceQueries.attendance_percentage_per_student(level, days)

        # Query 7: Students below 60% attendance threshold
        students_below_60 = AttendanceQueries.students_below_threshold(60, level, days)

        return render_template('instructor/dashboard.html',
                               level=level,
                               days=days,
                               levels=levels,
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
        flash("An error occurred while loading the dashboard. Please try again.", "error")
        return render_template('instructor/dashboard.html',
                               level=None, days=30, levels=[], error=True)

    except Exception as e:
        print(f"Unexpected error in dashboard: {str(e)}")
        flash("An unexpected error occurred. Please contact support.", "error")
        return render_template('instructor/dashboard.html',
                               level=None, days=30, levels=[], error=True)


@instructor_bp.route('/generate-qr')
@instructor_required
def generate_qr():
    return render_template('instructor/generate_qr.html')


@instructor_bp.route('/api/stats')
@instructor_required
def get_stats_api():
    """
    API endpoint for AJAX requests.
    Accepts optional level param — omit for all levels.
    """
    try:
        level = request.args.get('level') or None

        try:
            days = int(request.args.get('days', 30))
            if days not in [7, 14, 30, 60, 90]:
                days = 30
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid days parameter', 'success': False}), 400

        stats = AttendanceQueries.get_level_statistics(level, days)

        return jsonify({
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'data': stats
        }), 200

    except SQLAlchemyError as e:
        return jsonify({'error': 'Database error occurred', 'success': False}), 500

    except Exception as e:
        return jsonify({'error': 'Unexpected error occurred', 'success': False}), 500


@instructor_bp.route('/api/student/<int:student_id>/attendance')
@instructor_required
def get_student_attendance_api(student_id):
    """
    API endpoint for individual student attendance details (used by modal).
    Filtered by level — if a level is selected, the student must belong to it
    and only their records within that level context are returned.
    """
    try:
        days = int(request.args.get('days', 30))
        level = request.args.get('level') or None

        # Fetch the student, and if a level is selected, enforce it matches
        student_query = User.query.filter_by(id=student_id, role='student')
        if level:
            student_query = student_query.filter_by(level=level)

        student = student_query.first()

        # If student not found OR their level doesn't match the selected level
        if not student:
            return jsonify({
                'error': 'Student not found for the selected level',
                'success': False
            }), 404

        cutoff_date = datetime.now() - timedelta(days=days)

        # Attendance records are already scoped to this student
        # Level filtering is enforced above on the student itself
        attendance_records = Attendance.query.filter(
            Attendance.user_id == student_id,
            Attendance.timestamp >= cutoff_date
        ).order_by(Attendance.timestamp.desc()).all()

        records = [{
            'date': record.timestamp.strftime('%Y-%m-%d'),
            'time': record.timestamp.strftime('%H:%M:%S'),
            'level': student.level,
            'ip_address': record.ip_address
        } for record in attendance_records]

        return jsonify({
            'success': True,
            'student': {
                'id': student.id,
                'name': student.name,
                'email': student.email,
                'level': student.level
            },
            'attendance_records': records,
            'total_records': len(records)
        }), 200

    except Exception as e:
        return jsonify({'error': 'Error fetching student attendance', 'success': False}), 500


@instructor_bp.route('/api/export/attendance')
@instructor_required
def export_attendance_csv():
    """
    Export attendance data as CSV.
    Filtered by level — only students belonging to the selected level
    are included in the export.
    """
    try:
        level = request.args.get('level') or None
        days = int(request.args.get('days', 30))

        # attendance_percentage_per_student already filters by level internally
        student_data = AttendanceQueries.attendance_percentage_per_student(level, days)

        si = StringIO()
        writer = csv.writer(si)

        writer.writerow([
            'Student ID', 'Student Name', 'Email', 'Level',
            'Days Attended', 'Total Days', 'Attendance %', 'Status'
        ])

        for student in student_data:
            status = 'At Risk' if student['is_below_threshold'] else 'Good'
            writer.writerow([
                student['student_id'],
                student['student_name'],
                student['student_email'],
                student['student_level'] or 'N/A',
                student['days_attended'],
                student['total_days'],
                f"{student['attendance_pct']}%",
                status
            ])

        output = si.getvalue()
        si.close()

        level_label = level if level else 'all_levels'
        filename = f"attendance_{level_label}_{days}days.csv"

        return Response(
            output,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )

    except Exception as e:
        flash('Error exporting attendance data', 'error')
        return redirect(url_for('instructor.dashboard'))


@instructor_bp.route('/level/<string:level>')
@instructor_required
def level_detail(level):
    """
    Detailed view for a specific student level.
    Replaces the old course_detail route.
    """
    try:
        days = int(request.args.get('days', 30))

        # Verify the level actually has students
        level_exists = db.session.query(User.id).filter(
            User.role == 'student',
            User.level == level
        ).first()

        if not level_exists:
            flash(f"No students found for level: {level}", "error")
            return redirect(url_for('instructor.dashboard'))

        stats = AttendanceQueries.get_level_statistics(level, days)

        return render_template('instructor/level_detail.html',
                               level=level,
                               days=days,
                               stats=stats)

    except Exception as e:
        flash('Error loading level details', 'error')
        return redirect(url_for('instructor.dashboard'))