from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager

@login_manager.user_loader
def load_user(user_id):
    """Flask-Login helper to retrieve a user from our db."""
    return User.query.get(int(user_id))

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    level = db.Column(db.String(50), nullable=True)  # e.g., "beginner", "intermediate"
    role = db.Column(db.String(20), default='student', nullable=False) # 'student' or 'instructor'
    
    # Relationships
    attendances = db.relationship('Attendance', backref='student', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.email} ({self.role})>'

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

# New model for tracking blocked attempts
class BlockedAttempt(db.Model):
    __tablename__ = 'blocked_attempts'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    ip_address = db.Column(db.String(45), nullable=False)
    user_agent = db.Column(db.String(256), nullable=True)
    reason = db.Column(db.String(100), nullable=False)  # 'invalid_ip', 'invalid_qr', etc.
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    attempted_data = db.Column(db.JSON, nullable=True)  # Store what they tried to submit