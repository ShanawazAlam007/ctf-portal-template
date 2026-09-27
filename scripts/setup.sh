#!/usr/bin/env bash
# ============================================================
# CTF PORTAL TEMPLATE — SETUP & INITIALIZATION WIZARD
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "============================================================"
echo "         CTF PORTAL TEMPLATE SETUP WIZARD                   "
echo "============================================================"
echo "[*] Working directory: $ROOT_DIR"

cd "$ROOT_DIR"

# 1. Environment file setup
if [ ! -f ".env" ]; then
    echo "[*] Creating .env from .env.example..."
    cp .env.example .env
    
    # Generate secure random secret key
    SECRET_HEX=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
    sed -i "s/generate_a_secure_random_64_character_hex_string_here/$SECRET_HEX/" .env
    echo "[+] Generated random SECRET_KEY in .env"
else
    echo "[+] Existing .env file detected."
fi

# 2. Event configuration setup
if [ ! -f "config/event.json" ]; then
    echo "[*] Initializing config/event.json from config/event.example.json..."
    cp config/event.example.json config/event.json
    echo "[+] config/event.json created."
else
    echo "[+] Existing config/event.json detected."
fi

# 3. Create required runtime directories
echo "[*] Creating runtime directories..."
mkdir -p backups logs

# 4. Check deployment mode
echo ""
echo "Select deployment method:"
echo "  1) Docker Compose (Recommended for production)"
echo "  2) Local Standalone (Python virtualenv + SQLite/Postgres)"
read -rp "Enter choice [1 or 2, default: 1]: " DEPLOY_CHOICE
DEPLOY_CHOICE=${DEPLOY_CHOICE:-1}

if [ "$DEPLOY_CHOICE" = "1" ]; then
    if ! command -v docker >/dev/null 2>&1; then
        echo "[-] Error: docker is not installed or not in PATH."
        exit 1
    fi
    echo "[*] Building and starting Docker containers..."
    docker compose up -d --build
    echo "[+] Containers started!"
    echo "[*] Waiting 5 seconds for database initialization..."
    sleep 5
    echo ""
    echo "[+] Portal is accessible at http://localhost"
    echo ""
    echo "To initialize or update the Administrator account, run:"
    echo "  docker compose exec portal_web python3 /app/backend/create_admin.py"
else
    echo "[*] Setting up local Python environment..."
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    # shellcheck disable=SC1091
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r backend/requirements.txt
    
    echo "[*] Initializing database tables..."
    python3 database/init_db.py
    
    echo ""
    echo "[*] Prompting to create Administrator account:"
    python3 backend/create_admin.py
    
    echo ""
    echo "[+] Local setup complete! Start the server with:"
    echo "  source venv/bin/activate"
    echo "  cd backend && python3 app.py"
fi

echo ""
echo "============================================================"
echo "[+] SETUP COMPLETE! Your CTF Portal is ready to configure."
echo "============================================================"
