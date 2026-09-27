#!/usr/bin/env python3
"""
CLI utility to create or promote an administrator account for the CTF Portal.
Usage:
    python3 create_admin.py --email admin@example.com --name "Organizer" --password "SecurePass123"
Or run interactively:
    python3 create_admin.py
"""

import os
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import argparse
import getpass
from app import app, db
from models import User, AuditLog

def create_or_update_admin(email, name, password):
    email = email.strip().lower()
    name = name.strip()
    if not email or not password or not name:
        print("[-] Error: Email, name, and password are required.")
        sys.exit(1)

    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if user:
            user.name = name
            user.role = 'admin'
            user.is_verified = True
            user.is_active = True
            user.set_password(password)
            action = "UPDATED"
        else:
            user = User(
                name=name,
                email=email,
                role='admin',
                is_verified=True,
                is_active=True
            )
            user.set_password(password)
            db.session.add(user)
            action = "CREATED"

        audit = AuditLog(
            action="ADMIN_ACCOUNT_INITIALIZED",
            details=f"CLI initialized admin account: {name} ({email})"
        )
        db.session.add(audit)
        db.session.commit()
        print(f"[+] Successfully {action} administrator account for: {name} ({email})")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Initialize or update CTF Portal Administrator")
    parser.add_argument('--email', help="Admin email address")
    parser.add_argument('--name', help="Admin full name")
    parser.add_argument('--password', help="Admin password")

    args = parser.parse_args()

    email = args.email
    name = args.name
    password = args.password

    if not email:
        email = input("Admin Email: ").strip()
    if not name:
        name = input("Admin Full Name: ").strip()
    if not password:
        password = getpass.getpass("Admin Password: ").strip()

    create_or_update_admin(email, name, password)
