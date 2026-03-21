from flask import render_template, send_from_directory, current_app
import os
from . import main_bp


@main_bp.route('/')
def index():
    return render_template('index.html')


@main_bp.route('/sw.js')
def service_worker():
    return send_from_directory(
        os.path.join(current_app.root_path, 'static', 'js'),
        'service_worker.js',
        mimetype='application/javascript'
    )

# Safari always looks for these at the root regardless of what's in the <head> — these routes serve the existing files from /static/icons/.
@main_bp.route('/apple-touch-icon.png')
def apple_touch_icon():
    return send_from_directory(
        os.path.join(current_app.root_path, 'static', 'icons'),
        'apple-touch-icon.png',
        mimetype='image/png'
    )

@main_bp.route('/apple-touch-icon-precomposed.png')
def apple_touch_icon_precomposed():
    return send_from_directory(
        os.path.join(current_app.root_path, 'static', 'icons'),
        'apple-touch-icon.png',
        mimetype='image/png'
    )

@main_bp.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(current_app.root_path, 'static', 'icons'),
        'favicon.ico',
        mimetype='image/x-icon'
    )