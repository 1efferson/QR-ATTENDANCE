from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from . import student_bp
from app import db
from app.models import Attendance, BlockedAttempt, Batch
from datetime import datetime
from app.utils.ip_validation import is_ip_whitelisted, get_client_ip
import logging

logger = logging.getLogger(__name__)

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
    """
    Main attendance marking logic. 
    Optimized to be 'Level-Aware' so it aligns with the 9 PM scheduler.
    """
    if current_user.role != 'student':
        return jsonify({'success': False, 'message': 'Access denied'}), 403
 
    client_ip  = get_client_ip()
    user_agent = request.headers.get('User-Agent', 'Unknown')
    data       = request.get_json() or {}
 
    # 1. IP Whitelisting (Geofencing)
    if not is_ip_whitelisted(client_ip):
        db.session.add(BlockedAttempt(
            user_id=current_user.id,
            ip_address=client_ip,
            user_agent=user_agent,
            reason='invalid_ip',
            attempted_data=data
        ))
        db.session.commit()
        return jsonify({
            'success': False,
            'message': 'Access denied: You must be on school premises to mark attendance.'
        }), 403
 
    # 2. QR Code Validation
    scanned_code  = data.get('qr_content')
    master_secret = current_app.config.get('MASTER_QR_SECRET')
 
    if not scanned_code or scanned_code.strip() != master_secret:
        db.session.add(BlockedAttempt(
            user_id=current_user.id,
            ip_address=client_ip,
            user_agent=user_agent,
            reason='invalid_qr',
            attempted_data=data
        ))
        db.session.commit()
        return jsonify({'success': False, 'message': 'Invalid QR Code.'}), 400
 
    # 3. Level-Aware Duplicate Check (CRITICAL for 9 PM Scheduler)
    # We check if they scanned TODAY for their CURRENT level.
    today = datetime.utcnow().date()
    existing = Attendance.query.filter(
        Attendance.user_id == current_user.id,
        db.func.date(Attendance.timestamp) == today,
        Attendance.student_level == current_user.level  # Matches scheduler logic
    ).first()
 
    if existing:
        return jsonify({
            'success': False, 
            'message': f'Attendance already recorded for {current_user.level} level today.'
        }), 400
 
    # 4. Determine Session Type (Class Day vs Personal Time)
    is_personal_time = True
    batch = None
    if current_user.batch_id:
        batch = Batch.query.get(current_user.batch_id)
        if batch and batch.is_class_day(today):
            is_personal_time = False
 
    # 5. Record in Database
    try:
        attendance = Attendance(
            user_id=current_user.id,
            course_code="General Attendance",
            ip_address=client_ip,
            user_agent=user_agent,
            is_personal_time=is_personal_time,
            student_level=current_user.level  # Crucial for scheduler/dashboard accuracy
        )
        db.session.add(attendance)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"DB Error during scan: {e}")
        return jsonify({'success': False, 'message': 'Database error. Try again.'}), 500
 
    # 6. Optimized Google Sheets Sync
    # Only syncs if it's a real class day (not personal practice time)
    if not is_personal_time and batch:
        from app.sheets_sync import mark_student_present, _worksheet_name
        
        # This function should be the optimized 'Fetch Column' version
        sync_result = mark_student_present(
            student_name   = current_user.name,
            worksheet_name = _worksheet_name(batch)
        )
        
        if not sync_result.get('success'):
            logger.warning(f"Sheets Sync Failed for {current_user.name}: {sync_result.get('message')}")
            # Note: We don't fail the scan if Google Sheets is down, 
            # as the 9 PM scheduler will catch it later.
 
    message = "Attendance marked!" if not is_personal_time else "Personal scan recorded."
    return jsonify({
        'success': True,
        'message': f'{message} Welcome, {current_user.name}.',
        'is_personal_time': is_personal_time
    })

@student_bp.route('/history')
@login_required
def history():
    """Shows student their own attendance history grouped by month."""
    if current_user.role != 'student':
        flash("Access denied.", "error")
        return redirect(url_for('instructor.dashboard'))

    records = Attendance.query.filter_by(
        user_id=current_user.id
    ).order_by(Attendance.timestamp.desc()).all()

    grouped = {}
    for record in records:
        month_key = record.timestamp.strftime('%B %Y')
        grouped.setdefault(month_key, []).append(record)

    return render_template('student/history.html', grouped_records=grouped)


@student_bp.route('/debug-ip')
@login_required
def debug_ip():
    """Temporary route to debug IP detection."""
    from app.utils.ip_validation import get_client_ip, is_ip_whitelisted

    client_ip   = get_client_ip()
    whitelisted = is_ip_whitelisted(client_ip)
    bypass_list  = current_app.config.get('IP_WHITELIST_BYPASS', [])

    html = f"""
    <html><head><title>IP Debug</title></head>
    <body style="font-family: Arial; padding: 20px;">
        <h2>🔍 IP Detection Debug</h2>
        <div style="background: #f0f0f0; padding: 15px; border-radius: 5px;">
            <p><strong>Your detected IP:</strong> <span style="color: blue;">{client_ip}</span></p>
            <p><strong>Is whitelisted?</strong> <span style="color: {'green' if whitelisted else 'red'};">{whitelisted}</span></p>
            <h3>Bypass List:</h3><ul>
    """
    for ip in bypass_list:
        highlight = " <strong>⬅️ THIS IS YOU!</strong>" if ip == client_ip else ""
        html += f"<li>{ip}{highlight}</li>"

    html += """</ul><p><a href="/student/scan">⬅️ Back to Scanner</a></p></div></body></html>"""
    return html