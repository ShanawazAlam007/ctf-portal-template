#!/usr/bin/env python3
"""
Initialize database schema for the CTF Portal.
Creates all tables without adding any demo or competition challenges.
"""

import sys
import os

# Ensure backend directory is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend')))

from app import app, db
from models import User, Challenge, Flag, Hint, Submission, UserHintUnlock, AuditLog
from config import Config

def init_database():
    with app.app_context():
        print("[*] Creating database tables...")
        db.create_all()
        print("[+] Database tables successfully created!")

        # Check if organizer credentials are provided in environment
        admin_email = getattr(Config, 'ADMIN_EMAIL', None)
        admin_pass = getattr(Config, 'ADMIN_PASSWORD', None)

        if admin_email and admin_pass:
            admin = User.query.filter_by(email=admin_email).first()
            if not admin:
                print(f"[*] Initializing master administrator ({admin_email})...")
                admin = User(
                    name=getattr(Config, 'ADMIN_NAME', 'Administrator'),
                    email=admin_email,
                    role='admin',
                    is_verified=True,
                    is_active=True
                )
                admin.set_password(admin_pass)
                db.session.add(admin)
                db.session.commit()
                print(f"[+] Master administrator ({admin_email}) created.")
        else:
            print("[*] No admin credentials in environment. Run 'python3 backend/create_admin.py' to create an admin.")

if __name__ == '__main__':
    init_database()
