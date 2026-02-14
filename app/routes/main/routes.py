from flask import render_template
from flask_login import current_user
from . import main_bp

@main_bp.route('/')
def index():
    return render_template('index.html')

# not in place yet. later

# @main_bp.route('/about')
# def about():
#     return render_template('about.html')

# @main_bp.route('/contact')
# def contact():
#     return render_template('contact.html')