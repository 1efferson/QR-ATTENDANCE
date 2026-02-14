from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user, login_required

# 1. Local blueprint import
from . import auth_bp 

# 2. Global app imports (db and login_manager)
from app import db

# 3. Model and Form imports
from app.models import User
from app.forms import LoginForm, RegistrationForm

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        # Redirect based on role instead of 'index'
        if current_user.role == 'instructor':
            return redirect(url_for('instructor.dashboard'))
        else:
            return redirect(url_for('student.scan'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        # Create new user instance
        user = User(
            name=form.name.data,
            email=form.email.data,
            role=form.role.data,
            level=form.level.data
        )
        user.set_password(form.password.data) # Hashes the password
        
        db.session.add(user)
        db.session.commit()
        
        flash('Your account has been created! You can now log in.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html', form=form)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        # Redirect based on role instead of 'index'
        if current_user.role == 'instructor':
            return redirect(url_for('instructor.dashboard'))
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
            else:  # student - go to scanner
                return redirect(next_page) if next_page else redirect(url_for('student.scan'))
        else:
            flash('Login Unsuccessful. Please check email and password', 'error')
            
    return render_template('auth/login.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))