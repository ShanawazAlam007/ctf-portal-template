import os
import io
import csv
import time
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, flash, 
    session, jsonify, make_response, abort
)
import markdown

import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from config import Config
from models import db, User, Challenge, Flag, Hint, UserHintUnlock, Submission, AuditLog
from email_service import send_verification_email

app = Flask(
    __name__,
    template_folder=os.path.join(current_dir, '../frontend/templates'),
    static_folder=os.path.join(current_dir, '../frontend/static')
)
app.config.from_object(Config)

db.init_app(app)

# ==========================================
# TIMEZONE & SHARED-MEMORY RATE LIMITING
# ==========================================

# Timezone: Indian Standard Time (IST — UTC+05:30)
IST_OFFSET = timedelta(hours=5, minutes=30)

def to_ist(dt):
    if not dt:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone(IST_OFFSET))
    return dt + IST_OFFSET

# Shared memory rate limiter for multi-worker Gunicorn deployments
SHM_DB = "/dev/shm/ctf_ratelimit.db"

def init_ratelimit_db():
    try:
        with sqlite3.connect(SHM_DB, timeout=5) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS rate_limits (key TEXT, timestamp REAL)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rl_key_time ON rate_limits(key, timestamp)")
    except Exception:
        pass

init_ratelimit_db()

def rate_limited(limit_key: str, max_requests: int = 5, window_seconds: int = 30) -> bool:
    """Returns True if request exceeds rate limit, False otherwise."""
    now = time.time()
    cutoff = now - window_seconds
    try:
        with sqlite3.connect(SHM_DB, timeout=5) as conn:
            conn.execute("DELETE FROM rate_limits WHERE key = ? AND timestamp < ?", (limit_key, cutoff))
            cur = conn.execute("SELECT COUNT(*) FROM rate_limits WHERE key = ? AND timestamp >= ?", (limit_key, cutoff))
            count = cur.fetchone()[0]
            if count >= max_requests:
                return True
            conn.execute("INSERT INTO rate_limits VALUES (?, ?)", (limit_key, now))
            conn.commit()
            return False
    except Exception:
        return False

def clear_rate_limit(limit_key: str):
    try:
        with sqlite3.connect(SHM_DB, timeout=5) as conn:
            conn.execute("DELETE FROM rate_limits WHERE key = ?", (limit_key,))
            conn.commit()
    except Exception:
        pass

def get_client_ip() -> str:
    """Extract real client IP address considering proxy headers."""
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.headers.get('X-Real-IP') or request.remote_addr or '127.0.0.1'

# ==========================================
# TEMPLATE FILTERS & CONTEXT PROCESSORS
# ==========================================

@app.template_filter('md')
def render_markdown(text):
    if not text:
        return ""
    return markdown.markdown(text, extensions=['fenced_code', 'tables', 'nl2br'])

@app.template_filter('ist')
def format_ist(dt, fmt='%Y-%m-%d %I:%M:%S %p'):
    if not dt:
        return "-"
    ist_dt = to_ist(dt)
    return ist_dt.strftime(fmt)

@app.context_processor
def inject_globals():
    user = None
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if not user or not user.is_active:
            session.clear()
            user = None
    return dict(
        current_user=user,
        event=Config.EVENT,
        now=to_ist(datetime.utcnow())
    )

# ==========================================
# ROUTE GUARDS & DECORATORS
# ==========================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login', next=request.url))
        user = User.query.get(session['user_id'])
        if not user or not user.is_active:
            session.clear()
            flash("Session expired or account deactivated. Please log in again.", "danger")
            return redirect(url_for('login'))
        if not user.is_verified:
            flash("Your registration is pending administrator approval. Please wait for authorization.", "warning")
            return redirect(url_for('verify_pending', email=user.email))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            abort(404)
        user = User.query.get(session['user_id'])
        if not user or user.role != 'admin' or not user.is_active:
            abort(404)
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# STAGE LOCKING & LEADERBOARD HELPERS
# ==========================================

def is_stage_unlocked_for_user(user, challenge):
    """
    Stage lock logic:
    - If Config.SEQUENTIAL_STAGES is False, all active challenges are unlocked.
    - Admins can access all stages.
    - Stage 1 (display_order <= 1) is unlocked for everyone.
    - For Stage N (N > 1), the previous stage (display_order = N - 1) must have all its flags solved.
    """
    if not Config.SEQUENTIAL_STAGES:
        return True
    if not user or user.role == 'admin':
        return True
    if challenge.display_order <= 1:
        return True
    prev_challenge = Challenge.query.filter_by(display_order=challenge.display_order - 1, is_active=True).first()
    if not prev_challenge:
        return True
    prev_flag_ids = [f.id for f in prev_challenge.flags]
    if not prev_flag_ids:
        return True
    correct_subs = Submission.query.filter_by(user_id=user.id, challenge_id=prev_challenge.id, is_correct=True).all()
    prev_solved = sum(1 for s in correct_subs if s.flag_id in prev_flag_ids)
    return prev_solved >= len(prev_flag_ids)

