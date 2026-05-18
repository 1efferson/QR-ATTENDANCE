import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_caching import Cache
import logging
from config import Config
from flask_wtf.csrf import CSRFProtect
from authlib.integrations.flask_client import OAuth

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
cache = Cache()
csrf = CSRFProtect()
oauth = OAuth()

from werkzeug.middleware.proxy_fix import ProxyFix

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    cache.init_app(app)
    csrf.init_app(app)
    oauth.init_app(app)

    # Registering Google as an OAuth provider 
    oauth.register(
        name='google',
        client_id=app.config.get('GOOGLE_CLIENT_ID'),
        client_secret=app.config.get('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )

    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'

    os.makedirs(app.instance_path, exist_ok=True)

    if os.environ.get("REDIS_URL"):
        from app.tasks.celery_app import make_celery
        make_celery(app)
        
        # Only start APScheduler in the main process, not in gunicorn workers
        import os as _os
        if _os.environ.get("WERKZEUG_RUN_MAIN") != "false":
            from app.scheduler import init_scheduler
            init_scheduler(app)
            print(">>> APScheduler init called", flush=True) 
    else:
        app.logger.warning("REDIS_URL not set — Celery disabled.Sheets sync will run synchronously.")

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


    return app