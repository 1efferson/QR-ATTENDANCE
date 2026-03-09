
from flask import Blueprint

# create the object
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# import from the current directory
from . import routes

