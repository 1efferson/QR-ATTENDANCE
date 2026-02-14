from app import create_app, db
from app.models import User, Attendance

app = create_app()

@app.shell_context_processor
def make_shell_context():
    """Allows you to work with db models in flask shell without imports."""
    return {'db': db, 'User': User, 'Attendance': Attendance}

if __name__ == '__main__':
    # In production, use Gunicorn instead of app.run()
    app.run(debug=True, host='0.0.0.0', port=5000)