import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-please-change-in-prod')
    MASTER_QR_SECRET = os.environ.get('ATTENDANCE_SECRET_KEY')

    DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Pool settings only apply to PostgreSQL — SQLite doesn't support them
    if not DATABASE_URL.startswith('sqlite'):
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

    GOOGLE_SHEETS_CREDENTIALS_FILE = os.environ.get('GOOGLE_SHEETS_CREDENTIALS_FILE', 'credentials.json')
    GOOGLE_SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')
    SHEETS_SPREADSHEET_NAME = "Facemark"

    SERVER_NAME = None

    SCHOOL_IP_RANGES = os.environ.get('SCHOOL_IP_RANGES', '').split(',')
    ENABLE_IP_WHITELISTING = os.environ.get('ENABLE_IP_WHITELISTING', 'true').lower() == 'true'
    IP_WHITELIST_BYPASS = os.environ.get('IP_WHITELIST_BYPASS', '127.0.0.1,::1').split(',')

    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Use SimpleCache locally if Redis isn't available
    _redis_available = bool(os.environ.get("REDIS_URL"))
    CACHE_TYPE = "RedisCache" if _redis_available else "SimpleCache"
    CACHE_REDIS_URL = REDIS_URL if _redis_available else None 
    CACHE_DEFAULT_TIMEOUT = 60

    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL

    BASE_DIR = os.path.abspath(os.path.dirname(__file__))