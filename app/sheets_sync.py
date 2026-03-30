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
    High-efficiency daily sync.
    1. Finds the correct date column.
    2. Maps student names to row indices.
    3. Batches all 1s and 0s into a single API write call.
    """
    target_date = target_date or date.today()
    date_str = target_date.strftime(DATE_FORMAT)

    result = {"success": True, "updates_count": 0, "not_found": []}

    try:
        ws = _get_worksheet(worksheet_name)
        
        # 1. Get the Date Column index (Discovery)
        col_idx = _get_or_create_date_col(ws, date_str)
        
        # 2. Fetch all names (Col A) and all current values in the target date column
        # We use a range request to get exactly what we need in one go
        # e.g., "A1:A100" and "F1:F100"
        max_rows = ws.row_count
        data_range = f"A1:A{max_rows}"
        attendance_range = f"{gspread.utils.rowcol_to_a1(1, col_idx)}:{gspread.utils.rowcol_to_a1(max_rows, col_idx)}"
        
        # Fetching multiple ranges in one call saves API quota significantly
        batch_data = ws.spreadsheet.values_batch_get([
            f"'{worksheet_name}'!{data_range}", 
            f"'{worksheet_name}'!{attendance_range}"
        ])
        
        # Parse the results
        all_names = [row[0] if row else "" for row in batch_data['valueRanges'][0].get('values', [])]
        current_vals = [row[0] if row else "" for row in batch_data['valueRanges'][1].get('values', [])]

        # 3. Create a lookup map { "student name": row_index }
        name_map = {name.strip().lower(): i + 1 for i, name in enumerate(all_names) if name.strip()}
        
        updates = []

        # Helper to queue updates
        def queue_update(name_list, value):
            for name in name_list:
                clean_name = name.strip().lower()
                row_idx = name_map.get(clean_name)
                
                if not row_idx or row_idx < FIRST_DATA_ROW:
                    result["not_found"].append(name)
                    continue
                
                # Check if cell is already filled (don't overwrite or waste API calls)
                # (current_vals is 0-indexed, row_idx is 1-indexed)
                existing_val = current_vals[row_idx - 1] if row_idx <= len(current_vals) else ""
                
                if str(existing_val).strip() == "":
                    cell_a1 = gspread.utils.rowcol_to_a1(row_idx, col_idx)
                    updates.append({
                        "range": f"'{worksheet_name}'!{cell_a1}",
                        "values": [[value]]
                    })

        # Process Presents and Absences
        queue_update(present_names, VALUE_PRESENT)
        queue_update(absent_names, VALUE_ABSENT)

        # 4. Final Atomic Write
        if updates:
            # We use the spreadsheet object's batch_update to handle range-specific updates
            ws.spreadsheet.values_batch_update({
                "valueInputOption": "USER_ENTERED",
                "data": updates
            })
            result["updates_count"] = len(updates)
            logger.info("Successfully synced %d records to '%s'", len(updates), worksheet_name)
        else:
            logger.info("No new updates needed for '%s'.", worksheet_name)

        return result

    except APIError as e:
        if e.response.status_code == 429:
            logger.error("Quota exceeded on Google Sheets.")
            return {"success": False, "message": "Quota exceeded"}
        raise e









# def mark_student_present(
#     student_name: str,
#     worksheet_name: str,
#     scan_time=None,
# ) -> dict:
#     """
#     Mark a single student Present (1) for today.
#     Called immediately after a successful QR scan.
#     """
#     scan_time = scan_time or datetime.now()
#     date_str  = scan_time.strftime(DATE_FORMAT)

#     try:
#         ws  = _get_worksheet(worksheet_name)
#         col = _get_or_create_date_col(ws, date_str)
#         row = _find_student_row(ws, student_name)

#         if row is None:
#             msg = f"Student '{student_name}' not found in tab '{worksheet_name}'."
#             logger.warning(msg)
#             return {"success": False, "message": msg}

