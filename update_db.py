#!/usr/bin/env python3
"""
Simple database update script for IP whitelisting
"""

import sys
from pathlib import Path

# Add project to path
project_dir = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_dir))

from app import create_app, db
from app.models import Attendance, BlockedAttempt
from sqlalchemy import text

def update_database():
    """Simple database update function"""
    app = create_app()
    
    with app.app_context():
        print("Updating database for IP whitelisting...")
        
        # Add columns to Attendance table
        with db.engine.connect() as conn:
            # Check if columns exist and add them if they don't
            try:
                conn.execute(text('ALTER TABLE attendance ADD COLUMN ip_address VARCHAR(45)'))
                print("✓ Added ip_address column")
            except Exception as e:
                print("ℹ ip_address column may already exist:", str(e)[:50])
            
            try:
                conn.execute(text('ALTER TABLE attendance ADD COLUMN user_agent VARCHAR(256)'))
                print("✓ Added user_agent column")
            except Exception as e:
                print("ℹ user_agent column may already exist:", str(e)[:50])
            
            conn.commit()
        
        # Create BlockedAttempt table
        db.create_all()
        print("✓ Created/updated BlockedAttempt table")
        
        print("\n✅ Database update complete!")

if __name__ == "__main__":
    update_database()