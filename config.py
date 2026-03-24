import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-please-change-in-prod')

    # This matches the text you put in the QR code
    MASTER_QR_SECRET = os.environ.get('ATTENDANCE_SECRET_KEY')
    
    # Database Configuration
    # Defaults to SQLite for dev, but PostgreSQL URL in prod. switched in .env
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Google Sheets Configuration
    GOOGLE_SHEETS_CREDENTIALS_FILE = os.environ.get('GOOGLE_SHEETS_CREDENTIALS_FILE', 'credentials.json')
    GOOGLE_SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')
    # config.py
    SHEETS_SPREADSHEET_NAME = "Facemark"

    # ngrok
    SERVER_NAME = None  
    
    

    # IP Whitelisting Configuration
    SCHOOL_IP_RANGES = os.environ.get('SCHOOL_IP_RANGES', '').split(',')
    ENABLE_IP_WHITELISTING = os.environ.get('ENABLE_IP_WHITELISTING', 'true').lower() == 'true'
    IP_WHITELIST_BYPASS = os.environ.get('IP_WHITELIST_BYPASS', '127.0.0.1,::1').split(',') # bybass for localhost testing, add your device IPs to .env for testing from specific devices
    

    # Static Paths
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    