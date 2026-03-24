from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from . import student_bp
from app import db
from app.models import Attendance, BlockedAttempt, Batch
from datetime import datetime
from app.utils.ip_validation import is_ip_whitelisted, get_client_ip


@student_bp.route('/scan')
@login_required
def scan():
    """QR Code scanner page for students."""
    if current_user.role != 'student':
        flash("Access denied: Students only.", "error")
        return redirect(url_for('instructor.dashboard'))
    return render_template('student/scan.html')

# MARK ATTENDANCE ROUTE 
@student_bp.route('/mark-attendance', methods=['POST'])
@login_required
def mark_attendance():
    if current_user.role != 'student':
        return jsonify({'success': False, 'message': 'Access denied'}), 403
 
    client_ip  = get_client_ip()
    user_agent = request.headers.get('User-Agent', 'Unknown')
 
    # IP whitelisting check
    if not is_ip_whitelisted(client_ip):
        data = request.get_json()
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
 
    data          = request.get_json()
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
        return jsonify({'success': False, 'message': 'Invalid QR Code or Manual Code'}), 400
 
    # Check for duplicate scan today
    today    = datetime.utcnow().date()
    existing = Attendance.query.filter(
        Attendance.user_id == current_user.id,
        db.func.date(Attendance.timestamp) == today
    ).first()
 
    if existing:
        return jsonify({'success': False, 'message': 'Attendance already recorded for today'}), 400
 
    # Determine if today is a scheduled class day for this student's batch
    is_personal_time = True
    batch = None
    if current_user.batch_id:
        batch = Batch.query.get(current_user.batch_id)
        if batch and batch.is_class_day(today):
            is_personal_time = False
 
    # Record attendance in DB
    attendance = Attendance(
        user_id=current_user.id,
        course_code="General Attendance",
        ip_address=client_ip,
        user_agent=user_agent,
        is_personal_time=is_personal_time,
        student_level=current_user.level
    )
    db.session.add(attendance)
    db.session.commit()
 
    # ── Sync to Google Sheet (only on real class days, not Personal Time) ──
    if not is_personal_time and batch:
        from app.sheets_sync import mark_student_present, _worksheet_name
        result = mark_student_present(
            student_name   = current_user.name,
            worksheet_name = _worksheet_name(batch),  # e.g. "CodeCamp 3&4 - Beginner"
        )
        if not result['success']:
            current_app.logger.warning(
                "Sheets sync failed for %s: %s", current_user.name, result['message']
            )
    # ──────────────────────────────────────────────────────────────────────
 
    if is_personal_time:
        message = f'Scan recorded. Welcome, {current_user.name}.'
    else:
        message = f'Attendance marked! Welcome, {current_user.name}.'
 
    return jsonify({
        'success': True,
        'message': message,
        'is_personal_time': is_personal_time
    })

@student_bp.route('/history')
@login_required
def history():
    if current_user.role != 'student':
        flash("Access denied: Students only.", "error")
        return redirect(url_for('instructor.dashboard'))

    records = Attendance.query.filter_by(
        user_id=current_user.id
    ).order_by(Attendance.timestamp.desc()).all()

    # Group records by "Month Year" e.g. "February 2026"
    grouped = {}
    for record in records:
        month_key = record.timestamp.strftime('%B %Y')
        if month_key not in grouped:
            grouped[month_key] = []
        grouped[month_key].append(record)

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