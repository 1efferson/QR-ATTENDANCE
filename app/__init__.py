import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_caching import Cache
import logging
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
cache = Cache()
celery = None


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    cache.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'

    os.makedirs(app.instance_path, exist_ok=True)

    # Only start Celery if a real Redis URL is configured
    if os.environ.get("REDIS_URL"):
        from app.tasks.celery_app import make_celery
        global celery
        celery = make_celery(app)
    else:
        app.logger.warning("REDIS_URL not set — Celery disabled, Sheets sync will run synchronously.")

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

    from app.scheduler import init_scheduler
    init_scheduler(app)

    return app