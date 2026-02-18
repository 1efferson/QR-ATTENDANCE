
from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from . import student_bp
from app import db
from app.models import Attendance
from datetime import datetime

@student_bp.route('/scan')
@login_required
def scan():
    """QR Code scanner page for students."""
    if current_user.role != 'student':
        flash("Access denied: Students only.", "error")
        return redirect(url_for('instructor.dashboard'))
    
    return render_template('student/scan.html')

@student_bp.route('/mark-attendance', methods=['POST'])
@login_required
def mark_attendance():
    if current_user.role != 'student':
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    
    data = request.get_json()
    # Accept either the scanned QR text or the manually typed code
    scanned_code = data.get('qr_content')
    
    # Get the master secret from app config (loaded from .env)
    master_secret = current_app.config.get('MASTER_QR_SECRET')
    
    if not scanned_code or scanned_code.strip() != master_secret:
        return jsonify({'success': False, 'message': 'Invalid QR Code or Manual Code'}), 400
    
    # Check if they already signed in today
    today = datetime.utcnow().date()
    existing = Attendance.query.filter(
        Attendance.user_id == current_user.id,
        db.func.date(Attendance.timestamp) == today
    ).first()
    
    if existing:
        return jsonify({'success': False, 'message': 'Attendance already recorded for today'}), 400
    
    # Mark attendance (Using a placeholder for course_code since we aren't using multiple)
    attendance = Attendance(
        user_id=current_user.id,
        course_code="General Attendance" 
    )
    
    db.session.add(attendance)
    db.session.commit()
    
    return jsonify({
        'success': True, 
        'message': f'Attendance marked! Welcome, {current_user.name}.'
    })

@student_bp.route('/history')
@login_required
def history():
    """View attendance history (optional page)."""
    if current_user.role != 'student':
        flash("Access denied: Students only.", "error")
        return redirect(url_for('instructor.dashboard'))
    
    attendance_records = Attendance.query.filter_by(
        user_id=current_user.id
    ).order_by(Attendance.timestamp.desc()).all()
    
    return render_template('student/history.html', attendance_records=attendance_records)