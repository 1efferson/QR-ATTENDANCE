"""
sheets_sync.py
==============
Google Sheets attendance sync module for QR-Attend.

Sheet layout (Rows = Students, Columns = Dates):
  Row 1       : Batch title  e.g. "CODECAMP 3&4"
  Row 2       : Empty
  Row 3       : Headers — "NAMES", "Percentage", "Days Present", "Days Absent", "", <dates...>
  Row 4+      : One row per student — name in col A, 1/0 from col F onwards

  1 = Present  (green via conditional formatting in Google Sheets)
  0 = Absent   (red via conditional formatting in Google Sheets)

One tab per batch per level:
  "CodeCamp 3&4 - Beginner"
  "CodeCamp 3&4 - Intermediate"
  "CodeCamp 3&4 - Advanced"

Reads from .env:
  GOOGLE_SHEETS_CREDENTIALS_FILE  — path to service account JSON key
  GOOGLE_SHEET_ID                 — spreadsheet ID from the URL
"""

import logging
import os
from datetime import date, datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, WorksheetNotFound

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

DATE_FORMAT    = "%b %d %Y"   # e.g. "Jun 02 2025"
VALUE_PRESENT  = 1
VALUE_ABSENT   = 0

# Sheet layout anchors — must match the physical sheet structure
HEADER_ROW     = 3   # Row 3: "NAMES", "Percentage", "Days Present", "Days Absent", "", dates...
FIRST_DATA_ROW = 4   # Student names start at row 4
FIRST_DATE_COL = 6   # Column F — A=name, B=%, C=days present, D=days absent, E=buffer


# ---------------------------------------------------------------------------
# Auth / worksheet helpers
# ---------------------------------------------------------------------------

def _get_client() -> gspread.Client:
    creds_path = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_FILE", "credentials.json")
    if not Path(creds_path).exists():
        raise FileNotFoundError(
            f"Service account key not found at '{creds_path}'. "
            "Set GOOGLE_SHEETS_CREDENTIALS_FILE in your .env."
        )
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_spreadsheet():
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise ValueError(
            "GOOGLE_SHEET_ID is not set. Add it to your .env — find it in "
            "the spreadsheet URL: docs.google.com/spreadsheets/d/<SHEET_ID>/edit"
        )
    return _get_client().open_by_key(sheet_id)


def _get_worksheet(worksheet_name: str) -> gspread.Worksheet:
    """Open spreadsheet by GOOGLE_SHEET_ID and return the named tab."""
    spreadsheet = _get_spreadsheet()
    try:
        return spreadsheet.worksheet(worksheet_name)
    except WorksheetNotFound:
        available = [ws.title for ws in spreadsheet.worksheets()]
        raise WorksheetNotFound(
            f"Tab '{worksheet_name}' not found. Available tabs: {available}"
        )


def _worksheet_name(batch) -> str:
    """
    Build the tab name from batch name + current level.
    e.g. "CodeCamp 3&4 - Beginner"
    This is the single source of truth for tab naming across all functions.
    """
    return f"{batch.name} - {batch.current_level.capitalize()}"


# ---------------------------------------------------------------------------
# Row / column locators
# ---------------------------------------------------------------------------

def _get_or_create_date_col(ws: gspread.Worksheet, date_str: str) -> int:
    """
    Return the 1-based column index for date_str, searching from col F onwards.
    Columns A-E are reserved for name, %, days present, days absent, buffer.
    Appends a new date column if not found.
    """
    header_row = ws.row_values(HEADER_ROW)

    for idx, cell in enumerate(header_row, start=1):
        if idx < FIRST_DATE_COL:
            continue
        if cell.strip() == date_str:
            return idx

    next_col = max(FIRST_DATE_COL, len(header_row) + 1)
    ws.update_cell(HEADER_ROW, next_col, date_str)
    logger.info("Created new date column %d for %s", next_col, date_str)
    return next_col


def _find_student_row(ws: gspread.Worksheet, student_name: str):
    """
    Return the 1-based row index for student_name (case-insensitive).
    Searches from FIRST_DATA_ROW downwards. Returns None if not found.
    """
    name_col   = ws.col_values(1)
    name_lower = student_name.strip().lower()
    for idx, cell in enumerate(name_col, start=1):
        if idx < FIRST_DATA_ROW:
            continue
        if cell.strip().lower() == name_lower:
            return idx
    return None


# ---------------------------------------------------------------------------
# Tab management
# ---------------------------------------------------------------------------

