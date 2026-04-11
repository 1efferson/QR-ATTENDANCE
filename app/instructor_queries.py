"""
SQLAlchemy Query Utilities for Instructor Dashboard
ALL mathematical operations pushed to database level using SQLAlchemy func
Filters students by `level` and/or `batch_id` independently
Absence and Personal Time status computed inline per student
Attendance % anchored to batch's level_started_at so promotions reset the clock
student_level on Attendance ensures scans are counted for the correct level only
"""
from datetime import datetime, date, timedelta
from sqlalchemy import func, cast, Float, case, and_
from sqlalchemy import func, case, cast, Float, and_, literal
from app.models import Attendance, User, Absence, Batch, BatchSchedule
from app import db
import logging

logger = logging.getLogger(__name__)


class AttendanceQueries:
    """Centralized queries with database-level aggregations"""

    @staticmethod
    def total_checkins_today(level=None, batch_id=None):
        """
        Total check-ins for today. Optimized for index usage by avoiding
        func.date() on the column side of the filter.
        """
        # Using explicit start/end times ensures we hit the B-Tree index on 'timestamp'
        today_start = datetime.combine(date.today(), datetime.min.time())
        today_end   = datetime.combine(date.today(), datetime.max.time())

        query = db.session.query(
            func.count(Attendance.id).label('total_checkins')
        ).join(
            User, User.id == Attendance.user_id
        ).filter(
            # RANGE-BASED FILTER
            Attendance.timestamp >= today_start,
            Attendance.timestamp <= today_end,
            Attendance.is_personal_time == False,
            User.role == 'student'
        )

        if level:
            query = query.filter(User.level == level)
        if batch_id:
            query = query.filter(User.batch_id == batch_id)

        result = query.scalar()
        return result if result is not None else 0

    @staticmethod
    def total_expected_students(level=None, batch_id=None):
        """
        Total expected students.
        Optionally filtered by student level and/or batch.
        """
        query = db.session.query(
            func.count(User.id).label('total_students')
        ).filter(
            User.role == 'student'
        )

        if level:
            query = query.filter(User.level == level)
        if batch_id:
            query = query.filter(User.batch_id == batch_id)

        result = query.scalar()
        return result if result is not None else 0

    @staticmethod
    def attendance_percentage_today(level=None, batch_id=None):
        """
        Attendance percentage for today.
        Only counts non-personal-time scans.
        Optionally filtered by student level and/or batch.
        """
        today_start = datetime.combine(date.today(), datetime.min.time())
        today_end   = datetime.combine(date.today(), datetime.max.time())

        # Total expected students scalar subquery
        students_sq = db.session.query(func.count(User.id)).filter(User.role == 'student')
        if level:
            students_sq = students_sq.filter(User.level == level)
        if batch_id:
            students_sq = students_sq.filter(User.batch_id == batch_id)
        students_scalar = students_sq.scalar_subquery()

        # Total check-ins today (non-PT only) scalar subquery
        checkins_sq = db.session.query(
            func.count(Attendance.id)
        ).join(User, User.id == Attendance.user_id).filter(
            Attendance.timestamp >= today_start,
            Attendance.timestamp <= today_end,
            Attendance.is_personal_time == False,
            User.role == 'student'
        )
        if level:
            checkins_sq = checkins_sq.filter(User.level == level)
        if batch_id:
            checkins_sq = checkins_sq.filter(User.batch_id == batch_id)
        checkins_scalar = checkins_sq.scalar_subquery()

        result = db.session.query(
            case(
                (students_scalar == 0, cast(0, Float)),
                else_=(cast(checkins_scalar, Float) / cast(students_scalar, Float) * 100)
            )
        ).scalar()

        return round(result, 2) if result is not None else 0.0

    @staticmethod
    def student_average_checkin_time(level=None, days=30, batch_id=None):
        """
        Calculate each student's average check-in time over the period.
        Excludes personal time scans from the average.
        Only counts scans matching the student's current level (student_level column)
        so promoted students' old level scans don't skew their new level average.
        Optionally filtered by student level and/or batch.
        """
        cutoff_date = datetime.now() - timedelta(days=days)

        query = db.session.query(
            User.id,
            User.name,
            User.email,
            User.level,
            User.batch_id,
            func.avg(
                func.extract('hour', Attendance.timestamp) +
                (func.extract('minute', Attendance.timestamp) / 60.0)
            ).label('avg_time_decimal')
        ).join(
            Attendance, User.id == Attendance.user_id
        ).filter(
            User.role == 'student',
            Attendance.timestamp >= cutoff_date,
            Attendance.is_personal_time == False,
            Attendance.student_level == User.level
        )

        if level:
            query = query.filter(User.level == level)
        if batch_id:
            query = query.filter(User.batch_id == batch_id)

        query = query.group_by(User.id, User.name, User.email, User.level, User.batch_id)

        results = []
        for user_id, name, email, student_level, student_batch_id, avg_decimal in query.all():
            if avg_decimal is not None:
                hours   = int(avg_decimal)
                minutes = int((avg_decimal - hours) * 60)
                avg_time_str = f"{hours:02d}:{minutes:02d}"
            else:
                avg_time_str = "N/A"

            results.append({
                'student_id':       user_id,
                'student_name':     name,
                'student_email':    email,
                'student_level':    student_level,
                'student_batch_id': student_batch_id,
                'avg_time':         avg_time_str,
                'avg_time_decimal': avg_decimal
            })

        return results

    @staticmethod
    def top_5_earliest_students(level=None, target_date=None, batch_id=None):
        """
        Return the top 5 earliest students for a given day.
        Excludes personal time scans.
        Optionally filtered by student level and/or batch.
        """
        if target_date is None:
            target_date = date.today()

        day_start = datetime.combine(target_date, datetime.min.time())
        day_end   = datetime.combine(target_date, datetime.max.time())

        query = db.session.query(
            User.id,
            User.name,
            User.email,
            User.level,
            User.batch_id,
            func.min(Attendance.timestamp).label('earliest_checkin')
        ).join(
            Attendance, User.id == Attendance.user_id
        ).filter(
            User.role == 'student',
            Attendance.timestamp >= day_start,
            Attendance.timestamp <= day_end,
            Attendance.is_personal_time == False
        )

        if level:
            query = query.filter(User.level == level)
        if batch_id:
            query = query.filter(User.batch_id == batch_id)

        query = query.group_by(
            User.id, User.name, User.email, User.level, User.batch_id
        ).order_by(
            func.min(Attendance.timestamp)
        ).limit(5)

        results = []
        for user_id, name, email, student_level, student_batch_id, earliest in query.all():
            results.append({
                'student_id':       user_id,
                'student_name':     name,
                'student_email':    email,
                'student_level':    student_level,
                'student_batch_id': student_batch_id,
                'checkin_time':     earliest.strftime('%H:%M:%S') if earliest else 'N/A',
                'checkin_datetime': earliest
            })

        return results

    @staticmethod
    def attendance_percentage_per_student(level=None, days=30, batch_id=None):
        """
        Calculate attendance percentage per student.
        Optimized to use range-based joins and efficient distinct day counting.
        """
        cutoff_date = (datetime.now() - timedelta(days=days)).date()
        today       = date.today()

        batch = Batch.query.get(batch_id) if batch_id else None
        current_level = batch.current_level if batch else level

        if batch and batch.level_started_at:
            level_start_date = batch.level_started_at.date()
        else:
            level_start_date = None

        first_scan_query = db.session.query(
            func.min(Attendance.timestamp)
        ).join(User, User.id == Attendance.user_id).filter(
            Attendance.is_personal_time == False,
            User.role == 'student'
        )
        if batch_id:
            first_scan_query = first_scan_query.filter(User.batch_id == batch_id)
        if current_level:
            first_scan_query = first_scan_query.filter(Attendance.student_level == current_level)

        first_scan = first_scan_query.scalar()
        first_scan_date = first_scan.date() if first_scan else None

        candidates = [cutoff_date]
        if level_start_date: candidates.append(level_start_date)
        if first_scan_date:  candidates.append(first_scan_date)
        effective_start = max(candidates)

        if batch_id:
            schedules = BatchSchedule.query.filter_by(batch_id=batch_id).all()
            scheduled_weekdays = {s.weekday for s in schedules}
        else:
            schedules = BatchSchedule.query.all()
            scheduled_weekdays = {s.weekday for s in schedules}

        total_days = 0
        if scheduled_weekdays:
            current = effective_start
            while current <= today:
                if current.weekday() in scheduled_weekdays:
                    total_days += 1
                current += timedelta(days=1)

        effective_start_dt = datetime.combine(effective_start, datetime.min.time())

        days_attended_count = func.count(
            func.distinct(cast(Attendance.timestamp, db.Date))
        )

        attendance_pct_expr = case(
            (literal(total_days) == 0, cast(0, Float)),
            else_=(cast(days_attended_count, Float) / cast(literal(total_days), Float) * 100)
        )

        absent_today_sq = db.session.query(func.count(Absence.id)).filter(
            Absence.user_id == User.id,
            Absence.date == today
        ).correlate(User).scalar_subquery()

        pt_today_sq = db.session.query(func.count(Attendance.id)).filter(
            Attendance.user_id == User.id,
            Attendance.timestamp >= datetime.combine(today, datetime.min.time()),
            Attendance.timestamp <= datetime.combine(today, datetime.max.time()),
            Attendance.is_personal_time == True
        ).correlate(User).scalar_subquery()

        scanned_today_sq = db.session.query(func.count(Attendance.id)).filter(
            Attendance.user_id == User.id,
            Attendance.timestamp >= datetime.combine(today, datetime.min.time()),
            Attendance.timestamp <= datetime.combine(today, datetime.max.time()),
            Attendance.is_personal_time == False
        ).correlate(User).scalar_subquery()

        query = db.session.query(
            User.id, User.name, User.email, User.level, User.batch_id,
            days_attended_count.label('days_attended'),
            attendance_pct_expr.label('attendance_pct'),
            (attendance_pct_expr < 80).label('is_below_threshold'),
            (absent_today_sq > 0).label('is_absent_today'),
            (pt_today_sq > 0).label('is_pt_today'),
            (scanned_today_sq > 0).label('has_scanned_today')
        ).outerjoin(
            Attendance,
            and_(
                User.id == Attendance.user_id,
                Attendance.timestamp >= effective_start_dt,
                Attendance.is_personal_time == False,
                Attendance.student_level == User.level
            )
        ).filter(User.role == 'student')

        if level:
            query = query.filter(User.level == level)
        if batch_id:
            query = query.filter(User.batch_id == batch_id)

        query = query.group_by(User.id, User.name, User.email, User.level, User.batch_id)

        results = []
        for row in query.all():
            results.append({
                'student_id':         row[0],
                'student_name':       row[1],
                'student_email':      row[2],
                'student_level':      row[3],
                'student_batch_id':   row[4],
                'days_attended':      row[5] or 0,
                'attendance_pct':     round(row[6], 2) if row[6] is not None else 0.0,
                'total_days':         total_days,
                'is_below_threshold': bool(row[7]),
                'is_absent_today':    bool(row[8]),
                'is_pt_today':        bool(row[9]),
                'has_scanned_today':  bool(row[10])
            })
        return results
        
    @staticmethod
    def students_below_threshold(threshold=80, level=None, days=30, batch_id=None):
        """
        Flag students below the given attendance threshold.
        Excludes personal time from attendance count.
        Only counts scans matching the student's current level (student_level column)
        so promoted students' old level scans don't inflate their new level %.
        Optionally filtered by student level and/or batch.
        """
        cutoff_date = datetime.now() - timedelta(days=days)

        # total_days anchoring via level_started_at
        all_students = AttendanceQueries.attendance_percentage_per_student(
            level=level, days=days, batch_id=batch_id
        )

        return [s for s in all_students if s['attendance_pct'] < threshold]

    @staticmethod
    def todays_absences(level=None, batch_id=None):
        """
        Returns students marked absent today from the Absence table.
        Populated by the nightly scheduler at 9pm.
        Optionally filtered by level and/or batch.
        """
        today = date.today()

        query = db.session.query(
            Absence,
            User.name.label('student_name'),
            User.email.label('student_email'),
            User.level.label('student_level'),
            User.batch_id.label('student_batch_id')
        ).join(
            User, User.id == Absence.user_id
        ).filter(
            Absence.date == today,
            User.role == 'student'
        )

        if level:
            query = query.filter(User.level == level)
        if batch_id:
            query = query.filter(Absence.batch_id == batch_id)

        query = query.order_by(User.name)

        results = []
        for absence, name, email, student_level, student_batch_id in query.all():
            results.append({
                'absence_id':       absence.id,
                'student_id':       absence.user_id,
                'student_name':     name,
                'student_email':    email,
                'student_level':    student_level,
                'student_batch_id': student_batch_id,
                'date':             absence.date,
                'notified':         absence.notified
            })

        return results

    @staticmethod
    def todays_personal_time(level=None, batch_id=None):
        """
        Returns students who scanned today on a non-class day (P.T).
        Optionally filtered by level and/or batch.
        """
        today_start = datetime.combine(date.today(), datetime.min.time())
        today_end   = datetime.combine(date.today(), datetime.max.time())

        query = db.session.query(
            User.id,
            User.name,
            User.email,
            User.level,
            User.batch_id,
            Attendance.timestamp
        ).join(
            Attendance, User.id == Attendance.user_id
        ).filter(
            User.role == 'student',
            Attendance.timestamp >= today_start,
            Attendance.timestamp <= today_end,
            Attendance.is_personal_time == True
        )

        if level:
            query = query.filter(User.level == level)
        if batch_id:
            query = query.filter(User.batch_id == batch_id)

        query = query.order_by(User.name)

        results = []
        for user_id, name, email, student_level, student_batch_id, timestamp in query.all():
            results.append({
                'student_id':       user_id,
                'student_name':     name,
                'student_email':    email,
                'student_level':    student_level,
                'student_batch_id': student_batch_id,
                'checkin_time':     timestamp.strftime('%H:%M:%S')
            })

        return results

    @staticmethod
    def get_level_statistics(level, days=30, batch_id=None):
        """
        Comprehensive statistics for a given level/batch combination.
        Pass level=None for all levels; batch_id=None for all batches.
        """
        return {
            'level':                   level,
            'today_checkins':          AttendanceQueries.total_checkins_today(level, batch_id),
            'today_percentage':        AttendanceQueries.attendance_percentage_today(level, batch_id),
            'expected_students':       AttendanceQueries.total_expected_students(level, batch_id),
            'top_5_earliest':          AttendanceQueries.top_5_earliest_students(level, batch_id=batch_id),
            'average_checkin_times':   AttendanceQueries.student_average_checkin_time(level, days, batch_id),
            'students_below_80':       AttendanceQueries.students_below_threshold(80, level, days, batch_id),
            'all_student_percentages': AttendanceQueries.attendance_percentage_per_student(level, days, batch_id),
            'period_days':             days
        }