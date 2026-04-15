"""
Admin Blueprint - Batch and Student Management
Handles:
- Batch creation and management
- Approved student lists
- Batch level promotion
- Student assignment
- Admin Blueprint - Batch and Student Management
- ALL queries optimized with database-level aggregations
"""


from flask import render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from functools import wraps
from sqlalchemy import func, and_
from app import db
from app.models import User, Batch, ApprovedStudent, Attendance, BatchSchedule, BatchException
from datetime import datetime, timedelta
from app.sheets_sync import create_sheet_tab, append_student_to_sheet
import threading
from . import admin_bp
import logging
from flask import current_app
from datetime import date
from app.instructor_queries import invalidate_excluded_dates_cache

# Initialize logger for this module
logger = logging.getLogger(__name__)


def admin_required(f):
    """Decorator to ensure only admins can access routes"""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if current_user.role != 'admin':
            flash("Access denied: Admins only.", "error")
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function




# ============================================================================
# DASHBOARD
# ============================================================================

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    """
    Admin dashboard - overview of system
    """
    # Simple counts - database level
    total_batches = db.session.query(func.count(Batch.id)).filter(
        Batch.is_active == True
    ).scalar()
    
    total_students = db.session.query(func.count(User.id)).filter(
        User.role == 'student'
    ).scalar()
    
    total_instructors = db.session.query(func.count(User.id)).filter(
        User.role == 'instructor'
    ).scalar()
    
    unassigned_students = db.session.query(func.count(User.id)).filter(
        User.role == 'student',
        User.batch_id == None
    ).scalar()
    
    # Recent attendance (last 24 hours)
    yesterday = datetime.utcnow() - timedelta(days=1)
    recent_attendance = db.session.query(func.count(Attendance.id)).filter(
        Attendance.timestamp >= yesterday
    ).scalar()
    
    # Get batches with aggregated counts - SINGLE QUERY!
    batches_with_stats = db.session.query(
        Batch,
        func.count(func.distinct(User.id)).label('student_count'),
        func.count(func.distinct(ApprovedStudent.id)).label('approved_count')
    ).outerjoin(
        User, User.batch_id == Batch.id
    ).outerjoin(
        ApprovedStudent, ApprovedStudent.batch_id == Batch.id
    ).filter(
        Batch.is_active == True
    ).group_by(
        Batch.id
    ).all()
    
    # Format for template
    batches = []
    for batch, student_count, approved_count in batches_with_stats:
        batches.append({
            'id': batch.id,
            'name': batch.name,
            'description': batch.description,
            'current_level': batch.current_level,
            'student_count': student_count or 0,
            'approved_count': approved_count or 0
        })
    
    return render_template('admin/dashboard.html',
                         total_batches=total_batches or 0,
                         total_students=total_students or 0,
                         total_instructors=total_instructors or 0,
                         unassigned_students=unassigned_students or 0,
                         recent_attendance=recent_attendance or 0,
                         batches=batches)


# ============================================================================
# BATCH MANAGEMENT
# ============================================================================

@admin_bp.route('/batches')
@admin_required
def batches():
    """
    List all batches
    """
    batches_with_stats = db.session.query(
        Batch,
        func.count(func.distinct(User.id)).label('student_count'),
        func.count(func.distinct(ApprovedStudent.id)).label('approved_count')
    ).outerjoin(
        User, and_(User.batch_id == Batch.id, User.role == 'student')
    ).outerjoin(
        ApprovedStudent, ApprovedStudent.batch_id == Batch.id
    ).group_by(
        Batch.id
    ).order_by(
        Batch.created_at.desc()
    ).all()
    
    # Format for template
    batches = []
    for batch, student_count, approved_count in batches_with_stats:
        batches.append({
            'id': batch.id,
            'name': batch.name,
            'description': batch.description,
            'current_level': batch.current_level,
            'is_active': batch.is_active,
            'created_at': batch.created_at,
            'student_count': student_count or 0,
            'approved_count': approved_count or 0
        })
    
    return render_template('admin/batches.html', batches=batches)
         

