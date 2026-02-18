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
    
    # Static Paths
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    QR_FOLDER = os.path.join(BASE_DIR, 'app', 'static', 'qrcodes')