# CTF Portal Architecture & Technical Specification

## 1. System Overview

The **CTF Portal** is a production-grade, highly responsive, security-hardened competitive cybersecurity platform. It provides automated participant registration, administrative approval gating, sequential challenge unlocks, real-world target interaction dossiers, tiered hint penalization, instantaneous flag verification, and live leaderboard telemetry.

```
                          [ Internet / Competitors ]
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │    Nginx (Port 80/443)    │
                        │ - SSL/TLS Termination     │
                        │ - Static File Caching     │
                        │ - Security Headers        │
                        └─────────────┬─────────────┘
                                      │ Proxy Reverse
                                      ▼
                        ┌───────────────────────────┐
                        │  Gunicorn Application WSGI│
                        │  (3 Sync Worker Processes) │
                        └─────────────┬─────────────┘
                                      │
               ┌──────────────────────┴──────────────────────┐
               ▼                                             ▼
┌───────────────────────────────┐             ┌───────────────────────────────┐
│     Flask Application App     │             │ Shared Memory Rate Limiter    │
│  - Authentication & RBAC      │             │ (/dev/shm/ctf_ratelimit.db)   │
│  - Challenge Stage Gatekeeper │             │ - Multi-worker WAL SQLite     │
│  - Scoring & Penalty Engine   │             │ - Brute-force Interception    │
│  - Dynamic Jinja2 Templating  │             └───────────────────────────────┘
└──────────────┬────────────────┘
               │ SQLAlchemy ORM
               ▼
┌───────────────────────────────┐
│     PostgreSQL 16 Engine      │
│  - ACID Compliant Storage     │
│  - Relational Schema          │
│  - Cascade Deletions & Audits │
└───────────────────────────────┘
```

---

## 2. Key Components & Technologies

| Layer | Component | Details |
|---|---|---|
| **Reverse Proxy** | Nginx Alpine | Serves `/static/` assets directly with cache headers; injects security headers (`X-Frame-Options`, `X-XSS-Protection`, `X-Content-Type-Options`). |
| **Application Server** | Gunicorn 22.0.0 | Multi-worker Python WSGI server handling concurrent request pools. |
| **Framework** | Flask 3.0.3 | Lightweight, modular Python web framework with Blueprint/MVC structure. |
| **Database ORM** | Flask-SQLAlchemy 3.1.1 | Relational object modeling with connection pooling. |
| **Database** | PostgreSQL 16 Alpine | Primary production relational database. (SQLite supported for development). |
| **Cryptography** | Argon2-cffi 23.1.0 | State-of-the-art password hashing with salt and memory hardness. |
| **Frontend** | HTML5 / Vanilla JS / CSS3 | High-contrast dark cyber theme with zero heavy frontend framework dependencies. |

---

## 3. Database Schema

The relational database uses 7 normalized tables:

1. **`users`**:
   - `id` (PK, Serial)
   - `name` (VARCHAR 120): Legal / operative name
   - `email` (VARCHAR 150, Unique, Indexed)
   - `password_hash` (VARCHAR 255): Argon2 hash
   - `is_verified` (BOOLEAN): Approval / verification flag
   - `verification_token` (VARCHAR 128, Indexed)
   - `token_expires_at` (TIMESTAMP)
   - `role` (VARCHAR 20): `'player'` or `'admin'`
   - `is_active` (BOOLEAN)
   - `created_at` (TIMESTAMP)
   - `last_active` (TIMESTAMP)

2. **`challenges`**:
   - `id` (PK, Serial)
   - `name` (VARCHAR 150)
   - `slug` (VARCHAR 150, Unique, Indexed)
   - `category` (VARCHAR 80)
   - `difficulty` (VARCHAR 50)
   - `points` (INTEGER)
   - `target_info` (VARCHAR 200): Connection string / URL / host
   - `target_type` (VARCHAR 50): `'HTTP'`, `'SSH'`, `'RDP'`, etc.
   - `short_desc` (TEXT)
   - `story_markdown` (TEXT): Full challenge brief & dossier
   - `is_active` (BOOLEAN)
   - `display_order` (INTEGER): Stage number used for sequential gating
   - `created_at` (TIMESTAMP)

