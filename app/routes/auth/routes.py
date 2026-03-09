from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user, login_required
from datetime import datetime

# 1. Local blueprint import
from . import auth_bp

# 2. Global app imports
from app import db

# 3. Model and Form imports
from app.models import User, Batch, ApprovedStudent
from app.forms import LoginForm, RegistrationForm


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        if current_user.role == 'instructor':
            return redirect(url_for('instructor.dashboard'))
        elif current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('student.scan'))
    
    form = RegistrationForm()
    
    # Populate batch choices dynamically
    active_batches = Batch.query.filter_by(is_active=True).all()
    form.batch.choices = [(b.id, b.name) for b in active_batches]
    
    if form.validate_on_submit():
        # Get form data
        name = form.name.data.strip()
        email = form.email.data.strip()
        batch_id = form.batch.data
        level = form.level.data
        password = form.password.data
        
        # Get selected batch
        batch = Batch.query.get(batch_id)
        if not batch:
            flash('Invalid batch selected', 'error')
            return redirect(url_for('auth.register'))
        
        # VALIDATION 1: Find the approved record
        approved_record = ApprovedStudent.query.filter(
            ApprovedStudent.batch_id == batch_id,
            db.func.lower(ApprovedStudent.name) == name.lower()
        ).first()
        
        if not approved_record:
            flash(f'Your name is not on the approved list for {batch.name}. Please contact admin.', 'error')
            return redirect(url_for('auth.register'))
        
        # VALIDATION 2: Check if this approved name has already been used to register
        if approved_record.is_registered:
            flash(f'This name has already been used to register. If this is you, please login. Otherwise, contact admin.', 'error')
            return redirect(url_for('auth.login'))
        
        # VALIDATION 3: Check if level matches batch's current level
        if level != batch.current_level:
            flash(f'{batch.name} is currently at {batch.current_level} level. Please select {batch.current_level}.', 'error')
            return redirect(url_for('auth.register'))
        
        # VALIDATION 4: Check if email already registered
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email already registered. Please login.', 'error')
            return redirect(url_for('auth.login'))
        
        # CREATE NEW USER
        user = User(
            name=name,
            email=email,
            role='student',
            level=level,
            batch_id=batch_id
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.flush()  # Get user.id before committing
        
        # UPDATE APPROVED STUDENT RECORD
        approved_record.is_registered = True
        approved_record.registered_user_id = user.id
        approved_record.registered_at = datetime.utcnow()
        if not approved_record.email:
            approved_record.email = email
        
        db.session.commit()
        
        flash(f'Registration successful! Welcome to {batch.name} - {level.capitalize()}', 'success')
        return redirect(url_for('auth.login'))
    
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