#         existing = ws.cell(row, col).value
#         if existing is not None and str(existing).strip() != "":
#             msg = f"'{student_name}' already marked '{existing}' for {date_str}."
#             logger.info(msg)
#             return {"success": True, "message": msg}

#         ws.update_cell(row, col, VALUE_PRESENT)
#         msg = f"Marked '{student_name}' Present (1) on {date_str}."
#         logger.info(msg)
#         return {"success": True, "message": msg}

#     except APIError as e:
#         if e.response.status_code == 429:
#             logger.error("Google Sheets API quota exceeded: %s", e)
#             return {"success": False, "message": "API quota exceeded. Try again shortly."}
#         logger.error("Sheets API error: %s", e)
#         return {"success": False, "message": f"Sheets API error: {e}"}
#     except Exception as e:
#         logger.exception("Unexpected error in mark_student_present: %s", e)
#         return {"success": False, "message": str(e)}


# def mark_batch_absences(
#     absent_student_names: list,
#     worksheet_name: str,
#     target_date=None,
# ) -> dict:
#     """
#     Optimized bulk-mark students Absent (0).
#     Fetches full columns to minimize API hits and prevent 429 errors.
#     """
#     target_date = target_date or date.today()
#     date_str = datetime.combine(target_date, datetime.min.time()).strftime(DATE_FORMAT)

#     result = {
#         "success": True,
#         "marked": [],
#         "not_found": [],
#         "already_set": [],
#         "errors": [],
#     }

#     if not absent_student_names:
#         result["message"] = "No absent students to mark."
#         return result

#     try:
#         ws = _get_worksheet(worksheet_name)
#         col_idx = _get_or_create_date_col(ws, date_str)
        
#         # --- Fetch entire columns at once ---
#         # Get all names in Col A and all attendance values in the target column
#         all_names = ws.col_values(1)
#         all_attendance_values = ws.col_values(col_idx)
        
#         # Ensure the attendance list is as long as the names list to avoid index errors
#         while len(all_attendance_values) < len(all_names):
#             all_attendance_values.append("")

#         updates = []
#         # Create a lowercase map for faster student-to-row lookups
#         name_map = {name.strip().lower(): idx + 1 for idx, name in enumerate(all_names)}

#         for name in absent_student_names:
#             search_name = name.strip().lower()
#             row_idx = name_map.get(search_name)

#             if row_idx is None or row_idx < FIRST_DATA_ROW:
#                 logger.warning("Absent student '%s' not found in sheet '%s'.", name, worksheet_name)
#                 result["not_found"].append(name)
#                 continue

#             # Check value in our local list instead of calling the API again
#             # all_attendance_values is 0-indexed, row_idx is 1-indexed
#             existing_val = all_attendance_values[row_idx - 1]

#             if str(existing_val).strip() != "":
#                 # Student already has a 1 (Present) or 0 (Absent) — don't overwrite
#                 result["already_set"].append(name)
#                 continue

#             # Add to batch update list
#             cell_a1 = gspread.utils.rowcol_to_a1(row_idx, col_idx)
#             updates.append({"range": cell_a1, "values": [[VALUE_ABSENT]]})
#             result["marked"].append(name)

#         # Send all updates in a single API call
#         if updates:
#             ws.batch_update(updates)
#             logger.info("Sync success: Marked %d absences in '%s'.", len(updates), worksheet_name)

#         if result["not_found"] or result["errors"]:
#             result["success"] = False

#         return result

#     except APIError as e:
#         if e.response.status_code == 429:
#             logger.error("Google Sheets API quota exceeded. Consider increasing backoff.")
#             return {**result, "success": False, "message": "API quota exceeded."}
#         raise e # Let the scheduler's retry logic handle other API errors
#     except Exception as e:
#         logger.exception("Unexpected error in mark_batch_absences")
#         return {**result, "success": False, "message": str(e)}