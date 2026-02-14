from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError
from app.models import User

class RegistrationForm(FlaskForm):
    name = StringField('Full Name', 
                       validators=[DataRequired(), Length(min=2, max=100)])
    
    email = StringField('Email', 
                        validators=[DataRequired(), Email()])
    
    role = SelectField('Role', 
                       choices=[('student', 'Student'), ('instructor', 'Instructor')],
                       validators=[DataRequired()])
    
    # Updated levels as requested
    level = SelectField('Skill Level (Students Only)', 
                        choices=[('N/A', 'Instructor / Staff'), 
                                 ('beginner', 'Beginner'), 
                                 ('intermediate', 'Intermediate'), 
                                 ('advanced', 'Advanced')],
                        default='beginner')
    
    password = PasswordField('Password', 
                             validators=[DataRequired(), Length(min=6)])
    
    confirm_password = PasswordField('Confirm Password', 
                                     validators=[DataRequired(), EqualTo('password')])
    
    submit = SubmitField('Sign Up')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is already registered.')


class LoginForm(FlaskForm):
    email = StringField('Email', 
                        validators=[DataRequired(), Email()])
    
    password = PasswordField('Password', 
                             validators=[DataRequired()])
    
    submit = SubmitField('Login')


class QRGenerateForm(FlaskForm):
    """Form for instructors to create an attendance session."""
    course_code = StringField('Course Code (e.g., CS101)', 
                             validators=[DataRequired(), Length(min=2, max=20)])
    
    submit = SubmitField('Generate QR Code')