def get_leaderboard_sort_key(u):
    """
    Sort key for leaderboard ranking:
    1. Score descending (-u.score)
    2. Earliest solve timestamp (u.last_solve_time)
    3. User registration timestamp (u.created_at)
    """
    last_t = u.last_solve_time if u.last_solve_time else datetime.max
    return (-u.score, last_t, u.created_at)

# ==========================================
# PUBLIC & GENERAL ROUTES
# ==========================================

@app.route('/')
def index():
    challenges = Challenge.query.filter_by(is_active=True).order_by(Challenge.display_order).all()
    
    # Leaderboard preview: Top 5 approved players
    users = User.query.filter_by(role='player', is_active=True, is_verified=True).all()
    ranked_users = sorted(users, key=get_leaderboard_sort_key)[:5]
    leaderboard_preview = []
    for idx, u in enumerate(ranked_users, 1):
        leaderboard_preview.append({
            'rank': idx,
            'display_name': u.display_name,
            'score': u.score,
            'flags_count': u.flags_captured_count
        })

    # Stats for hero
    total_flags_count = sum(len(c.flags) for c in challenges)
    total_points = sum(c.points for c in challenges)

    return render_template(
        'index.html',
        challenges=challenges,
        leaderboard_preview=leaderboard_preview,
        total_flags_count=total_flags_count,
        total_points=total_points
    )

@app.route('/rules')
def rules():
    return render_template('rules.html')

# ==========================================
# AUTHENTICATION & REGISTRATION
# ==========================================

