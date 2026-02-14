from flask import render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from . import instructor_bp
#from app.models import Attendance  # use it for instructor dashboard later

@instructor_bp.route('/dashboard')
@login_required
def dashboard():
    # Only allow users with the 'instructor' role
    if current_user.role != 'instructor':
        flash("Access denied: Instructors only.", "error")
        return redirect(url_for('auth.login'))
        
    return render_template('instructor/dashboard.html')

@instructor_bp.route('/generate-qr')
@login_required
def generate_qr():
    if current_user.role != 'instructor':
        return redirect(url_for('auth.login'))
        
    return render_template('instructor/generate_qr.html')