3. **`flags`**:
   - `id` (PK, Serial)
   - `challenge_id` (FK $\rightarrow$ `challenges.id`, ON DELETE CASCADE)
   - `flag_value` (VARCHAR 200)
   - `points` (INTEGER)
   - `title` (VARCHAR 120)
   - `created_at` (TIMESTAMP)

4. **`hints`**:
   - `id` (PK, Serial)
   - `challenge_id` (FK $\rightarrow$ `challenges.id`, ON DELETE CASCADE)
   - `hint_number` (INTEGER): 1, 2, 3
   - `title` (VARCHAR 120)
   - `content` (TEXT): Clue content
   - `penalty` (INTEGER): Point deduction cost
   - `created_at` (TIMESTAMP)

5. **`user_hint_unlocks`**:
   - `id` (PK, Serial)
   - `user_id` (FK $\rightarrow$ `users.id`, ON DELETE CASCADE)
   - `challenge_id` (FK $\rightarrow$ `challenges.id`, ON DELETE CASCADE)
   - `hint_id` (FK $\rightarrow$ `hints.id`, ON DELETE CASCADE)
   - `penalty_applied` (INTEGER)
   - `unlocked_at` (TIMESTAMP)

6. **`submissions`**:
   - `id` (PK, Serial)
   - `user_id` (FK $\rightarrow$ `users.id`, ON DELETE CASCADE)
   - `challenge_id` (FK $\rightarrow$ `challenges.id`, ON DELETE CASCADE)
   - `flag_id` (FK $\rightarrow$ `flags.id`, ON DELETE SET NULL)
   - `submitted_flag` (VARCHAR 255)
   - `is_correct` (BOOLEAN)
   - `points_awarded` (INTEGER)
   - `ip_address` (VARCHAR 45)
   - `submitted_at` (TIMESTAMP)

7. **`audit_logs`**:
   - `id` (PK, Serial)
   - `user_id` (FK $\rightarrow$ `users.id`, ON DELETE SET NULL)
   - `action` (VARCHAR 60)
   - `details` (TEXT)
   - `ip_address` (VARCHAR 45)
   - `timestamp` (TIMESTAMP)

---

## 4. Security & Competition Mechanics

### A. Shared-Memory Multi-Worker Rate Limiting
To prevent multi-threaded brute-forcing or login stuffing across multiple Gunicorn workers, the rate limiter stores attempt timestamps in `/dev/shm/ctf_ratelimit.db` (a memory-backed SQLite database operating in WAL mode). When a client IP exceeds the configured threshold ($>5$ login requests in 30 seconds), an HTTP 429 response is issued with a security interception banner.

### B. Stage Sequential Locking
When `SEQUENTIAL_STAGES=true`:
- Stage 1 (`display_order <= 1`) is unlocked for all verified competitors.
- Stage $N$ ($N > 1$) remains strictly locked until the competitor has captured all flags belonging to Stage $N - 1$.
- Locked cards completely conceal target connection parameters (`target_info`) and progress counters (`solved / total flags`) until unlocked.

### C. Earliest-Solve Leaderboard Tie-Breaking
The leaderboard sort key is computed as:
$$\text{Key}(u) = (-\text{user.score}, \; \text{user.last\_solve\_time} \lor \infty, \; \text{user.created\_at})$$
Competitors who reach a score earlier are ranked above later solvers. Only officially approved participants (`is_verified=True`) are included in public standings.

### D. Tiered Hint Penalty with Balance Enforcement
- The first clue for each challenge is unlocked for **0 points penalty**.
- Subsequent clues deduct configured penalty points (default 15 pts).
- Competitors with 0 points or fewer points than the clue cost are strictly blocked from unlocking hints until they have earned enough points.
