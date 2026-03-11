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
    Contains approved student names and progresses through levels
    """
    __tablename__ = 'batches'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)  # "Code 1&2", "Code 3&4"
    description = db.Column(db.Text, nullable=True)
    current_level = db.Column(db.String(50), default='beginner')  # beginner, intermediate, advanced
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    students = db.relationship('User', backref='batch', lazy=True, foreign_keys='User.batch_id')
    approved_names = db.relationship('ApprovedStudent', backref='batch', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Batch {self.name} - {self.current_level}>'
    
    @property
    def full_name(self):
        """Returns: 'Code 1&2 - Beginner'"""
        return f"{self.name} - {self.current_level.capitalize()}"
    
    def is_student_approved(self, name):
        """Check if a student name is approved for this batch"""
        name_normalized = name.strip().lower()
        return any(
            approved.name.strip().lower() == name_normalized 
            for approved in self.approved_names
        )
    
    def promote_to_next_level(self):
        """Move entire batch to next level"""
        level_progression = {
            'beginner': 'intermediate',
            'intermediate': 'advanced',
            'advanced': 'advanced'  # Stay at advanced
        }
        
        next_level = level_progression.get(self.current_level)
        if next_level and next_level != self.current_level:
            old_level = self.current_level
            self.current_level = next_level
            
            # Update all registered students in this batch
            for student in self.students:
                student.level = next_level
            
            return True, old_level, next_level
        return False, self.current_level, self.current_level


# ============================================================================
# MODEL: ApprovedStudent
# ============================================================================
class ApprovedStudent(db.Model):
    """
    List of approved student names for each batch
    Students can only register if their name is on this list
    """
    __tablename__ = 'approved_students'
    
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer,db.ForeignKey('batches.id', name='fk_users_batch_id'),nullable=True)
    name = db.Column(db.String(100), nullable=False)  # Student's full name
    email = db.Column(db.String(120), nullable=True)  # Optional: expected email
    
    # Track registration status
    is_registered = db.Column(db.Boolean, default=False)
    registered_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    registered_at = db.Column(db.DateTime, nullable=True)
    
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Composite unique constraint
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

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    level = db.Column(db.String(50), nullable=True)  # "beginner", "intermediate", "advanced"
    role = db.Column(db.String(20), default='student', nullable=False)  # 'student', 'instructor', 'admin'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Link student to their assigned batch
    batch_id = db.Column(db.Integer,db.ForeignKey('batches.id', name='fk_users_batch_id'),nullable=True)
    
    # Relationships
    attendances = db.relationship('Attendance', backref='student', lazy=True)
    # batch relationship defined in Batch model

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.email} ({self.role})>'

# ============================================================================
# MODEL: attendance 
# ============================================================================
class Attendance(db.Model):
    __tablename__ = 'attendance'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_code = db.Column(db.String(20), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    # New fields for IP tracking
    ip_address = db.Column(db.String(45), nullable=True)  # IPv6 can be up to 45 chars
    user_agent = db.Column(db.String(256), nullable=True)  # Browser info
    
    def __repr__(self):
        return f'<Attendance {self.user_id} - {self.course_code}>'


# ============================================================================
# MODEL: blocked_attempts
# ============================================================================
class BlockedAttempt(db.Model):
    __tablename__ = 'blocked_attempts'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    ip_address = db.Column(db.String(45), nullable=False)
    user_agent = db.Column(db.String(256), nullable=True)
    reason = db.Column(db.String(100), nullable=False)  # 'invalid_ip', 'invalid_qr', etc.
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    attempted_data = db.Column(db.JSON, nullable=True)  # Store what they tried to submit    