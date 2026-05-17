# app/utils/session_state.py

import redis
from flask import current_app
from werkzeug.security import generate_password_hash, check_password_hash

SESSION_KEY = 'qr_session_active'
SESSION_TTL = 8 * 3600  # 8 hours


def _redis():
    return redis.from_url(current_app.config['REDIS_URL'])


def activate_session(display_token: str, pin: str):
    """Store session in Redis — visible to ALL devices, not just one browser."""
    r = _redis()
    r.hset(SESSION_KEY, mapping={
        'display_token': display_token,
        'pin_hash'     : generate_password_hash(pin),
        'active'       : '1',
    })
    r.expire(SESSION_KEY, SESSION_TTL)


def deactivate_session():
    """End session — display page sees it within 90 seconds."""
    _redis().delete(SESSION_KEY)


def get_session() -> dict | None:
    """Returns session dict if active, None if not."""
    try:
        r    = _redis()
        data = r.hgetall(SESSION_KEY)
    except Exception:
        return None
    if not data or data.get(b'active') != b'1':
        return None
    return {
        'display_token': data[b'display_token'].decode(),
        'pin_hash'     : data[b'pin_hash'].decode(),
    }


def get_display_token() -> str | None:
    """Returns the active display token, or None if no session."""
    sess = get_session()
    return sess['display_token'] if sess else None


def is_session_active() -> bool:
    return get_session() is not None


def verify_session_pin(pin: str) -> bool:
    sess = get_session()
    if not sess:
        return False
    return check_password_hash(sess['pin_hash'], pin)