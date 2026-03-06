"""
SQLAlchemy Query Utilities for Instructor Dashboard
ALL mathematical operations pushed to database level using SQLAlchemy func
Optimized for PostgreSQL performance with reusable query labels
Filters students by `level` instead of course_code
"""
from datetime import datetime, date, timedelta
from sqlalchemy import func, cast, Float, case, and_
from app.models import Attendance, User
from app import db


class AttendanceQueries:
    """Centralized queries with database-level aggregations"""

    @staticmethod
    def total_checkins_today(level=None):
        """
        Total check-ins for today
        Database does: COUNT aggregation
        Optionally filtered by student level
        """
        today_start = datetime.combine(date.today(), datetime.min.time())
        today_end = datetime.combine(date.today(), datetime.max.time())

        query = db.session.query(
            func.count(Attendance.id).label('total_checkins')
        ).join(
            User, User.id == Attendance.user_id
        ).filter(
            Attendance.timestamp >= today_start,
            Attendance.timestamp <= today_end,
            User.role == 'student'
        )

        if level:
            query = query.filter(User.level == level)

        result = query.scalar()
        return result if result is not None else 0

    @staticmethod
    def total_expected_students(level=None):
        """
        Total expected students
        Database does: COUNT aggregation
        Optionally filtered by student level
        """
        query = db.session.query(
            func.count(User.id).label('total_students')
        ).filter(
            User.role == 'student'
        )

        if level:
            query = query.filter(User.level == level)

        result = query.scalar()
        return result if result is not None else 0

    @staticmethod
    def attendance_percentage_today(level=None):
        """
        Attendance percentage for today
        Database does: COUNT, division, multiplication (percentage calculation)
        Optionally filtered by student level
        """
        today_start = datetime.combine(date.today(), datetime.min.time())
        today_end = datetime.combine(date.today(), datetime.max.time())

        # .scalar_subquery() returns a single inline value — no FROM entry, no cartesian product
        students_sq = db.session.query(func.count(User.id)).filter(User.role == 'student')
        if level:
            students_sq = students_sq.filter(User.level == level)
        students_scalar = students_sq.scalar_subquery()

        checkins_sq = db.session.query(
            func.count(Attendance.id)
        ).join(User, User.id == Attendance.user_id).filter(
            Attendance.timestamp >= today_start,
            Attendance.timestamp <= today_end,
            User.role == 'student'
        )
        if level:
            checkins_sq = checkins_sq.filter(User.level == level)
        checkins_scalar = checkins_sq.scalar_subquery()

        result = db.session.query(
            case(
                (students_scalar == 0, cast(0, Float)),
                else_=(cast(checkins_scalar, Float) / cast(students_scalar, Float) * 100)
            )
        ).scalar()

        return round(result, 2) if result is not None else 0.0

    @staticmethod
    def student_average_checkin_time(level=None, days=30):
        """
        Calculate each student's average check-in time
        Database does: EXTRACT, AVG, all time calculations
        Optionally filtered by student level
        """
        cutoff_date = datetime.now() - timedelta(days=days)

        query = db.session.query(
            User.id,
            User.name,
            User.email,
            User.level,
            func.avg(
                func.extract('hour', Attendance.timestamp) +
                (func.extract('minute', Attendance.timestamp) / 60.0)
            ).label('avg_time_decimal')
        ).join(
            Attendance, User.id == Attendance.user_id
        ).filter(
            User.role == 'student',
            Attendance.timestamp >= cutoff_date
        )

        if level:
            query = query.filter(User.level == level)

        query = query.group_by(User.id, User.name, User.email, User.level)

        results = []
        for user_id, name, email, student_level, avg_decimal in query.all():
            if avg_decimal is not None:
                hours = int(avg_decimal)
                minutes = int((avg_decimal - hours) * 60)
                avg_time_str = f"{hours:02d}:{minutes:02d}"
            else:
                avg_time_str = "N/A"

            results.append({
                'student_id': user_id,
                'student_name': name,
                'student_email': email,
                'student_level': student_level,
                'avg_time': avg_time_str,
                'avg_time_decimal': avg_decimal
            })

        return results

    @staticmethod
    def top_5_earliest_students(level=None, target_date=None):
        """
        Return the top 5 earliest students
        Database does: MIN, GROUP BY, ORDER BY, LIMIT
        Optionally filtered by student level
        """
        if target_date is None:
            target_date = date.today()

        day_start = datetime.combine(target_date, datetime.min.time())
        day_end = datetime.combine(target_date, datetime.max.time())

        query = db.session.query(
            User.id,
            User.name,
            User.email,
            User.level,
            func.min(Attendance.timestamp).label('earliest_checkin')
        ).join(
            Attendance, User.id == Attendance.user_id
        ).filter(
            User.role == 'student',
            Attendance.timestamp >= day_start,
            Attendance.timestamp <= day_end
        )

        if level:
            query = query.filter(User.level == level)

        query = query.group_by(
            User.id, User.name, User.email, User.level
        ).order_by(
            func.min(Attendance.timestamp)
        ).limit(5)

        results = []
        for user_id, name, email, student_level, earliest in query.all():
            results.append({
                'student_id': user_id,
                'student_name': name,
                'student_email': email,
                'student_level': student_level,
                'checkin_time': earliest.strftime('%H:%M:%S') if earliest else 'N/A',
                'checkin_datetime': earliest
            })

        return results

    @staticmethod
    def attendance_percentage_per_student(level=None, days=30):
        """
        Calculate attendance percentage per student.
        Database does: COUNT DISTINCT dates, division, percentage calculation.

        total_days is now a .scalar_subquery() — an inline value in the
        SELECT clause, not a joined table — eliminating the cartesian product.
        """
        cutoff_date = datetime.now() - timedelta(days=days)

        # Counts unique attendance days across the whole level (or all students).
        # .scalar_subquery() = single inline value, no FROM entry, no cartesian product.
        total_days_sq = db.session.query(
            func.count(func.distinct(func.date(Attendance.timestamp)))
        ).join(User, User.id == Attendance.user_id).filter(
            Attendance.timestamp >= cutoff_date,
            User.role == 'student'
        )
        if level:
            total_days_sq = total_days_sq.filter(User.level == level)
        total_days_scalar = total_days_sq.scalar_subquery()

        # Per-student days attended (evaluated in GROUP BY context)
        days_attended_count = func.count(func.distinct(func.date(Attendance.timestamp)))

        attendance_pct_expr = case(
            (total_days_scalar == 0, cast(0, Float)),
            else_=(cast(days_attended_count, Float) / cast(total_days_scalar, Float) * 100)
        )

        query = db.session.query(
            User.id,
            User.name,
            User.email,
            User.level,
            days_attended_count.label('days_attended'),
            total_days_scalar.label('total_days'),   # scalar inline — not a joined column
            attendance_pct_expr.label('attendance_pct'),
            (attendance_pct_expr < 60).label('is_below_threshold')
        ).outerjoin(
            Attendance,
            and_(
                User.id == Attendance.user_id,
                Attendance.timestamp >= cutoff_date
            )
        ).filter(User.role == 'student')

        if level:
            query = query.filter(User.level == level)

        # total_days_scalar is NOT in GROUP BY — it is a scalar, not a grouped column
        query = query.group_by(
            User.id, User.name, User.email, User.level
        ).order_by(attendance_pct_expr.desc())

        results = []
        for user_id, name, email, student_level, days_attended, total_days, pct, below_threshold in query.all():
            results.append({
                'student_id': user_id,
                'student_name': name,
                'student_email': email,
                'student_level': student_level,
                'attendance_pct': round(pct, 2) if pct is not None else 0.0,
                'days_attended': days_attended or 0,
                'total_days': total_days or 0,
                'is_below_threshold': below_threshold
            })

        return results

    @staticmethod
    def students_below_threshold(threshold=60, level=None, days=30):
        """
        Flag students below attendance threshold.
        Database does: HAVING clause filter.

        Same .scalar_subquery() fix as attendance_percentage_per_student —
        eliminates the cartesian product warning.
        """
        cutoff_date = datetime.now() - timedelta(days=days)

        total_days_sq = db.session.query(
            func.count(func.distinct(func.date(Attendance.timestamp)))
        ).join(User, User.id == Attendance.user_id).filter(
            Attendance.timestamp >= cutoff_date,
            User.role == 'student'
        )
        if level:
            total_days_sq = total_days_sq.filter(User.level == level)
        total_days_scalar = total_days_sq.scalar_subquery()

        days_attended_count = func.count(func.distinct(func.date(Attendance.timestamp)))

        attendance_pct_expr = case(
            (total_days_scalar == 0, cast(0, Float)),
            else_=(cast(days_attended_count, Float) / cast(total_days_scalar, Float) * 100)
        )

        query = db.session.query(
            User.id,
            User.name,
            User.email,
            User.level,
            days_attended_count.label('days_attended'),
            total_days_scalar.label('total_days'),   # scalar inline — not a joined column
            attendance_pct_expr.label('attendance_pct')
        ).outerjoin(
            Attendance,
            and_(
                User.id == Attendance.user_id,
                Attendance.timestamp >= cutoff_date
            )
        ).filter(User.role == 'student')

        if level:
            query = query.filter(User.level == level)

        # total_days_scalar NOT in GROUP BY — it's a scalar
        query = query.group_by(
            User.id, User.name, User.email, User.level
        ).having(
            attendance_pct_expr < threshold
        ).order_by(
            attendance_pct_expr.asc()
        )

        results = []
        for user_id, name, email, student_level, days_attended, total_days, pct in query.all():
            results.append({
                'student_id': user_id,
                'student_name': name,
                'student_email': email,
                'student_level': student_level,
                'attendance_pct': round(pct, 2) if pct is not None else 0.0,
                'days_attended': days_attended or 0,
                'total_days': total_days or 0,
                'is_below_threshold': True
            })

        return results

    @staticmethod
    def get_level_statistics(level, days=30):
        """
        Comprehensive statistics for a given student level for the dashboard.
        All aggregations happen at database level.
        Pass level=None to get stats across all levels.
        """
        return {
            'level': level,
            'today_checkins': AttendanceQueries.total_checkins_today(level),
            'today_percentage': AttendanceQueries.attendance_percentage_today(level),
            'expected_students': AttendanceQueries.total_expected_students(level),
            'top_5_earliest': AttendanceQueries.top_5_earliest_students(level),
            'average_checkin_times': AttendanceQueries.student_average_checkin_time(level, days),
            'students_below_60': AttendanceQueries.students_below_threshold(60, level, days),
            'all_student_percentages': AttendanceQueries.attendance_percentage_per_student(level, days),
            'period_days': days
        }