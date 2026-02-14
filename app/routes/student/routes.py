
from flask import render_template, redirect, url_for, flash, request, jsonify
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
    """Process scanned QR code and mark attendance."""
    if current_user.role != 'student':
        return jsonify({'success': False, 'message': 'Access denied'}), 403
    
    data = request.get_json()
    session_id = data.get('session_id')
    course_code = data.get('course_code')
    
    if not session_id or not course_code:
        return jsonify({'success': False, 'message': 'Invalid QR code'}), 400
    
    # Check if already marked attendance for this session
    existing = Attendance.query.filter_by(
        user_id=current_user.id,
        course_code=course_code
    ).filter(
        Attendance.timestamp >= datetime.utcnow().date()
    ).first()
    
    if existing:
        return jsonify({'success': False, 'message': 'Already marked attendance for this class today'}), 400
    
    # Create attendance record
    attendance = Attendance(
        user_id=current_user.id,
        course_code=course_code
    )
    
    db.session.add(attendance)
    db.session.commit()
    
    return jsonify({
        'success': True, 
        'message': f'Attendance marked for {course_code}!',
        'student': current_user.name,
        'course': course_code
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