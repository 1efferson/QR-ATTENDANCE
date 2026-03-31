from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user, login_required
from datetime import datetime
import logging

from . import auth_bp
from app import db
from app.forms import LoginForm, RegistrationForm
from app.services.registration_service import get_active_batches, register_student
from app.models import User

#  No top-level sheet_tasks import — loaded lazily below

logger = logging.getLogger(__name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return _redirect_authenticated(current_user)

    active_batches = get_active_batches()
    form = RegistrationForm()
    form.batch.choices = [(b.id, b.name) for b in active_batches]

    if not form.validate_on_submit():
        return render_template("auth/register.html", form=form, batches=active_batches)

    result = register_student(
        email_input=form.email.data.strip().lower(),
        batch_id=form.batch.data,
        level_input=form.level.data,
        password=form.password.data,
    )

    if not result.success:
        flash(result.error, result.error_type)
        redirect_target = (
            url_for("auth.login")
            if result.error_type == "info"
            else url_for("auth.register")
        )
        return redirect(redirect_target)

    # student is saved with is_synced_to_sheets=False.
    # Celery Beat picks them up every 5 minutes and pushes the whole
    # batch in 2 API calls. Registration response is now pure DB only.
    flash(f"Registration successful! Welcome, {result.user.name}.", "success")
    return redirect(url_for("auth.login"))


def _redirect_authenticated(user):
    destinations = {
        "instructor": "instructor.dashboard",
        "admin":      "admin.dashboard",
    }
    return redirect(url_for(destinations.get(user.role, "student.scan")))

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