def create_sheet_tab(batch) -> None:
    """
    Create a new tab named "{batch.name} - {level.capitalize()}" and write
    the header row. Called when a batch is created or promoted.
    Non-fatal — logs errors but never crashes the calling route.
    """
    tab_name = _worksheet_name(batch)
    try:
        spreadsheet = _get_spreadsheet()

        try:
            ws = spreadsheet.add_worksheet(title=tab_name, rows=200, cols=500)
            logger.info("Created sheet tab '%s'.", tab_name)
        except APIError as e:
            if "already exists" in str(e).lower():
                logger.info("Sheet tab '%s' already exists — skipping.", tab_name)
                return
            raise

        # Row 1: batch title
        ws.update_cell(1, 1, tab_name)

        # Row 3: column headers
        ws.update(
            f'A{HEADER_ROW}',
            [['NAMES', 'Percentage', 'Days Present', 'Days Absent', '']]
        )

        logger.info("Initialised headers for tab '%s'.", tab_name)

    except Exception as e:
        logger.error("Failed to create sheet tab '%s': %s", tab_name, e)


def append_students_to_sheet_batch(batch, unsynced_users: list) -> dict:
    """
    Batch append multiple unsynced students to their batch's Google Sheet.
    
    Only adds student names to column A — formulas in B, C, D auto-calculate.
    Called by Celery task every 5 minutes to sync students with is_synced_to_sheets=False.
    
    Optimized for minimal API quota usage:
    - Single fetch of existing names
    - Single batch write of all new names
    - Skips duplicates without API calls
    
    Args:
        batch: Batch object with current_level
        unsynced_users: List of User objects with is_synced_to_sheets=False
    
    Returns:
        {
            "appended": int (newly added students),
            "skipped": int (students already in sheet)
        }
    
    Raises:
        Exception: If worksheet not found or sheet API fails
    """
    from gspread.exceptions import APIError
    import time
    
    if not batch or not unsynced_users:
        return {"appended": 0, "skipped": 0}
    
    tab_name = _worksheet_name(batch)
    appended_count = 0
    skipped_count = 0
    
    try:
        ws = _get_worksheet(tab_name)
        logger.info("Starting batch append for '%s' with %d unsynced students.", 
                    batch.name, len(unsynced_users))
        
        # ─────────────────────────────────────────────────────────────────
        # 1. Fetch all existing names in column A (single API call)
        # ─────────────────────────────────────────────────────────────────
        try:
            all_names = ws.col_values(1)  # Get entire column A
        except APIError as e:
            logger.error("Failed to fetch existing names for '%s': %s", batch.name, e)
            raise
        
        # Build a set of lowercase names from FIRST_DATA_ROW onwards
        # (rows 1-3 are headers/titles, skip them)
        existing_names_lower = {
            name.strip().lower() 
            for name in all_names[FIRST_DATA_ROW - 1:]  # 0-indexed, so row 4 = index 3
            if name.strip()
        }
        
        logger.debug("Found %d existing students in '%s'.", len(existing_names_lower), tab_name)
        
        # ─────────────────────────────────────────────────────────────────
        # 2. Build list of students to append (filter out duplicates)
        # ─────────────────────────────────────────────────────────────────
        students_to_append = []
        
        for user in unsynced_users:
            user_name_lower = user.name.strip().lower()
            
            if user_name_lower in existing_names_lower:
                logger.debug("'%s' already exists in '%s'.", user.name, tab_name)
                skipped_count += 1
            else:
                students_to_append.append(user.name.strip())
        
        if not students_to_append:
            logger.info("No new students to append for '%s'.", batch.name)
            return {"appended": 0, "skipped": skipped_count}
        
        # ─────────────────────────────────────────────────────────────────
        # 3. Find the first empty row in column A (starting from FIRST_DATA_ROW)
        # ─────────────────────────────────────────────────────────────────
        start_row = FIRST_DATA_ROW
        for idx, name in enumerate(all_names[FIRST_DATA_ROW - 1:], start=FIRST_DATA_ROW):
            if not name.strip():
                start_row = idx
                break
        else:
            # No empty rows found, append after the last entry
            start_row = len(all_names) + 1
        
        logger.info("Will start appending at row %d in '%s'.", start_row, tab_name)
        
        # ─────────────────────────────────────────────────────────────────
        # 4. Batch append all new students (single API call)
        # ─────────────────────────────────────────────────────────────────
        try:
            # Prepare range notation for batch update
            # e.g., if appending 5 students starting at row 10: A10:A14
            end_row = start_row + len(students_to_append) - 1
            range_notation = f"A{start_row}:A{end_row}"
            
            # Convert list to 2D array (gspread expects [[val1], [val2], ...])
            values_to_write = [[name] for name in students_to_append]
            
            # Use the safer update() method instead of values_batch_update()
            # This avoids the API parameter structure issues
            ws.update(range_notation, values_to_write)
            
            appended_count = len(students_to_append)
            logger.info("Successfully appended %d new students to '%s' at rows %d-%d.",
                        appended_count, tab_name, start_row, end_row)
            
        except APIError as e:
            if e.response.status_code == 429:
                # Quota exceeded
                logger.error("Google Sheets API quota exceeded while appending to '%s'. "
                            "Retry in a few minutes.", batch.name)
                raise
            else:
                logger.error("API error while appending to '%s': %s", batch.name, e)
                raise
        
        except Exception as e:
            logger.error("Unexpected error while appending to '%s': %s", batch.name, e)
            raise
        
        # ─────────────────────────────────────────────────────────────────
        # 5. Return summary
        # ─────────────────────────────────────────────────────────────────
        result = {
            "appended": appended_count,
            "skipped": skipped_count
        }
        
        logger.info("Batch append complete for '%s': %d appended, %d already existed.",
                    batch.name, appended_count, skipped_count)
        
        return result
        
    except Exception as e:
        logger.error("Batch append failed for '%s': %s", batch.name, e)
        # Let exception bubble up — Celery's autoretry_for will handle retry
        raise


