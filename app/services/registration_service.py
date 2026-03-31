"""
Registration service — all business logic lives here.

Kept completely free of Flask's request context so it is:
  - Unit-testable without an HTTP client
  - Reusable for admin-initiated or bulk registrations
  - Easy to reason about independently of routing
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError

from app import db, cache
from app.models import Batch, User, ApprovedStudent

logger = logging.getLogger(__name__)


# ── Result object ──────────────────────────────────────────────────────────────
@dataclass
class RegistrationResult:
    success: bool
    user: Optional[User] = None
    error: Optional[str] = None
    error_type: str = "error"   # Flask flash category: "error" | "info" | "warning"


# ── Cached batch loader ────────────────────────────────────────────────────────

@cache.memoize(timeout=60)
def get_active_batches() -> list[Batch]:
    """
    Returns active batches from Redis cache (TTL = 60 s).

    Why cache this?
      - Every GET to /register loads all active batches.
      - Batches change rarely (admin action only).
      - 60 s TTL means worst-case stale data for 1 minute after a change.
      - Under load with 100 concurrent users on the register page, this
        collapses 100 DB queries/minute into at most 1.
    """
    return Batch.query.filter_by(is_active=True).all()


def invalidate_batch_cache() -> None:
    """
    Call this from any route that creates, updates, or deactivates a batch.
    Ensures the registration form always reflects current batch state.

    Example:
        @admin_bp.route('/batches/<int:id>/deactivate', methods=['POST'])
        def deactivate_batch(id):
            ...
            invalidate_batch_cache()   # ← add this
            ...
    """
    cache.delete_memoized(get_active_batches)


# ── Core registration logic ───────────────────────────────────────────────────

def register_student(
    email_input: str,      # Pre-normalised: stripped + lowercased
    batch_id: int,
    level_input: str,
    password: str,
) -> RegistrationResult:
    """
    Validates and creates a student account.

    Key optimisations over the original:
      1. Batch fetched via SQLAlchemy's identity map (often 0 DB queries if
         already loaded; falls back to a single indexed lookup by PK).
      2. ApprovedStudent fetched with SELECT FOR UPDATE — this serialises
         concurrent registrations for the same email, making the
         is_registered check atomic and preventing duplicate accounts.
      3. The global User.email safety-net query is eliminated. A UNIQUE
         constraint on users.email (+ the FOR UPDATE lock on approved_record)
         provides the same guarantee and is enforced at the DB level.
      4. Google Sheets is never touched here. The caller enqueues the task
         after getting a successful result.

    Total DB round trips: 2 (down from 4).
    Blocking external calls: 0 (down from 1 with up to 12 s sleep).
    """

    # ── Step 1: Load batch ─────────────────────────────────────────────────
    # db.session.get() uses SQLAlchemy's identity map (in-session cache)
    # before hitting the DB. Under a single request this is effectively free
    # if the batch was already loaded (e.g. from get_active_batches()).
    batch = db.session.get(Batch, batch_id)
    if not batch or not batch.is_active:
        logger.warning("Registration attempt for invalid/inactive batch_id=%s", batch_id)
        return RegistrationResult(success=False, error="Invalid batch selected.")

    # ── Step 2: Level check (pure Python, zero DB) ─────────────────────────
    if level_input != batch.current_level:
        logger.warning(
            "Level mismatch: %s tried '%s', batch '%s' is '%s'",
            email_input, level_input, batch.name, batch.current_level,
        )
        return RegistrationResult(
            success=False,
            error=(
                f"Registration failed: {batch.name} is currently "
                f"at {batch.current_level.capitalize()} level."
            ),
        )

    # ── Step 3: Approved record with row-level lock ────────────────────────
    # SELECT ... FOR UPDATE acquires a row lock for the duration of this
    # transaction. If two requests arrive simultaneously for the same email:
    #   Request A: acquires lock, reads is_registered=False, creates user,
    #              commits, releases lock.
    #   Request B: waits for lock, reads is_registered=True, returns error.
    # Without this, both could read is_registered=False simultaneously and
    # both attempt to create a User — causing a duplicate or IntegrityError.
    approved_record = (
        ApprovedStudent.query
        .filter(
            ApprovedStudent.batch_id == batch_id,
            db.func.lower(ApprovedStudent.email) == email_input,
        )
        .with_for_update(nowait=False)   # Block until lock is available
        .first()
    )

    if not approved_record:
        logger.info(
            "Unauthorised registration: %s not approved for batch '%s'",
            email_input, batch.name,
        )
        return RegistrationResult(
            success=False,
            error=(
                f"The email {email_input} is not on the approved list "
                f"for {batch.name}. Please contact your administrator."
            ),
        )

    if approved_record.is_registered:
        logger.info("Duplicate registration attempt: %s", email_input)
        return RegistrationResult(
            success=False,
            error="This account is already registered. Please log in.",
            error_type="info",
        )

    # ── Step 4: Create user + mark approved record (single transaction) ────
    try:
        user = User(
            name=approved_record.name,  # Admin-canonical spelling
            email=email_input,
            role="student",
            level=level_input,
            batch_id=batch_id,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()   # Populate user.id before updating approved_record

        approved_record.is_registered = True
        approved_record.registered_user_id = user.id
        approved_record.registered_at = datetime.now(timezone.utc)

        db.session.commit()
        logger.info("Registered student: %s (id=%s)", user.email, user.id)
        return RegistrationResult(success=True, user=user)

    except IntegrityError:
        db.session.rollback()
        # UNIQUE constraint on users.email caught a race condition that
        # slipped past the FOR UPDATE lock (e.g. different batch_id).
        logger.warning("IntegrityError (race condition) for %s", email_input)
        return RegistrationResult(
            success=False,
            error="Email already in use. Please log in or contact support.",
        )

    except Exception as exc:
        db.session.rollback()
        logger.critical("DB error during registration for %s: %s", email_input, exc, exc_info=True)
        return RegistrationResult(
            success=False,
            error="A critical error occurred. Please try again or contact support.",
        )