@admin_bp.route('/batches/create', methods=['GET', 'POST'])
@admin_required
def create_batch():
    """Create new batch with class schedule"""
    if request.method == 'POST':
        name        = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        class_days  = request.form.getlist('class_days')  # e.g. ['0', '2', '4']

        if not name:
            flash('Batch name is required', 'error')
            return redirect(url_for('admin.create_batch'))

        if not class_days:
            flash('Please select at least one class day', 'error')
            return redirect(url_for('admin.create_batch'))

        # Check duplicates
        existing_count = db.session.query(func.count(Batch.id)).filter(
            func.lower(Batch.name) == name.lower()
        ).scalar()

        if existing_count > 0:
            flash(f'Batch "{name}" already exists', 'error')
            return redirect(url_for('admin.create_batch'))

        # Create batch
        batch = Batch(
            name=name,
            description=description,
            current_level='beginner',
            is_active=True,
            level_started_at=datetime.utcnow()
        )
        db.session.add(batch)
        db.session.flush()  # Gets batch.id without committing

        # Save class schedule
        for day in class_days:
            db.session.add(BatchSchedule(batch_id=batch.id, weekday=int(day)))

        db.session.commit()

        # ── Create Google Sheet tab for this batch ─────────────────────────

        
        # ── Fire sheet creation in background — don't block the response ──
        
        thread = threading.Thread(target=create_sheet_tab, args=(batch,), daemon=True)
        thread.start()
        # ──────────────────────────────────────────────────────────────────

        # ──────────────────────────────────────────────────────────────────

        flash(f'Batch "{name}" created successfully!', 'success')
        return redirect(url_for('admin.batches'))

    return render_template('admin/create_batch.html')



@admin_bp.route('/batches/<int:batch_id>')
@admin_required
def view_batch(batch_id):
    """
    View batch details
    """
    batch = Batch.query.get_or_404(batch_id)
    
    # Get registered students count - database level
    registered_count = db.session.query(func.count(User.id)).filter(
        User.batch_id == batch_id,
        User.role == 'student'
    ).scalar()
    
    # Get approved students count - database level
    approved_count = db.session.query(func.count(ApprovedStudent.id)).filter(
        ApprovedStudent.batch_id == batch_id
    ).scalar()
    
    # Get registered students (need full list for display)
    registered_students = User.query.filter_by(
        batch_id=batch_id,
        role='student'
    ).order_by(User.name).all()
    
    # Get approved students with registration status - SINGLE QUERY with JOIN
    approved_students = db.session.query(
        ApprovedStudent,
        User.id.label('registered_user_id'),
        User.email.label('registered_email')
    ).outerjoin(
        User,
        and_(
            ApprovedStudent.registered_user_id == User.id,
            ApprovedStudent.is_registered == True
        )
    ).filter(
        ApprovedStudent.batch_id == batch_id
    ).order_by(
        ApprovedStudent.name
    ).all()
    
    # Calculate pending (approved but not registered) - database level
    pending_count = db.session.query(func.count(ApprovedStudent.id)).filter(
        ApprovedStudent.batch_id == batch_id,
        ApprovedStudent.is_registered == False
    ).scalar()
    
    # Recent attendance for this batch - database level
    last_30_days = datetime.utcnow() - timedelta(days=30)
    attendance_count = db.session.query(func.count(Attendance.id)).join(
        User, User.id == Attendance.user_id
    ).filter(
        User.batch_id == batch_id,
        Attendance.timestamp >= last_30_days
    ).scalar()
    
    return render_template('admin/view_batch.html',
                         batch=batch,
                         registered_students=registered_students,
                         approved_students=approved_students,
                         registered_count=registered_count or 0,
                         approved_count=approved_count or 0,
                         pending_count=pending_count or 0,
                         attendance_count=attendance_count or 0)


