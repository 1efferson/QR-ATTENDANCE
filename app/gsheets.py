import gspread
from flask import current_app
from datetime import datetime

class GSheetsHandler:
    def __init__(self):
        self.client = None
        self.sheet = None

    def connect(self):
        """Authenticates with Google Sheets API."""
        if not self.client:
            try:
                # The credentials file path is loaded from config
                creds_file = current_app.config['GOOGLE_SHEETS_CREDENTIALS_FILE']
                self.client = gspread.service_account(filename=creds_file)
            except Exception as e:
                print(f"Error connecting to Google Sheets: {e}")
                return False
        return True

    def log_attendance(self, user, course_code):
        """
        Appends a row to the configured Google Sheet.
        Expected columns: [Timestamp, Name, Email, Level, Course Code]
        """
        if not self.connect():
            return False

        try:
            sheet_id = current_app.config['GOOGLE_SHEET_ID']
            # Open the sheet by ID
            workbook = self.client.open_by_key(sheet_id)
            # Select the first worksheet
            worksheet = workbook.sheet1 
            
            timestamp_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            
            row = [
                timestamp_str,
                user.name,
                user.email,
                user.level,
                course_code
            ]
            
            worksheet.append_row(row)
            return True
        except Exception as e:
            print(f"Failed to log to Google Sheets: {e}")
            return False

# Create a global instance
gsheets_handler = GSheetsHandler()