import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from config import Config

# Initialize extensions globally, but unattached to app
db = SQLAlchemy()
login_manager = LoginManager()

def create_app(config_class=Config):
    """Application Factory to create and configure the Flask app."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions with the app
    db.init_app(app)
    login_manager.init_app(app)

    # Configure Login Manager
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'

    # Ensure QR code directory exists
    os.makedirs(app.config['QR_FOLDER'], exist_ok=True)

    # Register Blueprints
    # Note: These imports are inside the factory to avoid circular dependencies
    from app.routes.auth import auth_bp
    from app.routes.instructor import instructor_bp
    from app.routes.student import student_bp
    from app.routes.main import main_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(instructor_bp, url_prefix='/instructor')
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(main_bp)


    return app