from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from . import student_bp
from app import csrf
from app import db
from app.models import Attendance, BlockedAttempt, Batch, Absence
from datetime import datetime
from app.utils.ip_validation import is_ip_whitelisted, get_client_ip
import logging
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from math import ceil
from datetime import datetime as _dt

logger = logging.getLogger(__name__)

HISTORY_MONTHS_PER_PAGE = 2

@student_bp.route('/scan')
@login_required
def scan():
    """QR Code scanner page for students."""
    if current_user.role != 'student':
        flash("Access denied: Students only.", "error")
        return redirect(url_for('instructor.dashboard'))
    return render_template('student/scan.html')

@student_bp.route('/mark-attendance', methods=['POST'])
@csrf.exempt
@login_required
def mark_attendance():
    """
    Highly concurrent attendance marking logic.
    Optimized for fast DB writes and index usage.
    """
    if current_user.role != 'student':
        return jsonify({'success': False, 'message': 'Access denied'}), 403
 
    client_ip  = get_client_ip()
    user_agent = request.headers.get('User-Agent', 'Unknown')
    data       = request.get_json() or {}
 
    # 1. IP Whitelisting (Geofencing)
    if not is_ip_whitelisted(client_ip):
        # Consider logging blocked attempts asynchronously or in batches 
        # if this becomes a DDoS vector, but this is fine for now.
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
 
    # 3. Level-Aware Duplicate Check (Index-Optimized)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    
    # This range query allows PostgreSQL to use a B-Tree index on the timestamp column
    existing = Attendance.query.filter(
        Attendance.user_id == current_user.id,
        Attendance.timestamp >= today_start,
        Attendance.timestamp < tomorrow_start, 
    ).first()
 
    if existing:
        return jsonify({
            'success': False, 
            'message': f'Attendance already recorded for {current_user.level} level today.'
        }), 400
 
    # 4. Determine Session Type
    is_personal_time = True
    batch = None
    if current_user.batch_id:
        # Optimization tip: If Batch doesn't change often, you could cache this check
        batch = Batch.query.get(current_user.batch_id)
        if batch and batch.is_class_day(today_start.date()):
            is_personal_time = False
 
    # 5. Record in Database with Race Condition Handling
    try:
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
        
    except IntegrityError:
        # This catches the race condition where two requests hit the DB at the exact same time
        db.session.rollback()
        return jsonify({
            'success': False, 
            'message': f'Attendance already recorded for {current_user.level} level today.'
        }), 400
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"DB Error during scan for user {current_user.id}: {e}")
        return jsonify({'success': False, 'message': 'Database error. Try again.'}), 500
 
    # 6. Google Sheets Sync 
    # REMOVED: Defer this entirely to your 9 PM scheduler! 
    # The HTTP response should return immediately after the DB commit.
 
    message = "Attendance marked!" if not is_personal_time else "Personal scan recorded."
    return jsonify({
        'success': True,
        'message': f'{message} Welcome, {current_user.name}.',
        'is_personal_time': is_personal_time
    })

@student_bp.route('/history')
@login_required
def history():
    """
    Shows student their attendance + absence history grouped by month,
    paginated by month groups (3 months per page).
    Summary pill counts always reflect the full record, not just the current page.
    """
    if current_user.role != 'student':
        flash("Access denied.", "error")
        return redirect(url_for('instructor.dashboard'))

    # ── Fetch both tables ────────────────────────────────────────────
    attendances = Attendance.query.filter_by(
        user_id=current_user.id
    ).order_by(Attendance.timestamp.desc()).all()

    absences = Absence.query.filter_by(
        user_id=current_user.id
    ).order_by(Absence.date.desc()).all()

    # ── Merge into a unified list ────────────────────────────────────
    records = []

    for a in attendances:
        records.append({
            'type':          'present',
            'course_code':   a.course_code,
            'is_personal_time': a.is_personal_time,
            'sort_dt':       a.timestamp,
            'display_date':  a.timestamp.strftime('%d %B %Y, %I:%M %p'),
            'day_name':      a.timestamp.strftime('%A'),
            'month_key':     a.timestamp.strftime('%B %Y'),
        })

    for ab in absences:
        dt = _dt.combine(ab.date, _dt.min.time())
        records.append({
            'type':          'absent',
            'course_code':   'General Attendance',
            'is_personal_time': False,
            'sort_dt':       dt,
            'display_date':  ab.date.strftime('%d %B %Y'),
            'day_name':      ab.date.strftime('%A'),
            'month_key':     ab.date.strftime('%B %Y'),
        })

    # Sort newest first
    records.sort(key=lambda r: r['sort_dt'], reverse=True)

    # ── Group all records by month (used for grand total pills) ──────
    all_grouped = {}
    for record in records:
        all_grouped.setdefault(record['month_key'], []).append(record)

    # ── Paginate by month group ──────────────────────────────────────
    month_keys  = list(all_grouped.keys())   # already sorted newest-first
    total_months = len(month_keys)
    total_pages  = max(1, ceil(total_months / HISTORY_MONTHS_PER_PAGE))

    # Clamp page to valid range
    page = request.args.get('page', 1, type=int)
    page = max(1, min(page, total_pages))

    start = (page - 1) * HISTORY_MONTHS_PER_PAGE
    page_keys = month_keys[start:start + HISTORY_MONTHS_PER_PAGE]
    grouped_records = {k: all_grouped[k] for k in page_keys}

    return render_template(
        'student/history.html',
        grouped_records=grouped_records,   # current page only
        all_records=all_grouped,           # full set for summary pill counts
        page=page,
        total_pages=total_pages,
    )


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