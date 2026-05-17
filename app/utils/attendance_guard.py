# app/utils/attendance_guard.py

import logging
from datetime import datetime
from app.utils.device_trust import get_or_register_device

logger = logging.getLogger(__name__)


def verify_attendance_scan(student_id: int, fp_hash: str, request) -> dict:
    """
    Security checks for an attendance scan.
    IP whitelisting removed — device fingerprint is the primary gate.

    Returns a dict with:
        allowed (bool)
        reason  (str)
        action  (str, optional) — what the route should tell the client to do
    """
    ip         = _get_client_ip(request)
    user_agent = request.headers.get('User-Agent', '')

    device_info = get_or_register_device(student_id, fp_hash, user_agent, ip)

    # Passive proxy check — logs only, never blocks
    if fp_hash:
        _check_proxy_attempt(student_id, fp_hash)

    # ── Device cap reached ────────────────────────────────────────────
    if device_info['status'] == 'device_limit_reached':
        return {
            'allowed': False,
            'reason' : 'device_limit_reached',
            'action' : 'device_limit_reached',
        }

    # ── Trusted device → allow ────────────────────────────────────────
    if device_info['trusted']:
        return {'allowed': True, 'reason': 'trusted_device'}

    # ── New device → send to onboarding ──────────────────────────────
    if device_info['new_device']:
        return {
            'allowed'  : False,
            'reason'   : 'new_device',
            'action'   : 'prompt_onboarding',
            'device_id': device_info['device_id'],
        }

    # ── Known but not yet trusted → ask for PIN ───────────────────────
    return {
        'allowed'  : False,
        'reason'   : 'untrusted_device',
        'action'   : 'prompt_pin',
        'device_id': device_info['device_id'],
        'has_pin'  : device_info.get('has_pin', False),
    }


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
            f"PROXY_FLAG: device {fp_hash[:12]}... used for "
            f"student {conflict.user_id} AND student {student_id} today"
        )