import os
import base64
import json
import tempfile
from dotenv import load_dotenv

load_dotenv()

def _fix_db_url(url: str) -> str:
    """Ensure PostgreSQL URLs use the psycopg2 driver."""
    if url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql+psycopg2://', 1)
    if url.startswith('postgresql://') and 'psycopg2' not in url:
        return url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    return url

def _resolve_google_creds() -> str:
    """Write base64-encoded credentials to a temp file if provided, else fallback to file path."""
    b64 = os.environ.get('GOOGLE_CREDENTIALS_B64')
    if b64:
        creds_data = base64.b64decode(b64).decode()
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        tmp.write(creds_data)
        tmp.close()
        return tmp.name
    return os.environ.get('GOOGLE_SHEETS_CREDENTIALS_FILE', 'credentials.json')


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-please-change-in-prod')
    MASTER_QR_SECRET = os.environ.get('ATTENDANCE_SECRET_KEY')

    _raw_db_url = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
    SQLALCHEMY_DATABASE_URI = _fix_db_url(_raw_db_url)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    if not _raw_db_url.startswith('sqlite'):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_size": 10,
            "max_overflow": 20,
            "pool_timeout": 30,
            "pool_pre_ping": True,
            "pool_recycle": 1800,
        }

    # CSRF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None

    GOOGLE_SHEETS_CREDENTIALS_FILE = _resolve_google_creds()
    GOOGLE_SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')
    SHEETS_SPREADSHEET_NAME = "Facemark"

    GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')

    SERVER_NAME = None

    SCHOOL_IP_RANGES = os.environ.get('SCHOOL_IP_RANGES', '').split(',')
    ENABLE_IP_WHITELISTING = os.environ.get('ENABLE_IP_WHITELISTING', 'true').lower() == 'true'
    IP_WHITELIST_BYPASS = os.environ.get('IP_WHITELIST_BYPASS', '127.0.0.1,::1').split(',')

    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    _redis_available = bool(os.environ.get("REDIS_URL"))
    CACHE_TYPE = "RedisCache" if _redis_available else "SimpleCache"
    CACHE_REDIS_URL = REDIS_URL if _redis_available else None
    CACHE_DEFAULT_TIMEOUT = 60

    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL

    BASE_DIR = os.path.abspath(os.path.dirname(__file__))