@admin_bp.route('/batches/<int:batch_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_batch(batch_id):
    """Edit batch details and class schedule"""
    batch = Batch.query.get_or_404(batch_id)

    if request.method == 'POST':
        batch.name        = request.form.get('name', '').strip()
        batch.description = request.form.get('description', '').strip()
        batch.is_active   = request.form.get('is_active') == 'on'
        class_days        = request.form.getlist('class_days')

        if not class_days:
            flash('Please select at least one class day', 'error')
            return redirect(url_for('admin.edit_batch', batch_id=batch_id))

        # Replace existing schedule — delete old, insert new
        BatchSchedule.query.filter_by(batch_id=batch.id).delete()
        for day in class_days:
            db.session.add(BatchSchedule(batch_id=batch.id, weekday=int(day)))

        db.session.commit()
        flash(f'Batch "{batch.name}" updated successfully!', 'success')
        return redirect(url_for('admin.view_batch', batch_id=batch_id))

    # Pass current schedule days to template so checkboxes are pre-selected
    current_days = {s.weekday for s in batch.schedules}
    return render_template('admin/edit_batch.html', batch=batch, current_days=current_days)


# ============================================================================
# PROMOTE BATCH ROUTE  
 
@admin_bp.route('/batches/<int:batch_id>/promote', methods=['POST'])
@admin_required
def promote_batch(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    success, old_level, new_level = batch.promote_to_next_level()

    if success:
        student_count = db.session.query(func.count(User.id)).filter(
            User.batch_id == batch_id, User.role == 'student'
        ).scalar()

        db.session.commit()

        # 1. Get the app object to pass into the thread
        app = current_app._get_current_object()
        
        # 2. Get students before the thread starts
        students = User.query.filter_by(batch_id=batch_id, role='student').all()

        def sync_promotion(app_context, batch_id):
            # Use the logger defined at the top of your routes.py
            with app_context.app_context():
                # Re-fetch the batch inside the thread context
                t_batch = Batch.query.get(batch_id)
                if not t_batch:
                    logger.error(f"Sync Thread Error: Batch ID {batch_id} not found.")
                    return

                t_students = User.query.filter_by(batch_id=batch_id, role='student').all()
                
                try:
                    create_sheet_tab(t_batch)
                    for student in t_students:
                        append_student_to_sheet(student)
                    
                    # Log success so you know the background task finished
                    logger.info(f"SUCCESS: Google Sheets sync completed for Batch '{t_batch.name}'")

                except Exception:
                    # logger.exception automatically captures the Traceback/Stack Trace
                    logger.exception(f"CRITICAL: Google Sheets Sync failed for Batch ID {batch_id}")

        # Start the thread and pass the app object and batch ID
        thread = threading.Thread(target=sync_promotion, args=(app, batch.id), daemon=True)
        thread.start()

        flash(f'✓ Batch "{batch.name}" promoted to {new_level}!', 'success')
    else:
        flash(f'Batch already at {batch.current_level} level', 'warning')

    return redirect(url_for('admin.view_batch', batch_id=batch_id))


@admin_bp.route('/batches/<int:batch_id>/unpromote', methods=['POST'])
@admin_required
def unpromote_batch(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    old_level = batch.current_level
    
    demotion_map = {'alumni':'advanced','advanced':'intermediate','intermediate': 'beginner'}
    new_level = demotion_map.get(old_level)
    
    if not new_level:
        flash(f'Cannot unpromote "{batch.name}" from {old_level}.', 'warning')
        return redirect(url_for('admin.view_batch', batch_id=batch_id))

    try:
        # BULK UPDATE
        db.session.query(User).filter(
            User.batch_id == batch_id, 
            User.role == 'student'
        ).update({'level': new_level}, synchronize_session=False)
        
        batch.current_level = new_level
        db.session.commit()
        
        # logging for the Admin
        logger.warning(
            f"UNPROMOTE EVENT: Batch '{batch.name}' (ID: {batch_id}) reverted to {new_level}. "
            f"Action Required: Manual cleanup of Google Sheet tab '{batch.name} - {old_level.capitalize()}'."
        )

        flash(f'↺ "{batch.name}" reverted to {new_level}. Please manually delete the old tab in Google Sheets.', 'success')
              
    except Exception as e:
        db.session.rollback()
        flash('An error occurred during unpromotion.', 'error')

    return redirect(url_for('admin.view_batch', batch_id=batch_id))

# --- DEACTIVATE (Soft Delete) ---
@admin_bp.route('/batches/<int:batch_id>/deactivate', methods=['POST'])
@admin_required
def deactivate_batch(batch_id):
    """Hide batch from active views but keep data for records/history."""
    batch = Batch.query.get_or_404(batch_id)
    batch.is_active = False
    
    # Optional: Unassign students so they can join new batches
    db.session.query(User).filter(User.batch_id == batch_id).update(
        {User.batch_id: None}, synchronize_session=False
    )
    
    db.session.commit()
    logger.info(f"Batch {batch.name} deactivated by {current_user.email}")
    flash(f'Batch "{batch.name}" is now inactive.', 'info')
    return redirect(url_for('admin.batches'))

# --- CASCADE DELETE (Hard Delete) ---
@admin_bp.route('/batches/<int:batch_id>/delete-permanent', methods=['POST'])
@admin_required
def permanent_delete_batch(batch_id):
    """The Wipes everything related to the batch."""
    batch = Batch.query.get_or_404(batch_id)
    name = batch.name
    
    try:
        # 1. Clear Schedule
        BatchSchedule.query.filter_by(batch_id=batch_id).delete()
        # 2. Clear Approved List
        ApprovedStudent.query.filter_by(batch_id=batch_id).delete()
        # 3. Clear Attendance Records (Critical for a clean wipe)
        attendance_ids = db.session.query(Attendance.id).join(User).filter(User.batch_id == batch_id).all()
        Attendance.query.filter(Attendance.id.in_([a[0] for a in attendance_ids])).delete(synchronize_session=False)
        
        db.session.delete(batch)
        db.session.commit()
        
        logger.warning(f"PERMANENT DELETE: Batch {name} wiped by {current_user.email}")
        flash(f'Batch "{name}" and all history permanently deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to wipe batch {batch_id}: {e}")
        flash("Error during permanent deletion.", "error")
        
    return redirect(url_for('admin.batches'))


# ============================================================================
# APPROVED STUDENT LIST MANAGEMENT - OPTIMIZED
# ============================================================================

@admin_bp.route('/batches/<int:batch_id>/students/manage')
@admin_required
def manage_approved_students(batch_id):
    """
    Manage approved student list for a batch
    Single query with JOIN for registration status
    """
    batch = Batch.query.get_or_404(batch_id)
    
    # Get approved students with registration info - SINGLE QUERY
    approved_students_with_status = db.session.query(
        ApprovedStudent,
        User.email.label('registered_email'),
        User.name.label('registered_name')
    ).outerjoin(
        User,
        ApprovedStudent.registered_user_id == User.id
    ).filter(
        ApprovedStudent.batch_id == batch_id
    ).order_by(
        ApprovedStudent.name
    ).all()
    
    return render_template('admin/manage_students.html',
                         batch=batch,
                         approved_students=approved_students_with_status)


@admin_bp.route('/batches/<int:batch_id>/students/add', methods=['POST'])
@admin_required
def add_approved_student(batch_id):
    """Add a single student to the approved list with required email verification."""
    batch = Batch.query.get_or_404(batch_id)
    
    # 1. Capture and Clean Input
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower() # Normalize to lowercase
    
    # 2. Strict Validation: Both fields are now mandatory
    if not name or not email:
        logger.warning(f"Admin {current_user.email} attempted to add student with missing fields.")
        flash('Both Student Name and Email are strictly required.', 'error')
        return redirect(url_for('admin.manage_approved_students', batch_id=batch_id))
    
    try:
        # 3. Duplicate Check: Check by EMAIL (The unique identifier)
        existing_student = ApprovedStudent.query.filter(
            ApprovedStudent.batch_id == batch_id,
            db.func.lower(ApprovedStudent.email) == email
        ).first()
        
        if existing_student:
            logger.info(f"Duplicate entry blocked: Email {email} already in Batch {batch.id}")
            flash(f'The email "{email}" is already on the approved list for this batch.', 'warning')
            return redirect(url_for('admin.manage_approved_students', batch_id=batch_id))
        
        # 4. Add to approved list
        # We save 'name' as provided (Title Case usually) but email as lowercase
        approved = ApprovedStudent(
            batch_id=batch_id,
            name=name,
            email=email
        )
        
        db.session.add(approved)
        db.session.commit()
        
        logger.info(f"Admin {current_user.email} added {email} to {batch.name} approved list.")
        flash(f'✓ {name} ({email}) added to approved list for {batch.name}.', 'success')

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error adding single student {email}: {e}")
        flash("A database error occurred. Please try again.", "error")
    
    return redirect(url_for('admin.manage_approved_students', batch_id=batch_id))


@admin_bp.route('/batches/<int:batch_id>/students/bulk-upload', methods=['POST'])
@admin_required
def bulk_upload_students(batch_id):
    batch = Batch.query.get_or_404(batch_id)
    
    student_data = request.form.get('student_data', '')
    
    if not student_data:
        flash('Please enter student details', 'error')
        return redirect(url_for('admin.manage_approved_students', batch_id=batch_id))
    
    # Get existing emails in this batch to prevent duplicates
    existing_emails = db.session.query(ApprovedStudent.email).filter(
        ApprovedStudent.batch_id == batch_id,
        ApprovedStudent.email.isnot(None)
    ).all()
    existing_emails_set = {email[0].lower() for email in existing_emails}
    
    new_students = []
    skipped_count = 0
    invalid_count = 0  # Track lines that failed the Name, Email format
    
    # Process each line
    lines = student_data.strip().split('\n')
    for line in lines:
        if not line.strip():
            continue
            
        # Split by comma
        parts = [p.strip() for p in line.split(',')]
        
        # ENFORCEMENT: Ensure both Name AND Email are provided
        if len(parts) < 2 or not parts[0] or not parts[1]:
            invalid_count += 1
            continue
            
        name = parts[0]
        email = parts[1]
        
        # Validation: Check if email already exists in this batch
        if email.lower() in existing_emails_set:
            skipped_count += 1
            continue
            
        new_students.append(ApprovedStudent(
            batch_id=batch_id,
            name=name,
            email=email
        ))
    
    # Bulk insert
    if new_students:
        db.session.bulk_save_objects(new_students)
        db.session.commit()
    
    # Construct feedback message
    message = f'✓ Added {len(new_students)} students.'
    if skipped_count > 0:
        message += f' Skipped {skipped_count} duplicates.'
    if invalid_count > 0:
        message += f' Skipped {invalid_count} invalid lines (missing email).'
        
    flash(message, 'success' if len(new_students) > 0 else 'warning')
    return redirect(url_for('admin.manage_approved_students', batch_id=batch_id))

@admin_bp.route('/approved-students/<int:id>/delete', methods=['POST'])
@admin_required
def delete_approved_student(id):
    """Remove student from approved list"""
    approved = ApprovedStudent.query.get_or_404(id)
    batch_id = approved.batch_id
    name = approved.name
    
    # Check if student is already registered
    if approved.is_registered:
        flash(f'{name} has already registered and cannot be removed', 'error')
        return redirect(url_for('admin.manage_approved_students', batch_id=batch_id))
    
    db.session.delete(approved)
    db.session.commit()
    
    flash(f'{name} removed from approved list', 'success')
    return redirect(url_for('admin.manage_approved_students', batch_id=batch_id))

# --- UNASSIGN (Soft Removal) ---
@admin_bp.route('/students/<int:user_id>/unassign', methods=['POST'])
@admin_required
def unassign_student(user_id):
    """Remove a student from their batch but keep their account and attendance history."""
    student = User.query.filter_by(id=user_id, role='student').first_or_404()
    old_batch_name = student.batch.name if student.batch else "Unassigned"
    
    student.batch_id = None
    student.level = None
    db.session.commit()
    
    logger.info(f"Admin {current_user.email} unassigned {student.email} from {old_batch_name}")
    flash(f'Student {student.name} has been unassigned and is now in the "Unassigned" pool.', 'info')
    return redirect(request.referrer or url_for('admin.students'))

# --- PERMANENT DELETE (Hard Removal) ---
@admin_bp.route('/students/<int:user_id>/delete-permanent', methods=['POST'])
@admin_required
def permanent_delete_student(user_id):
    """The Nuclear Option: Wipes the User, their Attendance, and resets their Approval status."""
    student = User.query.filter_by(id=user_id, role='student').first_or_404()
    email = student.email
    
    try:
        # 1. Delete Attendance records
        Attendance.query.filter_by(user_id=user_id).delete()
        
        # 2. Reset the ApprovedStudent record so they can register again if needed
        approved = ApprovedStudent.query.filter_by(registered_user_id=user_id).first()
        if approved:
            approved.is_registered = False
            approved.registered_user_id = None
            approved.registered_at = None
        
        # 3. Delete the User record
        db.session.delete(student)
        db.session.commit()
        
        logger.warning(f"PERMANENT DELETE: User {email} wiped by {current_user.email}")
        flash(f'User account for {email} and all attendance history has been permanently deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to delete student {user_id}: {e}")
        flash("Error during permanent deletion of student.", "error")
        
    return redirect(url_for('admin.students'))


# ============================================================================
# REGISTERED STUDENTS MANAGEMENT - OPTIMIZED
# ============================================================================

@admin_bp.route('/students')
@admin_required
def students():
    """
    List all registered students
    """
    batch_id = request.args.get('batch_id', type=int)
    
    # Build query with JOIN to get batch info
    query = db.session.query(
        User,
        Batch.name.label('batch_name'),
        Batch.current_level.label('batch_level')
    ).outerjoin(
        Batch, User.batch_id == Batch.id
    ).filter(
        User.role == 'student'
    )
    
    # Filter by batch if specified
    if batch_id:
        query = query.filter(User.batch_id == batch_id)
    
    students_with_batch = query.order_by(User.name).all()
    
    # Get all active batches for filter dropdown
    batches = Batch.query.filter_by(is_active=True).order_by(Batch.name).all()
    
    return render_template('admin/students.html',
                         students=students_with_batch,
                         batches=batches,
                         selected_batch=batch_id)

# ============================================================================
# REGISTERED Instructor account - OPTIMIZED
# ============================================================================

@admin_bp.route('/create-instructor', methods=['GET', 'POST'])
@admin_required
def create_instructor():
    """Admin can create instructor accounts"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        
        if not all([name, email, password]):
            flash('All fields required', 'error')
            return redirect(url_for('admin.create_instructor'))
        
        # Check if email exists
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('admin.create_instructor'))
        
        # Create instructor
        instructor = User(
            name=name,
            email=email,
            role='instructor',
            level=None,
            batch_id=None
        )
        instructor.set_password(password)
        
        db.session.add(instructor)
        db.session.commit()
        
        flash(f'✓ Instructor {name} created successfully!', 'success')
        return redirect(url_for('admin.dashboard'))
    
    return render_template('admin/create_instructor.html')


# ── Global holidays ──────────────────────────────────────────────────────────

@admin_bp.route('/holidays', methods=['GET'])
@admin_required
def list_holidays():
    from app.models import Holiday, BatchException, Batch
    holidays   = Holiday.query.order_by(Holiday.date).all()
    exceptions = BatchException.query.order_by(BatchException.date).all()
    batches    = Batch.query.filter_by(is_active=True).order_by(Batch.name).all()
    return render_template('admin/holidays.html',
                           holidays=holidays,
                           exceptions=exceptions,
                           batches=batches,
                           today=date.today())


@admin_bp.route('/holidays/add', methods=['POST'])
@admin_required
def add_holiday():
    from app.models import Holiday
    from datetime import date as date_type
    name      = request.form.get('name', '').strip()
    date_str  = request.form.get('date', '').strip()

    if not name or not date_str:
        flash('Name and date are required.', 'error')
        return redirect(url_for('admin.list_holidays'))

    try:
        holiday_date = date_type.fromisoformat(date_str)
    except ValueError:
        flash('Invalid date format.', 'error')
        return redirect(url_for('admin.list_holidays'))

    existing = Holiday.query.filter_by(date=holiday_date).first()
    if existing:
        flash(f'A holiday already exists on {holiday_date}.', 'warning')
        return redirect(url_for('admin.list_holidays'))

    db.session.add(Holiday(name=name, date=holiday_date))
    db.session.commit()
    invalidate_excluded_dates_cache()
    flash(f'Holiday "{name}" added for {holiday_date}.', 'success')
    return redirect(url_for('admin.list_holidays'))


@admin_bp.route('/holidays/<int:holiday_id>/delete', methods=['POST'])
@admin_required
def delete_holiday(holiday_id):
    from app.models import Holiday
    holiday = Holiday.query.get_or_404(holiday_id)
    db.session.delete(holiday)
    db.session.commit()
    invalidate_excluded_dates_cache()
    flash(f'Holiday "{holiday.name}" removed.', 'success')
    return redirect(url_for('admin.list_holidays'))


# ── Batch exceptions ─────────────────────────────────────────────────────────

@admin_bp.route('/batch-exceptions/add', methods=['POST'])
@admin_required
def add_batch_exception():
    from app.models import BatchException
    from datetime import date as date_type
    batch_id  = request.form.get('batch_id', type=int)
    name      = request.form.get('name', '').strip()
    date_str  = request.form.get('date', '').strip()

    if not batch_id or not name or not date_str:
        flash('Batch, reason, and date are required.', 'error')
        return redirect(url_for('admin.list_holidays'))

    try:
        exc_date = date_type.fromisoformat(date_str)
    except ValueError:
        flash('Invalid date format.', 'error')
        return redirect(url_for('admin.list_holidays'))

    existing = BatchException.query.filter_by(batch_id=batch_id, date=exc_date).first()
    if existing:
        flash(f'An exception for this batch already exists on {exc_date}.', 'warning')
        return redirect(url_for('admin.list_holidays'))

    db.session.add(BatchException(batch_id=batch_id, name=name, date=exc_date))
    db.session.commit()
    invalidate_excluded_dates_cache()
    flash(f'Batch exception added for {exc_date}.', 'success')
    return redirect(url_for('admin.list_holidays'))


@admin_bp.route('/batch-exceptions/<int:exception_id>/delete', methods=['POST'])
@admin_required
def delete_batch_exception(exception_id):
    exc = BatchException.query.get_or_404(exception_id)
    db.session.delete(exc)
    db.session.commit()
    invalidate_excluded_dates_cache()
    flash('Batch exception removed.', 'success')
    return redirect(url_for('admin.list_holidays'))