def append_student_to_sheet(user, retries: int = 3, backoff: float = 2.0) -> None:
    """
    Append a newly registered student's name to column A of their batch's
    current level tab. Called after successful registration.

    Retries up to `retries` times on transient connection errors,
    waiting backoff * attempt seconds between each try (2s, 4s, 6s).
    Non-fatal — logs errors but never crashes registration.
    """
    import time

    try:
        if not user.batch_id:
            logger.warning("User '%s' has no batch_id — skipping sheet append.", user.name)
            return

        from app.models import Batch
        batch = Batch.query.get(user.batch_id)
        if not batch:
            logger.warning("Batch %d not found for user '%s'.", user.batch_id, user.name)
            return

        tab_name = _worksheet_name(batch)

        for attempt in range(1, retries + 1):
            try:
                ws       = _get_worksheet(tab_name)
                name_col = ws.col_values(1)

                # Avoid duplicates
                name_lower = user.name.strip().lower()
                if any(cell.strip().lower() == name_lower for cell in name_col[FIRST_DATA_ROW - 1:]):
                    logger.info("'%s' already in tab '%s' — skipping.", user.name, tab_name)
                    return

                # Find next empty row from FIRST_DATA_ROW downwards
                next_row = len(name_col) + 1
                for idx, cell in enumerate(name_col[FIRST_DATA_ROW - 1:], start=FIRST_DATA_ROW):
                    if cell.strip() == "":
                        next_row = idx
                        break

                ws.update_cell(next_row, 1, user.name)
                logger.info("Appended '%s' to tab '%s' at row %d.", user.name, tab_name, next_row)
                return   # success — exit retry loop

            except APIError as e:
                if e.response.status_code == 429:
                    # Quota error — no point retrying immediately
                    logger.error("API quota exceeded while appending '%s'.", user.name)
                    return
                if attempt < retries:
                    wait = backoff * attempt
                    logger.warning(
                        "Sheets API error appending '%s' (attempt %d/%d) — retrying in %.0fs: %s",
                        user.name, attempt, retries, wait, e
                    )
                    time.sleep(wait)
                else:
                    logger.error("Sheets API error appending '%s' after %d attempts: %s", user.name, retries, e)

            except Exception as e:
                if attempt < retries:
                    wait = backoff * attempt
                    logger.warning(
                        "Failed to append '%s' (attempt %d/%d) — retrying in %.0fs: %s",
                        user.name, attempt, retries, wait, e
                    )
                    time.sleep(wait)
                else:
                    logger.error("Failed to append '%s' after %d attempts: %s", user.name, retries, e)

    except Exception as e:
        logger.error("Unexpected error in append_student_to_sheet for '%s': %s", user.name, e)


# ---------------------------------------------------------------------------
# Attendance marking
# ---------------------------------------------------------------------------


