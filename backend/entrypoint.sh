#!/bin/bash
set -e

echo "[*] Initializing CTF Portal environment..."

# Wait for PostgreSQL if configured
if [ -n "$POSTGRES_HOST" ]; then
    echo "[*] Waiting for PostgreSQL database at ${POSTGRES_HOST}:${POSTGRES_PORT:-5432}..."
    python3 -c "
import time, psycopg2, os
for i in range(40):
    try:
        conn = psycopg2.connect(
            dbname=os.getenv('POSTGRES_DB', 'ctf_db'),
            user=os.getenv('POSTGRES_USER', 'ctf_admin'),
            password=os.getenv('POSTGRES_PASSWORD', ''),
            host=os.getenv('POSTGRES_HOST', 'postgres'),
            port=os.getenv('POSTGRES_PORT', '5432')
        )
        conn.close()
        print('[+] PostgreSQL is ready and accepting connections!')
        break
    except Exception:
        time.sleep(1)
else:
    print('[-] Warning: Timed out waiting for PostgreSQL, proceeding anyway...')
"
fi

# Initialize database schema
echo "[*] Initializing database schema..."
python3 -c "
import sys
sys.path.append('/app/backend')
from app import init_app
init_app()
"

echo "[+] Starting Gunicorn application server..."
cd /app/backend
exec gunicorn -w 3 -b 0.0.0.0:5000 --access-logfile - --error-logfile - app:app
