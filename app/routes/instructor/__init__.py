from flask import Blueprint

# Internal name must be 'instructor' to match your url_for targets
instructor_bp = Blueprint('instructor', __name__)

from . import routes