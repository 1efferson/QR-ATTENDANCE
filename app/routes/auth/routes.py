from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user, login_required
from datetime import datetime
from app.sheets_sync import append_student_to_sheet
import logging

# 1. Local blueprint import
from . import auth_bp

# 2. Global app imports
from app import db

# 3. Model and Form imports
from app.models import User, Batch, ApprovedStudent
from app.forms import LoginForm, RegistrationForm

# Initialize logger for this module
logger = logging.getLogger(__name__)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # 1. Redirect if already logged in
    if current_user.is_authenticated:
        if current_user.role == 'instructor':
            return redirect(url_for('instructor.dashboard'))
        elif current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('student.scan'))
    
    form = RegistrationForm()
    
    # 2. Populate batch choices dynamically
    try:
        active_batches = Batch.query.filter_by(is_active=True).all()
        form.batch.choices = [(b.id, b.name) for b in active_batches]
    except Exception as e:
        logger.error(f"Error fetching active batches: {e}")
        flash("System error loading registration. Please try again later.", "error")
        return redirect(url_for('auth.login'))
    
    if form.validate_on_submit():
        # Clean and normalize input data
        name_input = form.name.data.strip()
        email_input = form.email.data.strip().lower()
        batch_id = form.batch.data
        level_input = form.level.data
        password = form.password.data
        
        # 3. Fetch Batch details
        batch = Batch.query.get(batch_id)
        if not batch:
            logger.warning(f"Registration attempt for non-existent batch ID: {batch_id}")
            flash('Invalid batch selected.', 'error')
            return redirect(url_for('auth.register'))
        
        # 4. VALIDATION: Find approved record by EMAIL
        # This is the primary verification key.
        approved_record = ApprovedStudent.query.filter(
            ApprovedStudent.batch_id == batch_id,
            db.func.lower(ApprovedStudent.email) == email_input
        ).first()
        
        if not approved_record:
            logger.info(f"Unauthorized registration attempt: {email_input} for batch {batch.name}")
            flash(f'The email {email_input} is not on the approved list for {batch.name}. Please contact your administrator.', 'error')
            return redirect(url_for('auth.register'))
        
        # 5. VALIDATION: Check if already registered
        if approved_record.is_registered:
            logger.info(f"Duplicate registration attempt for email: {email_input}")
            flash('This account is already registered. Please log in.', 'info')
            return redirect(url_for('auth.login'))
        
        # 6. VALIDATION: Level check
        if level_input != batch.current_level:
            logger.warning(f"Level mismatch: User {email_input} tried {level_input}, Batch is {batch.current_level}")
            flash(f'Registration failed: {batch.name} is currently at {batch.current_level.capitalize()} level.', 'error')
            return redirect(url_for('auth.register'))
        
        # 7. VALIDATION: Global User table check (Safety net)
        existing_user = User.query.filter_by(email=email_input).first()
        if existing_user:
            logger.error(f"Database Inconsistency: {email_input} is in User table but not marked as registered in ApprovedStudent.")
            flash('Email already in use. Please login or contact support.', 'error')
            return redirect(url_for('auth.login'))
        
        try:
            # 8. CREATE NEW USER
            # Use the 'approved_record.name' (Admin spelling) for consistency in reports
            user = User(
                name=approved_record.name, 
                email=email_input,
                role='student',
                level=level_input,
                batch_id=batch_id
            )
            user.set_password(password)
            
            db.session.add(user)
            db.session.flush() # Get user.id for the approved_record link
            
            # 9. UPDATE APPROVED STUDENT RECORD
            approved_record.is_registered = True
            approved_record.registered_user_id = user.id
            approved_record.registered_at = datetime.utcnow()
            
            db.session.commit()
            logger.info(f"Successfully registered new student: {user.email} (ID: {user.id})")
            
            # 10. GOOGLE SHEETS SYNC
            try:
                append_student_to_sheet(user)
            except Exception as sheet_err:
                # Log but don't stop the user's registration progress
                logger.error(f"Google Sheets Sync Failed for {user.email}: {sheet_err}")

            flash(f'Registration successful! Welcome to {batch.name}, {user.name}.', 'success')
            return redirect(url_for('auth.login'))

        except Exception as db_err:
            db.session.rollback()
            logger.critical(f"Database crash during registration for {email_input}: {db_err}")
            flash("A critical error occurred. Please try again or contact support.", "error")
            return redirect(url_for('auth.register'))
    
    return render_template('auth/register.html', form=form, batches=active_batches)

# LOGIN ROUTE
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login route"""
    if current_user.is_authenticated:
        # Redirect based on role
        if current_user.role == 'instructor':
            return redirect(url_for('instructor.dashboard'))
        elif current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        else:  # student
            return redirect(url_for('student.scan'))
        
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash('Login Successful!', 'success')
            
            # Check for 'next' parameter (if they were redirected to login)
            next_page = request.args.get('next')
            
            # Role-based redirect
            if user.role == 'instructor':
                return redirect(next_page) if next_page else redirect(url_for('instructor.dashboard'))
            elif user.role == 'admin':
                return redirect(next_page) if next_page else redirect(url_for('admin.dashboard'))
            else:  # student
                return redirect(next_page) if next_page else redirect(url_for('student.scan'))
        else:
            flash('Login Unsuccessful. Please check email and password', 'error')
            
    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    """Logout route"""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Allow any logged-in user to change their password"""
    if request.method == 'POST':
        current_password = request.form.get('current_password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        # Validation
        if not all([current_password, new_password, confirm_password]):
            flash('All fields are required', 'error')
            return redirect(url_for('auth.change_password'))
        
        # Check current password
        if not current_user.check_password(current_password):
            flash('Current password is incorrect', 'error')
            return redirect(url_for('auth.change_password'))
        
        # Check new passwords match
        if new_password != confirm_password:
            flash('New passwords do not match', 'error')
            return redirect(url_for('auth.change_password'))
        
        # Check password length
        if len(new_password) < 6:
            flash('New password must be at least 6 characters', 'error')
            return redirect(url_for('auth.change_password'))
        
        # Check new password is different from current
        if current_password == new_password:
            flash('New password must be different from current password', 'error')
            return redirect(url_for('auth.change_password'))
        
        # Update password
        current_user.set_password(new_password)
        db.session.commit()
        
        flash('✓ Password changed successfully!', 'success')
        
        # Redirect based on role
        if current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        elif current_user.role == 'instructor':
            return redirect(url_for('instructor.dashboard'))
        else:
            return redirect(url_for('student.scan'))
    
    return render_template('auth/change_password.html')