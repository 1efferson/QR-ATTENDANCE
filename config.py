import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-please-change-in-prod')
    
    # Database Configuration
    # Defaults to SQLite for dev, but can be overridden with a PostgreSQL URL in .env
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Google Sheets Configuration
    GOOGLE_SHEETS_CREDENTIALS_FILE = os.environ.get('GOOGLE_SHEETS_CREDENTIALS_FILE', 'credentials.json')
    GOOGLE_SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')
    
    # Static Paths
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    QR_FOLDER = os.path.join(BASE_DIR, 'app', 'static', 'qrcodes')