import logging
from datetime import datetime, timedelta
from app.utils.ip_validation import is_ip_whitelisted, get_client_ip
from app.utils.device_trust import get_or_register_device, is_device_trusted

logger = logging.getLogger(__name__)

def verify_attendance_scan(student_id: int, fp_hash: str, request) -> dict:
    """
    Single entry point for all attendance security checks.
    Returns a dict with 'allowed' bool and 'action' for the route to act on.
    """
    ip = get_client_ip()
    ip_ok, ip_reason = is_ip_whitelisted(ip)

    user_agent  = request.headers.get('User-Agent', '')
    device_info = get_or_register_device(student_id, fp_hash, user_agent, ip)

    # ── Anomaly: same device used for multiple students today ──
    if fp_hash:
        _check_proxy_attempt(student_id, fp_hash)

    # ── Device cap reached ──
    if device_info['status'] == 'device_limit_reached':
        return {
            'allowed': False,
            'reason' : 'device_limit_reached',
            'action' : 'show_device_limit_error',
        }

    # ── On school network + trusted device → allow ──
    if ip_ok and device_info['trusted']:
        return {'allowed': True, 'reason': 'school_network_trusted_device'}

    # ── On school network + new device → onboard ──
    if ip_ok and device_info['new_device']:
        return {
            'allowed'  : False,
            'reason'   : 'new_device',
            'action'   : 'prompt_onboarding',
            'device_id': device_info['device_id'],
        }

    # ── On school network + known but not yet trusted → ask for PIN ──
    if ip_ok and not device_info['trusted']:
        return {
            'allowed'  : False,
            'reason'   : 'untrusted_device',
            'action'   : 'prompt_pin',
            'device_id': device_info['device_id'],
            'has_pin'  : device_info.get('has_pin', False),
        }

    # ── Off network → block regardless of device ──
    return {
        'allowed': False,
        'reason' : 'off_network',
        'action' : 'show_location_error',
    }

def _check_proxy_attempt(student_id: int, fp_hash: str):
    """
    Passive check — logs warning if the same device fingerprint
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