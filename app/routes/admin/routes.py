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
from app.models import User, Batch, ApprovedStudent, Attendance, BatchSchedule
from datetime import datetime, timedelta
from app.sheets_sync import create_sheet_tab
from . import admin_bp


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

        create_sheet_tab(batch)
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
    """Promote entire batch to next level and create new Google Sheet tab."""
    batch = Batch.query.get_or_404(batch_id)
 
    success, old_level, new_level = batch.promote_to_next_level()
 
    if success:
        student_count = db.session.query(func.count(User.id)).filter(
            User.batch_id == batch_id,
            User.role == 'student'
        ).scalar()
 
        db.session.commit()
 
        # ── Create fresh Google Sheet tab for the new level ────────────────
        from app.sheets_sync import create_sheet_tab, append_student_to_sheet
        create_sheet_tab(batch)   # Creates "CodeCamp 3&4 - Intermediate" tab
 
        # Seed all current students into the new tab
        students = User.query.filter_by(batch_id=batch_id, role='student').all()
        for student in students:
            append_student_to_sheet(student)
        # ──────────────────────────────────────────────────────────────────
 
        flash(
            f'✓ Batch "{batch.name}" promoted from {old_level} to {new_level}! '
            f'{student_count} students updated.',
            'success'
        )
    else:
        flash(f'Batch "{batch.name}" is already at {batch.current_level} level', 'warning')
 
    return redirect(url_for('admin.view_batch', batch_id=batch_id))

@admin_bp.route('/batches/<int:batch_id>/delete', methods=['POST'])
@admin_required
def delete_batch(batch_id):
    """
    Deactivate batch
    Bulk update at database level
    """
    batch = Batch.query.get_or_404(batch_id)
    
    # Deactivate instead of delete
    batch.is_active = False
    
    # Unassign all students - BULK UPDATE at database level
    db.session.query(User).filter(
        User.batch_id == batch_id
    ).update(
        {User.batch_id: None},
        synchronize_session=False
    )
    
    db.session.commit()
    flash(f'Batch "{batch.name}" deactivated and students unassigned', 'success')
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
    """Add single student to approved list"""
    batch = Batch.query.get_or_404(batch_id)
    
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    
    if not name:
        flash('Student name is required', 'error')
        return redirect(url_for('admin.manage_approved_students', batch_id=batch_id))
    
    # Check if already exists - database level
    existing_count = db.session.query(func.count(ApprovedStudent.id)).filter(
        ApprovedStudent.batch_id == batch_id,
        func.lower(ApprovedStudent.name) == name.lower()
    ).scalar()
    
    if existing_count > 0:
        flash(f'{name} is already on the approved list', 'warning')
        return redirect(url_for('admin.manage_approved_students', batch_id=batch_id))
    
    # Add to approved list
    approved = ApprovedStudent(
        batch_id=batch_id,
        name=name,
        email=email if email else None
    )
    
    db.session.add(approved)
    db.session.commit()
    
    flash(f'{name} added to approved list for {batch.name}', 'success')
    return redirect(url_for('admin.manage_approved_students', batch_id=batch_id))


@admin_bp.route('/batches/<int:batch_id>/students/bulk-upload', methods=['POST'])
@admin_required
def bulk_upload_students(batch_id):
    """
    Bulk upload students (one name per line)
    Batch insert with database-level duplicate checking
    """
    batch = Batch.query.get_or_404(batch_id)
    
    student_names = request.form.get('student_names', '')
    
    if not student_names:
        flash('Please enter student names', 'error')
        return redirect(url_for('admin.manage_approved_students', batch_id=batch_id))
    
    # Parse names (one per line)
    names = [line.strip() for line in student_names.split('\n') if line.strip()]
    
    # Get existing names in one query - database level
    existing_names = db.session.query(
        func.lower(ApprovedStudent.name)
    ).filter(
        ApprovedStudent.batch_id == batch_id
    ).all()
    
    existing_names_set = {name[0] for name in existing_names}
    
    # Prepare batch insert
    new_students = []
    skipped_count = 0
    
    for name in names:
        if name.lower() in existing_names_set:
            skipped_count += 1
            continue
        
        new_students.append(ApprovedStudent(
            batch_id=batch_id,
            name=name
        ))
    
    # Bulk insert - single database operation
    if new_students:
        db.session.bulk_save_objects(new_students)
        db.session.commit()
    
    added_count = len(new_students)
    
    flash(f'✓ Added {added_count} students. Skipped {skipped_count} duplicates.', 'success')
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