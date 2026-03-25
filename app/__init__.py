import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from config import Config
from flask_migrate import Migrate
import logging

# Initialize extensions globally, but unattached to app
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()

def create_app(config_class=Config):
    """Application Factory to create and configure the Flask app."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions with the app
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # Configure Login Manager
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'

    os.makedirs(app.instance_path, exist_ok=True)

    # Register Blueprints
    from app.routes.auth import auth_bp
    from app.routes.instructor import instructor_bp
    from app.routes.student import student_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(instructor_bp, url_prefix='/instructor')
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # Start the background scheduler (9 PM absence sync + Google Sheet sync)
    from app.scheduler import init_scheduler
    init_scheduler(app)

    return app