def sync_daily_attendance(
    present_names: list,
    absent_names: list,
    worksheet_name: str,
    target_date=None
) -> dict:
    """
    High-efficiency daily sync for attendance marks.
    
    1. Finds the correct date column.
    2. Maps student names to row indices.
    3. Updates attendance marks (1 = present, 0 = absent).
    
    Optimized for gspread 5.12.0 — uses safe, reliable update methods.
    """
    from datetime import date
    
    target_date = target_date or date.today()
    date_str = target_date.strftime(DATE_FORMAT)

    result = {"success": True, "updates_count": 0, "not_found": []}

    try:
        ws = _get_worksheet(worksheet_name)
        logger.info("Starting attendance sync for '%s' on %s", worksheet_name, date_str)
        
        # 1. Get the Date Column index (Discovery)
        col_idx = _get_or_create_date_col(ws, date_str)
        logger.debug("Using date column %d for '%s'", col_idx, date_str)
        
        # 2. Fetch all names (Col A) in one call
        max_rows = ws.row_count
        all_names = ws.col_values(1)  # Get entire column A
        
        # 3. Create a lookup map { "student name": row_index }
        name_map = {
            name.strip().lower(): i + 1 
            for i, name in enumerate(all_names) 
            if name.strip() and i + 1 >= FIRST_DATA_ROW
        }
        
        logger.debug("Found %d students for lookup in '%s'", len(name_map), worksheet_name)
        
        # 4. Build list of cells to update
        updates = []

        # Helper to queue updates
        def queue_update(name_list, value):
            for name in name_list:
                clean_name = name.strip().lower()
                row_idx = name_map.get(clean_name)
                
                if not row_idx or row_idx < FIRST_DATA_ROW:
                    result["not_found"].append(name)
                    logger.warning("Student '%s' not found in '%s'", name, worksheet_name)
                    continue
                
                # Convert to A1 notation: e.g., "F4" for column F, row 4
                cell_a1 = gspread.utils.rowcol_to_a1(row_idx, col_idx)
                updates.append({
                    "cell": cell_a1,
                    "value": value
                })

        # Process Presents and Absences
        queue_update(present_names, VALUE_PRESENT)
        queue_update(absent_names, VALUE_ABSENT)

        # 5. Write updates — use safe method for gspread 5.12.0
        if updates:
            try:
                # Method 1: Try batch_update (most reliable)
                _batch_update_cells(ws, updates, worksheet_name)
                result["updates_count"] = len(updates)
                logger.info("Successfully synced %d attendance records to '%s'", 
                           len(updates), worksheet_name)
                
            except Exception as batch_error:
                # Method 2: Fallback to individual cell updates
                logger.warning("Batch update failed for '%s', falling back to individual updates: %s", 
                              worksheet_name, batch_error)
                
                success_count = 0
                for update in updates:
                    try:
                        ws.update_cell(
                            *gspread.utils.a1_to_rowcol(update["cell"]),
                            update["value"]
                        )
                        success_count += 1
                    except Exception as e:
                        logger.error("Failed to update %s in '%s': %s", 
                                    update["cell"], worksheet_name, e)
                
                result["updates_count"] = success_count
                logger.info("Completed %d/%d individual updates for '%s'", 
                           success_count, len(updates), worksheet_name)
        else:
            logger.info("No new updates needed for '%s'.", worksheet_name)

        result["success"] = True
        return result

    except APIError as e:
        if e.response.status_code == 429:
            logger.error("Quota exceeded on Google Sheets for '%s'.", worksheet_name)
            return {"success": False, "message": "Quota exceeded"}
        logger.error("API error during attendance sync for '%s': %s", worksheet_name, e)
        raise e
    
    except Exception as e:
        logger.error("Unexpected error during attendance sync for '%s': %s", worksheet_name, e)
        raise


def _batch_update_cells(ws: gspread.Worksheet, updates: list, worksheet_name: str) -> None:
    """
    Safely batch update cells using gspread 5.12.0 compatible methods.
    
    Args:
        ws: gspread Worksheet object
        updates: List of {"cell": "A1", "value": value} dicts
        worksheet_name: Sheet name for logging
    """
    if not updates:
        return
    
    try:
        # Method 1: Use values_update with individual ranges
        # Group updates by range for efficiency
        ranges_and_values = [
            (update["cell"], [[update["value"]]])
            for update in updates
        ]
        
        # Use batch_update with valueRanges
        body = {
            "valueInputOption": "RAW",  # Don't interpret formulas
            "data": [
                {
                    "range": f"'{worksheet_name}'!{cell}",
                    "values": values
                }
                for cell, values in ranges_and_values
            ]
        }
        
        # Call the underlying client's batch_update to avoid parameter issues
        ws.spreadsheet.client.batch_update(
            spreadsheet_id=ws.spreadsheet.id,
            body=body
        )
        logger.debug("Batch updated %d cells in '%s' using client.batch_update", 
                    len(updates), worksheet_name)
        
    except Exception as e:
        # If batch_update fails, let the caller try fallback method
        logger.warning("Batch update failed, will fall back: %s", e)
        raise








