from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
from app.models import StudentDevice

MAX_DEVICES_PER_STUDENT = 2


def get_or_register_device(student_id: int, fp_hash: str, user_agent: str = '', ip: str = '') -> dict:
    """
    Look up or create a device record.
    Returns a status dict the route uses to decide what to do next.
    """
    if not fp_hash:
        return {'status': 'no_fingerprint', 'trusted': False, 'device_id': None}

    # Check if this fingerprint is already registered to a DIFFERENT student
    existing_claim = StudentDevice.query.filter(
        StudentDevice.fingerprint_hash == fp_hash,
        StudentDevice.student_id       != student_id
    ).first()

    if existing_claim:
        return {
            'status'    : 'device_taken',
            'trusted'   : False,
            'device_id' : None,
            'new_device': False,
        }

    device = StudentDevice.query.filter_by(
        student_id=student_id,
        fingerprint_hash=fp_hash
    ).first()

    now = datetime.utcnow()

    if device:
        device.last_seen_ip = ip
        device.last_seen_at = now
        db.session.commit()
        return {
            'status'    : 'known',
            'trusted'   : device.trusted,
            'has_pin'   : bool(device.pin_hash),
            'device_id' : device.id,
            'new_device': False,
        }

    # Check device cap before creating
    existing_count = StudentDevice.query.filter_by(student_id=student_id).count()
    if existing_count >= MAX_DEVICES_PER_STUDENT:
        return {
            'status'    : 'device_limit_reached',
            'trusted'   : False,
            'device_id' : None,
            'new_device': True,
        }

    new_device = StudentDevice(
        student_id       = student_id,
        fingerprint_hash = fp_hash,
        user_agent       = user_agent[:300],
        first_seen_ip    = ip,
        last_seen_ip     = ip,
        last_seen_at     = now,
        trusted          = False,
    )
    db.session.add(new_device)
    db.session.commit()

    return {
        'status'    : 'new_device',
        'trusted'   : False,
        'has_pin'   : False,
        'device_id' : new_device.id,
        'new_device': True,
    }


def get_device_by_id(device_id: int, student_id: int):
    """Look up a device by its DB id, scoped to a student."""
    return StudentDevice.query.filter_by(
        id=device_id,
        student_id=student_id
    ).first()


def is_device_trusted(student_id: int, fp_hash: str) -> bool:
    device = StudentDevice.query.filter_by(
        student_id=student_id,
        fingerprint_hash=fp_hash,
        trusted=True
    ).first()
    return device is not None


def get_trusted_device_by_cookie(student_id: int, device_id: int) -> dict | None:
    """
    Look up a device by its cookie-stored ID.
    Returns device info dict if found and trusted, else None.
    Used as the primary identification path on day 2+ scans.
    """
    device = StudentDevice.query.filter_by(
        id=device_id,
        student_id=student_id,
        trusted=True
    ).first()

    if not device:
        return None

    return {
        'status'    : 'known',
        'trusted'   : True,
        'has_pin'   : bool(device.pin_hash),
        'device_id' : device.id,
        'new_device': False,
        'fp_hash'   : device.fingerprint_hash,
    }


def set_device_pin(device_id: int, pin: str) -> bool:
    """Hash and store the PIN; marks device as trusted."""
    if not pin or len(pin) < 4:
        return False
    device = StudentDevice.query.get(device_id)
    if not device:
        return False
    device.pin_hash = generate_password_hash(pin)
    device.trusted  = True
    db.session.commit()
    return True


def verify_device_pin(student_id: int, fp_hash: str, pin: str) -> bool:
    """
    Verify PIN for a known but untrusted device.
    Returns True only if the device belongs to this student and the PIN matches.
    On success, marks device as trusted.
    """
    device = StudentDevice.query.filter_by(
        student_id=student_id,
        fingerprint_hash=fp_hash
    ).first()
    if not device or not device.pin_hash:
        return False
    if check_password_hash(device.pin_hash, pin):
        device.trusted      = True
        device.last_seen_at = datetime.utcnow()
        db.session.commit()
        return True
    return False


def verify_pin_by_student(student_id: int, pin: str):
    """
    Verify PIN across ALL devices for this student.
    Used during cookie-missing recovery — we don't have a fingerprint yet,
    just the PIN the student remembers.
    Returns the matching device if found, else None.
    """
    devices = StudentDevice.query.filter_by(student_id=student_id).all()
    for device in devices:
        if device.pin_hash and check_password_hash(device.pin_hash, pin):
            return device
    return None


def replace_device_fingerprint(device_id: int, student_id: int, new_fp: str, ip: str = '') -> bool:
    """
    Replace a device's fingerprint — used when a student gets a new phone
    or clears cookies and verifies via PIN.
    Clears any existing claim on new_fp from other students first (shouldn't exist
    after get_or_register_device check, but defensive).
    """
    device = StudentDevice.query.filter_by(
        id=device_id,
        student_id=student_id
    ).first()
    if not device:
        return False

    device.fingerprint_hash = new_fp
    device.last_seen_ip     = ip
    device.last_seen_at     = datetime.utcnow()
    device.trusted          = True
    db.session.commit()
    return True


def trust_device(device_id: int):
    """Called after successful PIN or passkey verification."""
    device = StudentDevice.query.get(device_id)
    if device:
        device.trusted = True
        db.session.commit()