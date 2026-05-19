from flask import render_template, redirect, url_for, flash, request, jsonify, current_app, make_response
from flask_login import login_required, current_user
from . import student_bp
from app import csrf
from app import db
from app.models import Attendance, BlockedAttempt, Batch, Absence
from datetime import datetime
import logging
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from math import ceil
from datetime import datetime as _dt
from app.utils.attendance_guard import verify_attendance_scan, DEVICE_COOKIE_NAME
from app.utils.device_trust import set_device_pin, verify_device_pin
from app.utils.qr_tokens import validate_qr_token
from app.models import StudentDevice

logger = logging.getLogger(__name__)

HISTORY_MONTHS_PER_PAGE = 2


def get_client_ip():
    """Get real client IP, handling proxies."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    return request.remote_addr


@student_bp.route('/scan')
@login_required
def scan():
    if current_user.role != 'student':
        flash("Access denied: Students only.", "error")
        return redirect(url_for('instructor.dashboard'))

    has_device = StudentDevice.query.filter_by(
        student_id=current_user.id, trusted=True
    ).first()
    if not has_device:
        return redirect(url_for('student.onboarding'))

    return render_template('student/scan.html')


# ── mark_attendance ────────────────────────────────────────────────
@student_bp.route('/mark-attendance', methods=['POST'])
@csrf.exempt
@login_required
def mark_attendance():
    if current_user.role != 'student':
        return jsonify({'success': False, 'message': 'Access denied'}), 403

    client_ip  = get_client_ip()
    user_agent = request.headers.get('User-Agent', 'Unknown')
    data       = request.get_json() or {}

    # 1 ── QR token check (signed token, no DB)
    scanned_code = data.get('qr_content', '')
    token_valid, token_reason = validate_qr_token(scanned_code)
    if not token_valid:
        db.session.add(BlockedAttempt(
            user_id=current_user.id, ip_address=client_ip,
            user_agent=user_agent, reason=f'invalid_qr:{token_reason}',
            attempted_data=data
        ))
        db.session.commit()
        msgs = {
            'invalid_or_expired': 'QR code expired — ask your instructor to refresh.',
            'missing_token'     : 'No QR code received.',
        }
        return jsonify({
            'success': False,
            'message': msgs.get(token_reason, 'Invalid QR code.')
        }), 400

    # 2 ── Device fingerprint + guard
    device_fp = data.get('device_fp', '')
    guard     = verify_attendance_scan(current_user.id, device_fp, request)

    if not guard['allowed']:
        action = guard.get('action', '')

        if action == 'prompt_onboarding':
            return jsonify({
                'success'  : False,
                'action'   : 'onboarding',
                'device_id': guard.get('device_id'),
                'message'  : 'Please complete device setup first.',
            }), 403

        if action == 'prompt_pin':
            return jsonify({
                'success'  : False,
                'action'   : 'verify_pin',
                'device_id': guard.get('device_id'),
                'has_pin'  : guard.get('has_pin', False),
                'message'  : 'Please verify your device PIN.',
            }), 403

        if action == 'prompt_recovery':
            # Cookie is gone and fingerprint doesn't match any trusted device.
            # Client still sends whatever fp it has — used in /device/recover
            # to re-link the account once PIN is verified.
            return jsonify({
                'success': False,
                'action' : 'recovery',
                'message': 'Device not recognized. Please verify your PIN to continue.',
            }), 403

        if action == 'device_taken':
            return jsonify({
                'success': False,
                'action' : 'device_taken',
                'message': 'This device is registered to another student. Contact your instructor.',
            }), 403

        if action == 'device_limit_reached':
            return jsonify({
                'success': False,
                'message': 'Device limit reached. Contact your instructor to manage devices.',
            }), 403

        return jsonify({
            'success': False,
            'message': 'Attendance could not be recorded. Please try again.',
        }), 403

    # 3 ── Duplicate check
    today_start    = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    existing = Attendance.query.filter(
        Attendance.user_id   == current_user.id,
        Attendance.timestamp >= today_start,
        Attendance.timestamp <  tomorrow_start,
    ).first()
    if existing:
        return jsonify({
            'success': False,
            'message': 'Attendance already recorded for today.'
        }), 400

    # 4 ── Session type (class day vs personal time)
    is_personal_time = True
    if current_user.batch_id:
        batch = Batch.query.get(current_user.batch_id)
        if batch and batch.is_class_day(today_start.date()):
            is_personal_time = False

    # 5 ── Write to DB
    try:
        attendance = Attendance(
            user_id          = current_user.id,
            course_code      = "General Attendance",
            ip_address       = client_ip,
            user_agent       = user_agent,
            is_personal_time = is_personal_time,
            student_level    = current_user.level,
            device_fp_hash   = device_fp,
        )
        db.session.add(attendance)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Attendance already recorded for today.'
        }), 400
    except Exception as e:
        db.session.rollback()
        logger.error(f"DB Error during scan for user {current_user.id}: {e}")
        return jsonify({'success': False, 'message': 'Database error. Try again.'}), 500

    # 6 ── Build response, set device cookie if this was a fingerprint-verified scan
    message = "Attendance marked!" if not is_personal_time else "Personal scan recorded."
    resp = make_response(jsonify({
        'success'         : True,
        'message'         : f'{message} Welcome, {current_user.name}.',
        'is_personal_time': is_personal_time,
    }))

    if guard.get('set_cookie') and guard.get('device_id'):
        resp.set_cookie(
            DEVICE_COOKIE_NAME,
            str(guard['device_id']),
            max_age=60 * 60 * 24 * 365,   # 1 year
            httponly=True,
            samesite='Lax',
            secure=not current_app.debug,  # HTTPS only in production
        )
        logger.info(
            "Device cookie set for student %s → device %s",
            current_user.id, guard['device_id']
        )

    return resp


# ── Onboarding ────────────────────────────────────────────────────────

@student_bp.route('/onboarding')
@login_required
def onboarding():
    if current_user.role != 'student':
        return redirect(url_for('instructor.dashboard'))

    has_device = StudentDevice.query.filter_by(
        student_id=current_user.id, trusted=True
    ).first()
    if has_device:
        return redirect(url_for('student.scan'))

    return render_template('student/onboarding.html')


# ── Set PIN for a device ──────────────────────────────────────────────

@student_bp.route('/device/set-pin', methods=['POST'])
@login_required
def device_set_pin():
    data      = request.get_json() or {}
    device_id = data.get('device_id')
    pin       = str(data.get('pin', ''))

    if not device_id or not pin or len(pin) < 4:
        return jsonify({'success': False, 'message': 'Invalid PIN or device.'}), 400

    device = StudentDevice.query.filter_by(
        id=device_id, student_id=current_user.id
    ).first()
    if not device:
        return jsonify({'success': False, 'message': 'Device not found.'}), 404

    ok = set_device_pin(device_id, pin)
    if ok:
        return jsonify({'success': True, 'message': 'Device registered successfully.'})
    return jsonify({'success': False, 'message': 'Failed to set PIN.'}), 500


# ── Verify PIN on scan ────────────────────────────────────────────────

@student_bp.route('/device/verify-pin', methods=['POST'])
@login_required
def device_verify_pin():
    data    = request.get_json() or {}
    fp_hash = data.get('device_fp', '')
    pin     = str(data.get('pin', ''))

    if not fp_hash or not pin:
        return jsonify({'success': False, 'message': 'Missing device or PIN.'}), 400

    ok = verify_device_pin(current_user.id, fp_hash, pin)
    if ok:
        return jsonify({'success': True, 'message': 'Device verified.'})
    return jsonify({'success': False, 'message': 'Incorrect PIN.'}), 401


# ── Attendance history ────────────────────────────────────────────────

@student_bp.route('/history')
@login_required
def history():
    if current_user.role != 'student':
        flash("Access denied.", "error")
        return redirect(url_for('instructor.dashboard'))

    attendances = Attendance.query.filter_by(
        user_id=current_user.id
    ).order_by(Attendance.timestamp.desc()).all()

    absences = Absence.query.filter_by(
        user_id=current_user.id
    ).order_by(Absence.date.desc()).all()

    if not attendances and not absences:
        return render_template(
            'student/history.html',
            grouped_records={},
            all_records={},
            page=1,
            total_pages=1,
            no_history=True,
        )

    records = []
    for a in attendances:
        records.append({
            'type'            : 'present',
            'course_code'     : a.course_code,
            'is_personal_time': a.is_personal_time,
            'sort_dt'         : a.timestamp,
            'display_date'    : a.timestamp.strftime('%d %B %Y, %I:%M %p'),
            'day_name'        : a.timestamp.strftime('%A'),
            'month_key'       : a.timestamp.strftime('%B %Y'),
        })
    for ab in absences:
        dt = _dt.combine(ab.date, _dt.min.time())
        records.append({
            'type'            : 'absent',
            'course_code'     : 'General Attendance',
            'is_personal_time': False,
            'sort_dt'         : dt,
            'display_date'    : ab.date.strftime('%d %B %Y'),
            'day_name'        : ab.date.strftime('%A'),
            'month_key'       : ab.date.strftime('%B %Y'),
        })

    records.sort(key=lambda r: r['sort_dt'], reverse=True)

    all_grouped = {}
    for record in records:
        all_grouped.setdefault(record['month_key'], []).append(record)

    month_keys   = list(all_grouped.keys())
    total_months = len(month_keys)
    total_pages  = max(1, ceil(total_months / HISTORY_MONTHS_PER_PAGE))

    page = request.args.get('page', 1, type=int)
    page = max(1, min(page, total_pages))

    start           = (page - 1) * HISTORY_MONTHS_PER_PAGE
    page_keys       = month_keys[start:start + HISTORY_MONTHS_PER_PAGE]
    grouped_records = {k: all_grouped[k] for k in page_keys}

    return render_template(
        'student/history.html',
        grouped_records=grouped_records,
        all_records=all_grouped,
        page=page,
        total_pages=total_pages,
        no_history=False,
    )


# ── Device registration ───────────────────────────────────────────────

@student_bp.route('/device/register', methods=['POST'])
@login_required
def device_register():
    data      = request.get_json() or {}
    device_fp = data.get('device_fp', '')

    if not device_fp:
        return jsonify({'success': False, 'message': 'No fingerprint received.'}), 400

    from app.utils.device_trust import get_or_register_device

    ip         = get_client_ip()
    user_agent = request.headers.get('User-Agent', '')
    info       = get_or_register_device(current_user.id, device_fp, user_agent, ip)

    if info['status'] == 'device_limit_reached':
        return jsonify({
            'success': False,
            'message': 'Device limit reached. Contact your instructor.'
        }), 403

    if info['status'] == 'device_taken':
        return jsonify({
            'success': False,
            'message': 'This device is registered to another student. Contact your instructor.'
        }), 403

    other_trusted = StudentDevice.query.filter(
        StudentDevice.student_id == current_user.id,
        StudentDevice.trusted    == True,
        StudentDevice.id         != info['device_id']
    ).first()

    return jsonify({
        'success'             : True,
        'device_id'           : info['device_id'],
        'is_new'              : info['new_device'],
        'is_returning_student': other_trusted is not None,
    })


# ── Device recovery ───────────────────────────────────────────────────

@student_bp.route('/device/recover', methods=['POST'])
@login_required
def device_recover():
    data   = request.get_json() or {}
    new_fp = data.get('device_fp', '')
    pin    = str(data.get('pin', ''))

    if not new_fp or not pin:
        return jsonify({'success': False, 'message': 'Missing data.'}), 400

    from werkzeug.security import check_password_hash

    existing_devices = StudentDevice.query.filter_by(
        student_id=current_user.id
    ).all()

    pin_matched_device = None
    for device in existing_devices:
        if device.pin_hash and check_password_hash(device.pin_hash, pin):
            pin_matched_device = device
            break

    if not pin_matched_device:
        return jsonify({
            'success': False,
            'message': 'Incorrect PIN. If you forgot your PIN, contact your instructor.'
        }), 401

    already_exists = StudentDevice.query.filter_by(
        student_id=current_user.id,
        fingerprint_hash=new_fp
    ).first()

    if already_exists:
        already_exists.trusted = True
        db.session.commit()
        return jsonify({'success': True, 'message': 'Device re-verified.'})

    if len(existing_devices) >= 2:
        oldest = StudentDevice.query.filter_by(
            student_id=current_user.id
        ).order_by(StudentDevice.created_at.asc()).first()
        oldest.fingerprint_hash = new_fp
        oldest.trusted          = True
        oldest.last_seen_at     = datetime.utcnow()
        oldest.pin_hash         = pin_matched_device.pin_hash
        db.session.commit()
        return jsonify({'success': True, 'message': 'Device recovered successfully.'})

    from app.utils.device_trust import get_or_register_device
    info       = get_or_register_device(
        current_user.id, new_fp,
        request.headers.get('User-Agent', ''),
        get_client_ip()
    )
    new_device          = StudentDevice.query.get(info['device_id'])
    new_device.pin_hash = pin_matched_device.pin_hash
    new_device.trusted  = True
    db.session.commit()

    return jsonify({'success': True, 'message': 'Device recovered successfully.'})