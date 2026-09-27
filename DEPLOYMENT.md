# CTF Portal Production Deployment Guide

This guide provides step-by-step instructions for deploying the CTF Portal in a secure, containerized production environment (e.g. AWS EC2, Azure VM, DigitalOcean Droplet, or on-premises server).

---

## 1. System Requirements

- **Operating System:** Ubuntu 22.04 LTS or 24.04 LTS (x86_64)
- **Resources:** Minimum 2 vCPU, 4GB RAM, 20GB SSD storage
- **Software:** Docker Engine 24.0+, Docker Compose v2+
- **Network Ports:** Port 80 (HTTP), Port 443 (HTTPS), Port 22 (SSH)

---

## 2. Quick Deployment (Docker Compose)

### Step 1: Copy Template to Deployment Directory
```bash
cp -r ~/CTF-Portal-Template /opt/my-ctf-event
cd /opt/my-ctf-event
```

### Step 2: Configure Environment Variables
```bash
cp .env.example .env
```
Edit `.env` using your preferred editor (`nano .env`):
- Set a strong `SECRET_KEY` (generate one with `openssl rand -hex 32`).
- Set a strong `POSTGRES_PASSWORD`.
- Set `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
- Configure `ALLOWED_EMAIL_DOMAINS` if you wish to restrict registration to university/corporate email domains (e.g. `university.edu,alumni.university.edu`). Leave blank to permit all domains.
- Set `REQUIRE_ADMIN_APPROVAL=true` if you want organizers to manually approve registrants before they can compete.

### Step 3: Configure Event Branding
```bash
cp config/event.example.json config/event.json
```
Edit `config/event.json` with your competition name, subtitle, and organization.

### Step 4: Build and Launch Services
```bash
docker compose up -d --build
```
Verify all 3 containers are healthy and running:
```bash
docker compose ps
```
You should see:
- `ctf_postgres` (Up, healthy)
- `ctf_web` (Up)
- `ctf_nginx` (Up, listening on 0.0.0.0:80)

### Step 5: Initialize the Master Administrator
If you did not specify `ADMIN_PASSWORD` in `.env`, run the interactive admin creation CLI:
```bash
docker compose exec portal_web python3 /app/backend/create_admin.py
```

### Step 6: Log In & Access Admin Console
Open your browser and navigate to:
```
http://<YOUR_SERVER_IP_OR_DOMAIN>/login
```
Log in using your administrator credentials. You will be redirected to the **Administrative Console** (`/admin`).

---

## 3. Configuring SSL / TLS (HTTPS) with Let's Encrypt

To secure logins and flag submissions in production with HTTPS:

1. Install Certbot on the host:
```bash
sudo apt update && sudo apt install -y certbot
```

2. Temporarily stop Nginx:
```bash
docker compose stop nginx
```

3. Obtain certificate:
```bash
sudo certbot certonly --standalone -d ctf.yourdomain.com
```

4. Mount certificate volumes into `docker-compose.yml` under `nginx`:
```yaml
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
      - ./frontend/static:/app/frontend/static:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    ports:
      - "80:80"
      - "443:443"
```

5. Update `nginx/default.conf` to redirect port 80 to 443 and add SSL parameters.
6. Restart Nginx:
```bash
docker compose up -d nginx
```

---

## 4. Automated Daily Backups

Add a cron job on the host server to create daily timestamped backups of the PostgreSQL database:

```bash
sudo crontab -e
```
Add the following line (runs daily at 02:00 AM):
```cron
0 2 * * * /opt/my-ctf-event/scripts/backup.sh >> /var/log/ctf-backup.log 2>&1
```

---

## 5. Tournament Season Operations

### Adding Challenges
1. Access `/admin` in your browser.
2. Under **Challenge Missions Management**, click **[+ Create New Challenge]**.
3. Fill in the challenge title, slug, points, category, difficulty, service connection info, description, and Markdown story brief.
4. Add the initial flag and save.
5. Add any additional hints/clues through the **[Flags & Hints]** manager.

### Exporting Final Results
In the top right of the Admin Console, click:
- **Export Leaderboard**: Downloads clean CSV with Rank, Full Name, Email, Score, Flags Captured, and Last Solve Time.
- **Export Submissions**: Downloads full telemetry logs of all flag attempts.
- **Export Users**: Downloads roster of all enrolled participants.

### Resetting Between Rounds / Tournaments
To zero the leaderboard and wipe player submissions while preserving all challenges and administrator accounts:
```bash
docker compose exec portal_web python3 /app/backend/reset_competition.py --scores-only
```
Or to purge player accounts as well:
```bash
docker compose exec portal_web python3 /app/backend/reset_competition.py --all-players
```
