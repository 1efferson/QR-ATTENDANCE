# app/utils/qr_tokens.py

import hmac
import hashlib
import time
import base64
import json
from flask import current_app

TOKEN_LIFETIME = 90  # seconds


def _sign(payload: dict) -> str:
    """Creates a tamper-proof signed token. Format: base64(payload).signature"""
    body      = base64.urlsafe_b64encode(
                    json.dumps(payload).encode()
                ).decode()
    secret    = current_app.config['SECRET_KEY'].encode()
    signature = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _verify(token: str) -> dict | None:
    """Returns payload dict if valid, None if tampered or expired."""
    try:
        body, signature = token.rsplit('.', 1)
    except ValueError:
        return None

    secret       = current_app.config['SECRET_KEY'].encode()
    expected_sig = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_sig, signature):
        return None

    payload = json.loads(base64.urlsafe_b64decode(body).decode())

    if time.time() > payload['exp']:
        return None

    return payload


def generate_qr_token(instructor_id: int) -> str:
    """
    Returns a signed QR token string. Nothing written to DB.
    Valid for TOKEN_LIFETIME seconds (90s).
    """
    payload = {
        'type': 'qr',
        'iss' : instructor_id,
        'iat' : int(time.time()),
        'exp' : int(time.time()) + TOKEN_LIFETIME,
    }
    return _sign(payload)


def validate_qr_token(token: str) -> tuple[bool, str]:
    """
    Pure in-memory validation. No DB touch.
    Returns (is_valid, reason).
    """
    if not token:
        return False, 'missing_token'

    payload = _verify(token)

    if payload is None:
        return False, 'invalid_or_expired'

    if payload.get('type') != 'qr':
        return False, 'invalid_or_expired'

    return True, 'valid'


def generate_display_token(instructor_id: int) -> str:
    """
    Signed token for the public display URL.
    Valid for 8 hours (one school day).
    Safe to share — contains no sensitive info.
    """
    payload = {
        'type': 'display',
        'iss' : instructor_id,
        'iat' : int(time.time()),
        'exp' : int(time.time()) + (8 * 3600),
    }
    return _sign(payload)


def verify_display_token(token: str) -> bool:
    """Verify the public display URL token."""
    if not token:
        return False
    payload = _verify(token)
    if not payload:
        return False
    return payload.get('type') == 'display'


def seconds_remaining(token: str) -> int:
    """How many seconds until this token expires."""
    try:
        body, _ = token.rsplit('.', 1)
        payload = json.loads(base64.urlsafe_b64decode(body).decode())
        remaining = int(payload['exp'] - time.time())
        return max(0, remaining)
    except Exception:
        return 0

