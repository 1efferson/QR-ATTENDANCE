
from flask import Blueprint

# create the object
auth_bp = Blueprint('auth', __name__)

# import from the current directory
from . import routes

