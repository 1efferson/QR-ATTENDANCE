from flask import Blueprint

# Create the blueprint object
student_bp = Blueprint('student', __name__)

# Import the routes at the bottom to avoid circular imports
from . import routes