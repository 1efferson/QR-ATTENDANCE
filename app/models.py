from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager

@login_manager.user_loader
def load_user(user_id):
    """Flask-Login helper to retrieve a user from our db."""
    return User.query.get(int(user_id))


# ============================================================================
# MODEL: Batch
# ============================================================================
class Batch(db.Model):
    """
    Represents a cohort/batch of students (e.g., 'Code 1&2', 'Code 3&4')
    Contains approved student names and progresses through levels.
    """
    __tablename__ = 'batches'

    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(100), unique=True, nullable=False)
    description     = db.Column(db.Text, nullable=True)
    current_level   = db.Column(db.String(50), default='beginner')  # beginner, intermediate, advanced
    is_active       = db.Column(db.Boolean, default=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    # Tracks when the current level started — set on promotion and on batch creation.
    # Used to anchor attendance % calculations so students aren't penalised
    # for days before their current level began.
    level_started_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)

    # Relationships
    students       = db.relationship('User', backref='batch', lazy=True, foreign_keys='User.batch_id')
    approved_names = db.relationship('ApprovedStudent', backref='batch', lazy=True, cascade='all, delete-orphan')
    schedules      = db.relationship('BatchSchedule', backref='batch', lazy=True, cascade='all, delete-orphan')
    absences       = db.relationship('Absence', backref='batch', lazy=True)

    def __repr__(self):
        return f'<Batch {self.name} - {self.current_level}>'

    @property
    def full_name(self):
        """Returns: 'Code 1&2 - Beginner'"""
        return f"{self.name} - {self.current_level.capitalize()}"

    def is_student_approved(self, name):
        """Check if a student name is approved for this batch."""
        name_normalized = name.strip().lower()
        return any(
            approved.name.strip().lower() == name_normalized
            for approved in self.approved_names
        )

    def is_class_day(self, date):
        """
        Check if a given date is a scheduled class day for this batch.
        Returns True if the weekday matches any BatchSchedule entry.
        Weekday: 0=Monday, 1=Tuesday, ..., 6=Sunday
        """
        weekday = date.weekday()
        return any(s.weekday == weekday for s in self.schedules)

    def promote_to_next_level(self):
        """
        Move entire batch to next level.
        Resets level_started_at to now so attendance calculations
        start fresh from the promotion date.
        """
        level_progression = {
            'beginner':     'intermediate',
            'intermediate': 'advanced',
            'advanced':     'advanced'  # Stays at advanced
        }
        next_level = level_progression.get(self.current_level)
        if next_level and next_level != self.current_level:
            old_level = self.current_level
            self.current_level = next_level
            self.level_started_at = datetime.utcnow()  # reset the clock for the new level
            for student in self.students:
                student.level = next_level
            return True, old_level, next_level
        return False, self.current_level, self.current_level


# ============================================================================
# MODEL: BatchSchedule
# ============================================================================
class BatchSchedule(db.Model):
    """
    Defines which days of the week a batch is scheduled to attend class.
    One row per class day. e.g. batch 1 meets Monday (0) and Wednesday (2).
    Admin sets this when creating or editing a batch.
    """
    __tablename__ = 'batch_schedules'

    id       = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('batches.id', name='fk_batch_schedule_batch_id'), nullable=False)
    weekday  = db.Column(db.Integer, nullable=False)  # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun

    # Prevent duplicate days per batch
    __table_args__ = (
        db.UniqueConstraint('batch_id', 'weekday', name='unique_batch_weekday'),
    )

    @property
    def weekday_name(self):
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        return days[self.weekday]

    def __repr__(self):
        return f'<BatchSchedule batch={self.batch_id} day={self.weekday_name}>'


# ============================================================================
# MODEL: ApprovedStudent
# ============================================================================
class ApprovedStudent(db.Model):
    """
    List of approved student names for each batch.
    Students can only register if their name is on this list.
    """
    __tablename__ = 'approved_students'

    id                 = db.Column(db.Integer, primary_key=True)
    batch_id           = db.Column(db.Integer, db.ForeignKey('batches.id', name='fk_approved_student_batch_id'), nullable=True)
    name               = db.Column(db.String(100), nullable=False)
    email              = db.Column(db.String(120), nullable=True)
    is_registered      = db.Column(db.Boolean, default=False)
    registered_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    registered_at      = db.Column(db.DateTime, nullable=True)
    added_at           = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('batch_id', 'name', name='unique_batch_student'),
    )

    def __repr__(self):
        return f'<ApprovedStudent {self.name} for Batch {self.batch_id}>'


# ============================================================================
# MODEL: User
# ============================================================================
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    name          = db.Column(db.String(100), nullable=False)
    level         = db.Column(db.String(50), nullable=True)   # beginner, intermediate, advanced
    role          = db.Column(db.String(20), default='student', nullable=False)  # student, instructor, admin
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    batch_id      = db.Column(db.Integer, db.ForeignKey('batches.id', name='fk_user_batch_id'), nullable=True)

    # Relationships
    attendances = db.relationship('Attendance', backref='student', lazy=True)
    absences    = db.relationship('Absence', backref='student', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.email} ({self.role})>'


# ============================================================================
# MODEL: Attendance
# ============================================================================
class Attendance(db.Model):
    __tablename__ = 'attendance'

    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_code      = db.Column(db.String(20), nullable=False)
    timestamp        = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address       = db.Column(db.String(45), nullable=True)
    user_agent       = db.Column(db.String(256), nullable=True)

    # True if the scan happened on a non-class day — shown as P.T (Personal Time)
    is_personal_time = db.Column(db.Boolean, default=False, nullable=False)

    # Snapshot of the student's level at the time of scan.
    # Ensures attendance history stays separated by level even after promotion.
    # e.g. beginner scans won't count toward intermediate attendance %.
    student_level    = db.Column(db.String(50), nullable=True)

    def __repr__(self):
        pt = ' [P.T]' if self.is_personal_time else ''
        return f'<Attendance {self.user_id} - {self.course_code}{pt}>'


# ============================================================================
# MODEL: Absence
# ============================================================================
class Absence(db.Model):
    """
    Records a student as absent on a scheduled class day.
    Created by the daily scheduled job for any student who did not scan
    on a day their batch was supposed to be in class.
    """
    __tablename__ = 'absences'

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    batch_id     = db.Column(db.Integer, db.ForeignKey('batches.id', name='fk_absence_batch_id'), nullable=False)
    date         = db.Column(db.Date, nullable=False)             # The class day they missed
    notified     = db.Column(db.Boolean, default=False)           # Whether WhatsApp/email was sent
    notified_at  = db.Column(db.DateTime, nullable=True)          # When notification was sent
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    # Prevent duplicate absence records for the same student on the same day
    __table_args__ = (
        db.UniqueConstraint('user_id', 'date', name='unique_student_absence_date'),
    )

    def __repr__(self):
        return f'<Absence user={self.user_id} date={self.date}>'


# ============================================================================
# MODEL: BlockedAttempt
# ============================================================================
class BlockedAttempt(db.Model):
    __tablename__ = 'blocked_attempts'

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    ip_address     = db.Column(db.String(45), nullable=False)
    user_agent     = db.Column(db.String(256), nullable=True)
    reason         = db.Column(db.String(100), nullable=False)  # 'invalid_ip', 'invalid_qr', etc.
    timestamp      = db.Column(db.DateTime, default=datetime.utcnow)
    attempted_data = db.Column(db.JSON, nullable=True)