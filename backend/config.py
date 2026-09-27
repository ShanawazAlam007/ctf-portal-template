import os
import json
import secrets
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

def load_event_config():
    """Load configurable event parameters from config/event.json (fallback to event.example.json)."""
    event_file = BASE_DIR / "config" / "event.json"
    example_file = BASE_DIR / "config" / "event.example.json"

    target_file = event_file if event_file.exists() else example_file
    if target_file.exists():
        try:
            with open(target_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    return {
        "eventName": "CYBER ARENA CTF",
        "eventSubtitle": "Think. Enumerate. Exploit. Capture.",
        "organization": "Security Operations & Research Lab",
        "contactEmail": "admin@example.com",
        "registrationEnabled": True,
        "leaderboardEnabled": True,
        "allowedEmailDomains": [],
        "requireNumericRoll": False,
        "requireAdminApproval": True,
        "sequentialStages": True,
        "rateLimitWarning": "Automated security interception: High-frequency requests detected. Your IP has been temporarily rate-limited."
    }

EVENT_CONFIG = load_event_config()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', secrets.token_hex(32))
    
    # Database
    DB_USER = os.getenv('POSTGRES_USER', 'ctf_admin')
    DB_PASSWORD = os.getenv('POSTGRES_PASSWORD', '')
    DB_HOST = os.getenv('POSTGRES_HOST', 'localhost')
    DB_PORT = os.getenv('POSTGRES_PORT', '5432')
    DB_NAME = os.getenv('POSTGRES_DB', 'ctf_db')
    
    # Auto-detect SQLite or PostgreSQL
    default_db_url = f'postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}' if DB_PASSWORD else f'sqlite:///{BASE_DIR}/ctf_dev.db'
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', default_db_url)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session & Security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.getenv('FORCE_HTTPS', 'false').lower() == 'true'
    PERMANENT_SESSION_LIFETIME = 86400  # 24 hours

    # Portal Base URL
    PORTAL_BASE_URL = os.getenv('PORTAL_BASE_URL', 'http://localhost')

    # Allowed Domains & Registration Rules
    # Priority: Environment variable -> event.json -> open (empty list)
    env_domains = os.getenv('ALLOWED_EMAIL_DOMAINS')
    if env_domains is not None:
        ALLOWED_EMAIL_DOMAINS = [d.strip().lower() for d in env_domains.split(',') if d.strip()]
    else:
        ALLOWED_EMAIL_DOMAINS = [d.strip().lower() for d in EVENT_CONFIG.get('allowedEmailDomains', []) if d.strip()]

    REQUIRE_NUMERIC_ROLL = os.getenv('REQUIRE_NUMERIC_ROLL', str(EVENT_CONFIG.get('requireNumericRoll', False))).lower() == 'true'
    REQUIRE_ADMIN_APPROVAL = os.getenv('REQUIRE_ADMIN_APPROVAL', str(EVENT_CONFIG.get('requireAdminApproval', True))).lower() == 'true'
    SEQUENTIAL_STAGES = os.getenv('SEQUENTIAL_STAGES', str(EVENT_CONFIG.get('sequentialStages', True))).lower() == 'true'

    # Master Administrator Init (Optional)
    ADMIN_NAME = os.getenv('ADMIN_NAME', 'CTF Director')
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@example.com')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')

    # Rate Limiting
    RATE_LIMIT_LOGIN_MAX = int(os.getenv('RATE_LIMIT_LOGIN_MAX', '5'))
    RATE_LIMIT_LOGIN_WINDOW = int(os.getenv('RATE_LIMIT_LOGIN_WINDOW', '30'))

    # Transactional Email (SMTP)
    SMTP_HOST = os.getenv('SMTP_HOST', '')
    SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USERNAME = os.getenv('SMTP_USERNAME', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
    EMAIL_FROM = os.getenv('EMAIL_FROM', 'noreply@example.com')
    SMTP_USE_TLS = os.getenv('SMTP_USE_TLS', 'true').lower() == 'true'

    # Event Metadata
    EVENT = EVENT_CONFIG
