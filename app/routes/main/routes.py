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