@app.route('/register', methods=['GET', 'POST'])
def register():
    if not Config.EVENT.get('registrationEnabled', True):
        flash("Registration is currently closed for this event.", "info")
        return redirect(url_for('login'))

    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        role = request.form.get('role', 'player').strip().lower()
        if role not in ['player', 'admin']:
            role = 'player'

        if not name or not email or not password:
            flash("All fields are required.", "danger")
            return render_template('register.html', name=name, email=email, role=role)

        # Domain restriction validation
        allowed_domains = Config.ALLOWED_EMAIL_DOMAINS
        if allowed_domains:
            email_domain = email.split('@')[-1] if '@' in email else ''
            if email_domain not in allowed_domains:
                domains_str = ", ".join(f"@{d}" for d in allowed_domains)
                flash(f"Access restricted. Registration is limited to authorized domains: {domains_str}.", "danger")
                return render_template('register.html', name=name, email=email, role=role)

        # Numeric username roll check (optional)
        if Config.REQUIRE_NUMERIC_ROLL:
            prefix = email.split('@')[0]
            if not prefix.isdigit():
                flash("Invalid format. The username before the @ symbol must be numeric (student roll number).", "danger")
                return render_template('register.html', name=name, email=email, role=role)

        if len(password) < 8:
            flash("Password must be at least 8 characters in length.", "danger")
            return render_template('register.html', name=name, email=email, role=role)

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template('register.html', name=name, email=email, role=role)

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            if not existing_user.is_verified:
                flash("An account with this email exists but is pending approval/verification.", "warning")
                return redirect(url_for('verify_pending', email=email))
            flash("An account with this email address is already registered. Please log in.", "danger")
            return redirect(url_for('login'))

        # Create user
        is_verified_by_default = not Config.REQUIRE_ADMIN_APPROVAL
        new_user = User(
            name=name,
            email=email,
            is_verified=is_verified_by_default,
            role=role
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        audit = AuditLog(
            user_id=new_user.id,
            action="USER_REGISTERED",
            details=f"User registered: {name} ({email}) as {role}",
            ip_address=get_client_ip()
        )
        db.session.add(audit)
        db.session.commit()

        if Config.REQUIRE_ADMIN_APPROVAL:
            flash("Registration received! Your account is pending organizer approval.", "info")
            return redirect(url_for('verify_pending', email=email))
        else:
            flash("Registration successful! You may now log in to the portal.", "success")
            return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/verify-pending')
def verify_pending():
    email = request.args.get('email', '')
    user = User.query.filter_by(email=email).first() if email else None
    return render_template('verify_pending.html', email=email, user=user)

@app.route('/verify/<token>')
def verify_token(token):
    user = User.query.filter_by(verification_token=token).first()
    if not user:
        flash("Invalid or expired verification link.", "danger")
        return redirect(url_for('login'))

    if user.token_expires_at and user.token_expires_at < datetime.utcnow():
        flash("This verification link has expired. Please contact an organizer.", "warning")
        return redirect(url_for('login'))

    user.is_verified = True
    user.verification_token = None
    user.token_expires_at = None
    db.session.commit()

    audit = AuditLog(
        user_id=user.id,
        action="EMAIL_VERIFIED",
        details=f"User {user.email} verified account via link.",
        ip_address=get_client_ip()
    )
    db.session.add(audit)
    db.session.commit()

    return render_template('verify_success.html', user=user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    client_ip = get_client_ip()

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        # Anti-Brute-Force Rate Limiting
        bf_key = f"bf_login_{client_ip}"
        if rate_limited(bf_key, max_requests=Config.RATE_LIMIT_LOGIN_MAX, window_seconds=Config.RATE_LIMIT_LOGIN_WINDOW):
            audit_key = f"bf_audit_{client_ip}"
            if not rate_limited(audit_key, max_requests=1, window_seconds=60):
                audit = AuditLog(
                    user_id=None,
                    action="LOGIN_BRUTE_FORCE_BLOCKED",
                    details=f"Login brute-force detected from IP {client_ip} attempting target '{email or 'anonymous'}'.",
                    ip_address=client_ip
                )
                db.session.add(audit)
                db.session.commit()

            return render_template(
                'login.html',
                email=email,
                brute_force_warning=True,
                client_ip=client_ip,
                attempted_target=email or 'anonymous'
            ), 429

        if not email or not password:
            flash("Please enter both email and password.", "danger")
            return render_template('login.html', email=email)

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Invalid credentials. Please verify your email and password.", "danger")
            return render_template('login.html', email=email)

        if not user.is_active:
            flash("Your account has been deactivated. Please contact CTF organizers.", "danger")
            return render_template('login.html', email=email)

        if not user.is_verified:
            flash("Your registration is pending administrator approval. Please wait for an administrator to approve your account.", "warning")
            return redirect(url_for('verify_pending', email=user.email))

        clear_rate_limit(bf_key)

        session.clear()
        session['user_id'] = user.id
        session['role'] = user.role
        user.last_active = datetime.utcnow()
        db.session.commit()

        audit = AuditLog(
            user_id=user.id,
            action="USER_LOGIN",
            details=f"User {user.email} successfully logged in.",
            ip_address=client_ip
        )
        db.session.add(audit)
        db.session.commit()

        flash(f"Welcome back, {user.display_name}!", "success")
        if user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('dashboard'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    uid = session.get('user_id')
    if uid:
        audit = AuditLog(
            user_id=uid,
            action="USER_LOGOUT",
            details="User logged out.",
            ip_address=get_client_ip()
        )
        db.session.add(audit)
        db.session.commit()
    session.clear()
    flash("You have been securely logged out.", "info")
    return redirect(url_for('login'))

# ==========================================
# COMPETITOR DASHBOARD & CHALLENGES
# ==========================================

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    challenges = Challenge.query.filter_by(is_active=True).order_by(Challenge.display_order).all()
    
    correct_submissions = Submission.query.filter_by(user_id=user.id, is_correct=True).all()
    solved_flag_ids = set(s.flag_id for s in correct_submissions if s.flag_id)

    challenge_status = []
    total_flags_count = 0
    for c in challenges:
        c_flags = [f.id for f in c.flags]
        solved_count = sum(1 for fid in c_flags if fid in solved_flag_ids)
        total_flags = len(c_flags)
        total_flags_count += total_flags
        is_completed = (solved_count == total_flags and total_flags > 0)
        is_unlocked = is_stage_unlocked_for_user(user, c)
        required_stage = c.display_order - 1 if c.display_order > 1 else None
        challenge_status.append({
            'challenge': c,
            'solved_count': solved_count,
            'total_flags': total_flags,
            'is_completed': is_completed,
            'is_unlocked': is_unlocked,
            'required_stage': required_stage
        })

    recent_subs = Submission.query.filter_by(user_id=user.id).order_by(Submission.submitted_at.desc()).limit(10).all()

    # User's rank among approved players
    users = User.query.filter_by(role='player', is_active=True, is_verified=True).all()
    ranked = sorted(users, key=get_leaderboard_sort_key)
    user_rank = next((idx for idx, u in enumerate(ranked, 1) if u.id == user.id), "-")

    return render_template(
        'dashboard.html',
        user=user,
        challenge_status=challenge_status,
        recent_subs=recent_subs,
        user_rank=user_rank,
        total_flags_count=total_flags_count
    )

@app.route('/challenges')
@login_required
def challenges():
    user = User.query.get(session['user_id'])
    all_challenges = Challenge.query.filter_by(is_active=True).order_by(Challenge.display_order).all()

    correct_submissions = Submission.query.filter_by(user_id=user.id, is_correct=True).all()
    solved_flag_ids = set(s.flag_id for s in correct_submissions if s.flag_id)

    challenges_data = []
    for c in all_challenges:
        c_flags = [f.id for f in c.flags]
        solved_count = sum(1 for fid in c_flags if fid in solved_flag_ids)
        total_flags = len(c_flags)
        is_completed = (solved_count == total_flags and total_flags > 0)
        is_unlocked = is_stage_unlocked_for_user(user, c)
        required_stage = c.display_order - 1 if c.display_order > 1 else None

        challenges_data.append({
            'item': c,
            'solved_count': solved_count,
            'total_flags': total_flags,
            'is_completed': is_completed,
            'is_unlocked': is_unlocked,
            'required_stage': required_stage
        })

    return render_template('challenges.html', challenges_data=challenges_data)

@app.route('/challenge/<slug>', methods=['GET', 'POST'])
@login_required
def challenge_detail(slug):
    user = User.query.get(session['user_id'])
    challenge = Challenge.query.filter_by(slug=slug, is_active=True).first_or_404()

    # Verify stage unlock
    if not is_stage_unlocked_for_user(user, challenge):
        flash(f"Stage locked. You must solve all flags in Stage {challenge.display_order - 1} before accessing this mission.", "warning")
        return redirect(url_for('challenges'))

    # Flags & solves
    c_flags = challenge.flags
    user_correct_subs = Submission.query.filter_by(user_id=user.id, challenge_id=challenge.id, is_correct=True).all()
    solved_flag_ids = set(s.flag_id for s in user_correct_subs if s.flag_id)

    flags_data = []
    for f in c_flags:
        flags_data.append({
            'id': f.id,
            'title': f.title,
            'points': f.points,
            'is_solved': f.id in solved_flag_ids
        })

    # Flag Submission Handling
    if request.method == 'POST':
        submitted_flag = request.form.get('flag', '').strip()
        client_ip = get_client_ip()

        # Rate limiting on submissions (2s window)
        sub_key = f"sub_rate_{user.id}"
        if rate_limited(sub_key, max_requests=1, window_seconds=2):
            flash("Submission rate limit active. Please pause 2 seconds between attempts.", "warning")
            return redirect(url_for('challenge_detail', slug=slug))

        if not submitted_flag:
            flash("Please enter a flag before submitting.", "danger")
            return redirect(url_for('challenge_detail', slug=slug))

        # Check against challenge flags
        matching_flag = None
        for f in c_flags:
            if f.flag_value.strip() == submitted_flag:
                matching_flag = f
                break

        if matching_flag:
            if matching_flag.id in solved_flag_ids:
                flash("Flag already verified! You have already claimed points for this objective.", "info")
                return redirect(url_for('challenge_detail', slug=slug))

            submission = Submission(
                user_id=user.id,
                challenge_id=challenge.id,
                flag_id=matching_flag.id,
                submitted_flag=submitted_flag,
                is_correct=True,
                points_awarded=matching_flag.points,
                ip_address=client_ip
            )
            db.session.add(submission)

            audit = AuditLog(
                user_id=user.id,
                action="FLAG_CAPTURED",
                details=f"User {user.email} captured flag '{matching_flag.title}' (+{matching_flag.points} pts) for challenge '{challenge.name}'",
                ip_address=client_ip
            )
            db.session.add(audit)
            db.session.commit()

            flash(f"CRACKED! Correct flag verified! +{matching_flag.points} Points credited to your score.", "success")
            return redirect(url_for('challenge_detail', slug=slug))
        else:
            submission = Submission(
                user_id=user.id,
                challenge_id=challenge.id,
                flag_id=None,
                submitted_flag=submitted_flag,
                is_correct=False,
                points_awarded=0,
                ip_address=client_ip
            )
            db.session.add(submission)
            db.session.commit()

            flash("Incorrect flag. Analyze the evidence carefully and try again.", "danger")
            return redirect(url_for('challenge_detail', slug=slug))

    # User unlock status for hints
    user_unlocks = UserHintUnlock.query.filter_by(user_id=user.id, challenge_id=challenge.id).all()
    unlocked_hint_ids = set(u.hint_id for u in user_unlocks)

    hints_info = []
    for h in challenge.hints:
        is_unlocked = h.id in unlocked_hint_ids
        hints_info.append({
            'id': h.id,
            'number': h.hint_number,
            'title': h.title,
            'content': h.content if is_unlocked else None,
            'penalty': h.penalty,
            'is_unlocked': is_unlocked
        })

    user_history = Submission.query.filter_by(user_id=user.id, challenge_id=challenge.id).order_by(Submission.submitted_at.desc()).limit(15).all()

    return render_template(
        'story.html',
        challenge=challenge,
        flags_data=flags_data,
        hints_info=hints_info,
        user_history=user_history
    )

@app.route('/challenge/<slug>/unlock-hint/<int:hint_id>', methods=['POST'])
@login_required
def unlock_hint(slug, hint_id):
    user = User.query.get(session['user_id'])
    challenge = Challenge.query.filter_by(slug=slug, is_active=True).first_or_404()
    hint = Hint.query.filter_by(id=hint_id, challenge_id=challenge.id).first_or_404()

    already_unlocked = UserHintUnlock.query.filter_by(user_id=user.id, hint_id=hint.id).first()
    if already_unlocked:
        flash("Clue already unlocked.", "info")
        return redirect(url_for('challenge_detail', slug=slug))

    prior_unlocks_count = UserHintUnlock.query.filter_by(user_id=user.id, challenge_id=challenge.id).count()
    penalty_cost = 0 if prior_unlocks_count == 0 else (hint.penalty if hint.penalty > 0 else 15)

    if penalty_cost > 0 and user.score < penalty_cost:
        flash(f"Insufficient score balance. You need at least {penalty_cost} points to unlock this clue.", "danger")
        return redirect(url_for('challenge_detail', slug=slug))

    unlock = UserHintUnlock(
        user_id=user.id,
        challenge_id=challenge.id,
        hint_id=hint.id,
        penalty_applied=penalty_cost
    )
    db.session.add(unlock)

    audit = AuditLog(
        user_id=user.id,
        action="HINT_UNLOCKED",
        details=f"User {user.email} unlocked Hint #{hint.hint_number} for '{challenge.name}' (penalty: -{penalty_cost} pts)",
        ip_address=get_client_ip()
    )
    db.session.add(audit)
    db.session.commit()

    if penalty_cost > 0:
        flash(f"Clue unlocked! {penalty_cost} points deducted from tournament score.", "warning")
    else:
        flash("First clue unlocked for free (0 pts penalty).", "success")

    return redirect(url_for('challenge_detail', slug=slug))

# ==========================================
# LEADERBOARD & USER PROFILE
# ==========================================

@app.route('/leaderboard')
@login_required
def leaderboard():
    users = User.query.filter_by(role='player', is_active=True, is_verified=True).all()
    sorted_users = sorted(users, key=get_leaderboard_sort_key)

    total_flags_count = sum(len(c.flags) for c in Challenge.query.filter_by(is_active=True).all())

    leaderboard_data = []
    for rank, u in enumerate(sorted_users, 1):
        leaderboard_data.append({
            'rank': rank,
            'id': u.id,
            'display_name': u.display_name,
            'score': u.score,
            'flags_count': u.flags_captured_count,
            'last_solve': u.last_solve_time
        })

    return render_template('leaderboard.html', leaderboard=leaderboard_data, total_flags_count=total_flags_count)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'change_password':
            old_password = request.form.get('old_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')

            if not user.check_password(old_password):
                flash("Current passphrase entered is incorrect.", "danger")
                return redirect(url_for('profile'))

            if len(new_password) < 8:
                flash("New passphrase must be at least 8 characters long.", "danger")
                return redirect(url_for('profile'))

            if new_password != confirm_password:
                flash("New passphrases do not match.", "danger")
                return redirect(url_for('profile'))

            user.set_password(new_password)
            db.session.commit()

            audit = AuditLog(
                user_id=user.id,
                action="PASSWORD_CHANGED",
                details=f"User {user.email} changed their password.",
                ip_address=get_client_ip()
            )
            db.session.add(audit)
            db.session.commit()

            flash("Passphrase updated successfully!", "success")
            return redirect(url_for('profile'))

    user_solves = Submission.query.filter_by(user_id=user.id, is_correct=True).order_by(Submission.submitted_at.desc()).all()
    return render_template('profile.html', user=user, user_solves=user_solves)

# ==========================================
# ADMIN DASHBOARD & MANAGEMENT
# ==========================================

@app.route('/admin')
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    verified_users = User.query.filter_by(is_verified=True).count()
    pending_users = User.query.filter_by(is_verified=False).order_by(User.created_at.desc()).all()
    approved_users = User.query.filter(User.id != session.get('user_id'), User.is_verified == True).order_by(User.created_at.desc()).all()
    total_submissions = Submission.query.count()
    correct_submissions = Submission.query.filter_by(is_correct=True).count()

    challenges = Challenge.query.order_by(Challenge.display_order).all()
    recent_submissions = Submission.query.order_by(Submission.submitted_at.desc()).limit(20).all()
    total_flags_count = sum(len(c.flags) for c in challenges)

    return render_template(
        'admin.html',
        total_users=total_users,
        verified_users=verified_users,
        pending_users=pending_users,
        approved_users=approved_users,
        total_submissions=total_submissions,
        correct_submissions=correct_submissions,
        challenges=challenges,
        recent_submissions=recent_submissions,
        total_flags_count=total_flags_count
    )

@app.route('/admin/user/approve/<int:user_id>', methods=['POST'])
@admin_required
def admin_approve_user(user_id):
    user = User.query.get_or_404(user_id)
    override_role = request.form.get('role')
    if override_role in ['player', 'admin']:
        user.role = override_role
    user.is_verified = True
    db.session.commit()

    role_label = "Administrator" if user.role == 'admin' else "Competitor (Player)"
    audit = AuditLog(
        user_id=session.get('user_id'),
        action="ADMIN_APPROVED_USER",
        details=f"Admin approved {user.name} ({user.email}) as {role_label}",
        ip_address=get_client_ip()
    )
    db.session.add(audit)
    db.session.commit()

    flash(f"Account '{user.name}' ({user.email}) approved and activated as {role_label}.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/user/reject/<int:user_id>', methods=['POST'])
@admin_required
def admin_reject_user(user_id):
    user = User.query.get_or_404(user_id)
    user_email = user.email
    user_name = user.name
    UserHintUnlock.query.filter_by(user_id=user.id).delete()
    Submission.query.filter_by(user_id=user.id).delete()
    AuditLog.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()

    audit = AuditLog(
        user_id=session.get('user_id'),
        action="ADMIN_REJECTED_USER",
        details=f"Admin rejected user {user_name} ({user_email})",
        ip_address=get_client_ip()
    )
    db.session.add(audit)
    db.session.commit()

    flash(f"Participant '{user_name}' ({user_email}) was rejected and removed.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/user/delete/<int:user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    if user_id == session.get('user_id'):
        flash("Action forbidden: You cannot delete your own admin account.", "danger")
        return redirect(url_for('admin_dashboard'))

    user = User.query.get_or_404(user_id)
    user_email = user.email
    user_name = user.name

    UserHintUnlock.query.filter_by(user_id=user.id).delete()
    Submission.query.filter_by(user_id=user.id).delete()
    AuditLog.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()

    audit = AuditLog(
        user_id=session.get('user_id'),
        action="ADMIN_DELETED_USER_PROFILE",
        details=f"Admin permanently deleted user profile: {user_name} ({user_email})",
        ip_address=get_client_ip()
    )
    db.session.add(audit)
    db.session.commit()

    flash(f"User profile '{user_name}' ({user_email}) has been permanently deleted.", "success")
    return redirect(url_for('admin_dashboard'))

# ------------------------------------------
# CHALLENGE CRUD & FLAG MANAGEMENT
# ------------------------------------------

@app.route('/admin/challenge/create', methods=['POST'])
@admin_required
def admin_create_challenge():
    name = request.form.get('name', '').strip()
    slug = request.form.get('slug', '').strip().lower()
    category = request.form.get('category', '').strip()
    difficulty = request.form.get('difficulty', 'Beginner').strip()
    points = int(request.form.get('points', 100))
    target_info = request.form.get('target_info', '').strip()
    target_type = request.form.get('target_type', 'HTTP').strip()
    short_desc = request.form.get('short_desc', '').strip()
    story_markdown = request.form.get('story_markdown', '').strip()
    display_order = int(request.form.get('display_order', 1))
    is_active = request.form.get('is_active') == 'on'

    if not name or not slug or not category:
        flash("Name, unique slug, and category are required.", "danger")
        return redirect(url_for('admin_dashboard'))

    existing = Challenge.query.filter_by(slug=slug).first()
    if existing:
        flash(f"A challenge with slug '{slug}' already exists. Choose a unique slug.", "danger")
        return redirect(url_for('admin_dashboard'))

    new_chall = Challenge(
        name=name,
        slug=slug,
        category=category,
        difficulty=difficulty,
        points=points,
        target_info=target_info,
        target_type=target_type,
        short_desc=short_desc,
        story_markdown=story_markdown,
        display_order=display_order,
        is_active=is_active
    )
    db.session.add(new_chall)
    db.session.flush()

    # Optional initial flag
    initial_flag = request.form.get('initial_flag', '').strip()
    if initial_flag:
        flag_title = request.form.get('flag_title', 'Authentic Flag').strip() or "Authentic Flag"
        flag = Flag(
            challenge_id=new_chall.id,
            flag_value=initial_flag,
            points=points,
            title=flag_title
        )
        db.session.add(flag)

    db.session.commit()

    audit = AuditLog(
        user_id=session.get('user_id'),
        action="ADMIN_CREATED_CHALLENGE",
        details=f"Admin created challenge '{name}' (slug: {slug})",
        ip_address=get_client_ip()
    )
    db.session.add(audit)
    db.session.commit()

    flash(f"Challenge '{name}' created successfully!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/challenge/edit/<int:challenge_id>', methods=['POST'])
@admin_required
def admin_edit_challenge(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    challenge.name = request.form.get('name', challenge.name).strip()
    challenge.category = request.form.get('category', challenge.category).strip()
    challenge.difficulty = request.form.get('difficulty', challenge.difficulty).strip()
    challenge.points = int(request.form.get('points', challenge.points))
    challenge.target_info = request.form.get('target_info', challenge.target_info).strip()
    challenge.target_type = request.form.get('target_type', challenge.target_type).strip()
    challenge.short_desc = request.form.get('short_desc', challenge.short_desc).strip()
    challenge.story_markdown = request.form.get('story_markdown', challenge.story_markdown).strip()
    challenge.display_order = int(request.form.get('display_order', challenge.display_order))
    challenge.is_active = request.form.get('is_active') == 'on'

    db.session.commit()
    flash(f"Challenge '{challenge.name}' updated successfully.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/challenge/delete/<int:challenge_id>', methods=['POST'])
@admin_required
def admin_delete_challenge(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    name = challenge.name

    # Cascade deletes flags, hints, unlocks, submissions via model relations
    db.session.delete(challenge)
    db.session.commit()

    audit = AuditLog(
        user_id=session.get('user_id'),
        action="ADMIN_DELETED_CHALLENGE",
        details=f"Admin deleted challenge '{name}'",
        ip_address=get_client_ip()
    )
    db.session.add(audit)
    db.session.commit()

    flash(f"Challenge '{name}' and all associated flags/hints were deleted.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/challenge/toggle/<int:challenge_id>', methods=['POST'])
@admin_required
def admin_toggle_challenge(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    challenge.is_active = not challenge.is_active
    db.session.commit()
    flash(f"Challenge '{challenge.name}' status set to {'ACTIVE' if challenge.is_active else 'DISABLED'}.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/challenge/<int:challenge_id>/flag/add', methods=['POST'])
@admin_required
def admin_add_flag(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    flag_val = request.form.get('flag_value', '').strip()
    points = int(request.form.get('points', 100))
    title = request.form.get('title', 'Authentic Flag').strip() or "Authentic Flag"

    if not flag_val:
        flash("Flag string value cannot be empty.", "danger")
        return redirect(url_for('admin_dashboard'))

    flag = Flag(challenge_id=challenge.id, flag_value=flag_val, points=points, title=title)
    db.session.add(flag)
    db.session.commit()
    flash(f"Added flag '{title}' (+{points} pts) to '{challenge.name}'.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/flag/delete/<int:flag_id>', methods=['POST'])
@admin_required
def admin_delete_flag(flag_id):
    flag = Flag.query.get_or_404(flag_id)
    title = flag.title
    db.session.delete(flag)
    db.session.commit()
    flash(f"Deleted flag '{title}'.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/challenge/<int:challenge_id>/hint/add', methods=['POST'])
@admin_required
def admin_add_hint(challenge_id):
    challenge = Challenge.query.get_or_404(challenge_id)
    hint_num = int(request.form.get('hint_number', len(challenge.hints) + 1))
    title = request.form.get('title', f"Clue #{hint_num}").strip()
    content = request.form.get('content', '').strip()
    penalty = int(request.form.get('penalty', 0))

    if not content:
        flash("Hint content cannot be empty.", "danger")
        return redirect(url_for('admin_dashboard'))

    hint = Hint(challenge_id=challenge.id, hint_number=hint_num, title=title, content=content, penalty=penalty)
    db.session.add(hint)
    db.session.commit()
    flash(f"Added Hint #{hint_num} to '{challenge.name}'.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/hint/delete/<int:hint_id>', methods=['POST'])
@admin_required
def admin_delete_hint(hint_id):
    hint = Hint.query.get_or_404(hint_id)
    db.session.delete(hint)
    db.session.commit()
    flash("Deleted hint.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/scores/reset', methods=['POST'])
@admin_required
def admin_reset_scores():
    UserHintUnlock.query.delete()
    num_subs = Submission.query.delete()
    db.session.commit()

    audit = AuditLog(
        user_id=session.get('user_id'),
        action="ADMIN_RESET_SCORES",
        details=f"Admin purged {num_subs} submissions and reset leaderboard.",
        ip_address=get_client_ip()
    )
    db.session.add(audit)
    db.session.commit()

    flash(f"Tournament leaderboard reset to zero ({num_subs} submissions purged).", "success")
    return redirect(url_for('admin_dashboard'))

# ------------------------------------------
# CSV EXPORT ROUTES
# ------------------------------------------

@app.route('/admin/export/leaderboard')
@admin_required
def export_leaderboard():
    users = User.query.filter_by(role='player', is_active=True, is_verified=True).all()
    sorted_users = sorted(users, key=get_leaderboard_sort_key)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Rank', 'Full Name', 'Email', 'Score', 'Flags Solved', 'Last Submission Time (IST)'])

    for rank, u in enumerate(sorted_users, 1):
        last_solve = to_ist(u.last_solve_time).strftime('%Y-%m-%d %I:%M:%S %p IST') if u.last_solve_time else "N/A"
        writer.writerow([rank, u.name, u.email, u.score, u.flags_captured_count, last_solve])

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=ctf_leaderboard_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response

@app.route('/admin/export/submissions')
@admin_required
def export_submissions():
    subs = Submission.query.order_by(Submission.submitted_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'User Email', 'User Name', 'Challenge', 'Submitted Flag', 'Correct', 'Points', 'IP Address', 'Timestamp (IST)'])

    for s in subs:
        user_email = s.user.email if s.user else "Unknown"
        user_name = s.user.name if s.user else "Unknown"
        challenge_name = s.challenge.name if s.challenge else "Unknown"
        sub_time = to_ist(s.submitted_at).strftime('%Y-%m-%d %I:%M:%S %p IST') if s.submitted_at else "N/A"
        writer.writerow([
            s.id, user_email, user_name, challenge_name, s.submitted_flag, 
            s.is_correct, s.points_awarded, s.ip_address, sub_time
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=ctf_submissions_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response

@app.route('/admin/export/users')
@admin_required
def export_users():
    users = User.query.filter_by(role='player').order_by(User.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Full Name', 'Email', 'Verified', 'Score', 'Flags Solved', 'Registration Date (IST)', 'Last Active (IST)'])

    for u in users:
        reg_time = to_ist(u.created_at).strftime('%Y-%m-%d %I:%M:%S %p IST') if u.created_at else "N/A"
        last_act = to_ist(u.last_active).strftime('%Y-%m-%d %I:%M:%S %p IST') if u.last_active else "N/A"
        writer.writerow([
            u.id, u.name, u.email, u.is_verified, u.score, 
            u.flags_captured_count, reg_time, last_act
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=ctf_users_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response

# ==========================================
# ERROR HANDLERS
# ==========================================

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message="Target resource or route does not exist in this grid."), 404

@app.errorhandler(429)
def too_many_requests(e):
    return render_template('error.html', code=429, message="Telemetry threshold exceeded. Too many requests."), 429

@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', code=500, message="Internal telemetry failure. An anomaly occurred."), 500

def init_app():
    with app.app_context():
        db.create_all()
        # Initialize master admin if configured in environment
        admin_email = getattr(Config, 'ADMIN_EMAIL', None)
        admin_pass = getattr(Config, 'ADMIN_PASSWORD', None)
        if admin_email and admin_pass:
            admin = User.query.filter_by(email=admin_email).first()
            if not admin:
                print(f"[+] Initializing master administrator ({admin_email})...")
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
                print(f"[+] Administrator account ({admin_email}) created.")

if __name__ == '__main__':
    init_app()
    app.run(host='0.0.0.0', port=5000, debug=True)
