# app/utils/attendance_guard.py

import logging
from datetime import datetime
from flask import request as flask_request
from app.utils.device_trust import get_or_register_device, get_trusted_device_by_cookie

logger = logging.getLogger(__name__)

DEVICE_COOKIE_NAME = 'qr_device_id'


def verify_attendance_scan(student_id: int, fp_hash: str, request) -> dict:
    """
    Security checks for an attendance scan.
    Cookie-first identification: if a valid device cookie is present, use it.
    Falls back to fingerprint matching, then triggers recovery flow if needed.

    Returns a dict with:
        allowed   (bool)
        reason    (str)
        action    (str, optional) — what the route should tell the client to do
        device_id (int, optional)
        has_pin   (bool, optional)
    """
    ip         = _get_client_ip(request)
    user_agent = request.headers.get('User-Agent', '')

    # ── Step 1: Cookie-first identification ──────────────────────────
    cookie_device_id = _get_device_cookie(request)

    if cookie_device_id:
        device_info = get_trusted_device_by_cookie(student_id, cookie_device_id)

        if device_info:
            # Cookie matches a trusted device for this student — fast path
            _check_proxy_attempt(student_id, device_info['fp_hash'])
            return {
                'allowed'          : True,
                'reason'           : 'trusted_cookie',
                'device_id'        : device_info['device_id'],
                'set_cookie'       : False,  # cookie already valid
            }
        # Cookie present but doesn't match this student — fall through to fingerprint

    # ── Step 2: Fingerprint-based lookup ─────────────────────────────
    if fp_hash:
        _check_proxy_attempt(student_id, fp_hash)

    device_info = get_or_register_device(student_id, fp_hash, user_agent, ip)

    # ── Device taken by another student ──────────────────────────────
    if device_info['status'] == 'device_taken':
        return {
            'allowed': False,
            'reason' : 'device_taken',
            'action' : 'device_taken',
        }

    # ── Device cap reached ────────────────────────────────────────────
    if device_info['status'] == 'device_limit_reached':
        return {
            'allowed': False,
            'reason' : 'device_limit_reached',
            'action' : 'device_limit_reached',
        }

    # ── No fingerprint and no cookie → recovery needed ────────────────
    if device_info['status'] == 'no_fingerprint':
        return {
            'allowed'  : False,
            'reason'   : 'no_fingerprint',
            'action'   : 'prompt_recovery',
        }

    # ── Trusted device via fingerprint → allow + set/refresh cookie ──
    if device_info['trusted']:
        return {
            'allowed'          : True,
            'reason'           : 'trusted_device',
            'device_id'        : device_info['device_id'],
            'set_cookie'       : True,   # refresh/set the cookie
        }

    # ── New device → send to onboarding ──────────────────────────────
    if device_info['new_device']:
        return {
            'allowed'  : False,
            'reason'   : 'new_device',
            'action'   : 'prompt_onboarding',
            'device_id': device_info['device_id'],
        }

    # ── Known but untrusted → cookie missing/cleared, ask for PIN ────
    return {
        'allowed'  : False,
        'reason'   : 'untrusted_device',
        'action'   : 'prompt_pin',
        'device_id': device_info['device_id'],
        'has_pin'  : device_info.get('has_pin', False),
    }


def _get_device_cookie(request) -> int | None:
    """Read and validate the device cookie. Returns device_id int or None."""
    raw = request.cookies.get(DEVICE_COOKIE_NAME)
    if raw and raw.isdigit():
        return int(raw)
    return None


def _get_client_ip(request) -> str:
    """Get real client IP, handling proxies."""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    return request.remote_addr


def _check_proxy_attempt(student_id: int, fp_hash: str):
    """
    Passive check — logs a warning if the same device fingerprint
    has been used for a different student today. Does not block.
    """
    from app.models import Attendance
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    conflict = Attendance.query.filter(
        Attendance.device_fp_hash == fp_hash,
        Attendance.user_id        != student_id,
        Attendance.timestamp      >= today_start,
    ).first()
    if conflict:
        logger.warning(
            "PROXY_FLAG: device %s... used for student %s AND student %s today",
            fp_hash[:12], conflict.user_id, student_id
        )