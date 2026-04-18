from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email
from sqlalchemy import func
from app import db, oauth
from app.models import User, ApprovedStudent, Batch
from datetime import datetime
import logging

from . import auth_bp
logger = logging.getLogger(__name__)



# ── Forms ─────────────────────────────────────────────────────────────────────

class LoginForm(FlaskForm):
    email    = StringField('Email',    validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit   = SubmitField('Sign In')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _redirect_for(user):
    """Send each role to their home dashboard."""
    if user.role == 'admin':
        return url_for('admin.dashboard')
    if user.role == 'instructor':
        return url_for('instructor.dashboard')
    return url_for('student.scan')


# ── Password login (admin, instructor, legacy students) ───────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(_redirect_for(current_user))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter(
            func.lower(User.email) == form.email.data.strip().lower()
        ).first()

        if user and user.check_password(form.password.data):
            login_user(user)
            next_page = request.args.get('next')
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(next_page or _redirect_for(user))

        flash('Invalid email or password.', 'error')

    return render_template('auth/login.html', form=form)


# ── Register page (just shows the Google button now) ─────────────────────────

@auth_bp.route('/register')
def register():
    if current_user.is_authenticated:
        return redirect(_redirect_for(current_user))
    return render_template('auth/register.html')


# ── Google OAuth — Step 1: redirect to Google ────────────────────────────────

@auth_bp.route('/google/login')
def google_login():
    # Stash the 'next' URL so we can honour it after the callback
    session['oauth_next'] = request.args.get('next', '')
    redirect_uri = url_for('auth.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


# ── Google OAuth — Step 2: handle the return ─────────────────────────────────

@auth_bp.route('/google/callback')
def google_callback():
    try:
        token     = oauth.google.authorize_access_token()
        user_info = token.get('userinfo')
    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}")
        flash('Google sign-in failed. Please try again.', 'error')
        return redirect(url_for('auth.login'))

    if not user_info or not user_info.get('email'):
        flash('Could not get your email from Google. Please try again.', 'error')
        return redirect(url_for('auth.login'))

    email     = user_info['email'].strip().lower()
    google_id = user_info.get('sub')      # Google's permanent unique user ID

    # ── Case 1: user already exists → just log them in ───────────────────────
    user = User.query.filter(func.lower(User.email) == email).first()

    if user:
        if not user.google_id:
            # First time using Google — silently link their account
            user.google_id = google_id
            db.session.commit()
            logger.info(f"Linked Google ID to existing account: {email}")

        login_user(user)
        flash(f'Welcome back, {user.name}!', 'success')
        next_url = session.pop('oauth_next', None)
        return redirect(next_url or _redirect_for(user))

    # ── Case 2: new user — check the approved list ────────────────────────────
    approved = ApprovedStudent.query.filter(
        func.lower(ApprovedStudent.email) == email,
        ApprovedStudent.is_registered == False
    ).first()

    if not approved:
        # Nicer error: distinguish "never added" from "already registered"
        already_registered = ApprovedStudent.query.filter(
            func.lower(ApprovedStudent.email) == email,
            ApprovedStudent.is_registered == True
        ).first()

        if already_registered:
            flash(
                'This email is already registered. Please sign in instead.',
                'warning'
            )
        else:
            flash(
                'Your Google email is not on the approved list. '
                'Ask your admin to add you before registering.',
                'error'
            )
        return redirect(url_for('auth.login'))

    # ── Auto-create the student account ──────────────────────────────────────
    batch = Batch.query.get(approved.batch_id) if approved.batch_id else None

    new_user = User(
        email     = email,
        name      = approved.name,                          # Admin's approved name
        role      = 'student',
        batch_id  = approved.batch_id,
        level     = batch.current_level if batch else None, # Inherit from batch
        google_id = google_id,
        # password_hash intentionally left None — Google-only account
    )
    db.session.add(new_user)
    db.session.flush()   # Populate new_user.id before updating approved record

    # Mark the approved slot as taken
    approved.is_registered      = True
    approved.registered_user_id = new_user.id
    approved.registered_at      = datetime.utcnow()
    db.session.commit()

    login_user(new_user)
    logger.info(
        f"New student registered via Google: {email} "
        f"→ Batch '{batch.name if batch else 'None'}' / {new_user.level}"
    )
    flash(f'Welcome, {new_user.name}! Your account has been created.', 'success')
    next_url = session.pop('oauth_next', None)
    return redirect(next_url or url_for('student.scan'))


# ── Logout ────────────────────────────────────────────────────────────────────

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been signed out.', 'info')
    return redirect(url_for('auth.login'))