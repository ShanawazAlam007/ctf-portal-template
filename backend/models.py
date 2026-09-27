from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

db = SQLAlchemy()
ph = PasswordHasher()

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    verification_token = db.Column(db.String(128), nullable=True, index=True)
    token_expires_at = db.Column(db.DateTime, nullable=True)
    role = db.Column(db.String(20), default='player', nullable=False) # 'player', 'admin'
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_active = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    submissions = db.relationship('Submission', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    audit_logs = db.relationship('AuditLog', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    hint_unlocks = db.relationship('UserHintUnlock', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password: str):
        self.password_hash = ph.hash(password)

    def check_password(self, password: str) -> bool:
        try:
            return ph.verify(self.password_hash, password)
        except VerifyMismatchError:
            return False

    @property
    def display_name(self) -> str:
        parts = self.name.strip().split()
        if len(parts) >= 2:
            return f"{parts[0]} {parts[-1][0]}."
        elif len(parts) == 1:
            return parts[0]
        return "Anonymous Player"

    @property
    def total_penalty(self) -> int:
        return sum(u.penalty_applied for u in self.hint_unlocks)

    @property
    def score(self) -> int:
        gross = sum(s.points_awarded for s in self.submissions if s.is_correct)
        return max(0, gross - self.total_penalty)

    @property
    def flags_captured_count(self) -> int:
        return len(set(s.flag_id for s in self.submissions if s.is_correct and s.flag_id))

    @property
    def last_solve_time(self):
        correct_subs = [s.submitted_at for s in self.submissions if s.is_correct]
        return max(correct_subs) if correct_subs else None

class Challenge(db.Model):
    __tablename__ = 'challenges'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(150), unique=True, nullable=False, index=True)
    category = db.Column(db.String(80), nullable=False)
    difficulty = db.Column(db.String(50), nullable=False) # 'Beginner', 'Intermediate', 'Advanced'
    points = db.Column(db.Integer, default=100, nullable=False)
    target_info = db.Column(db.String(200), default="", nullable=False)
    target_type = db.Column(db.String(50), default="HTTP", nullable=False) # 'HTTP', 'SSH', 'RDP', etc.
    short_desc = db.Column(db.Text, nullable=False)
    story_markdown = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    display_order = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    flags = db.relationship('Flag', backref='challenge', lazy='select', cascade='all, delete-orphan')
    submissions = db.relationship('Submission', backref='challenge', lazy='dynamic', cascade='all, delete-orphan')
    hints = db.relationship('Hint', backref='challenge', lazy='select', order_by='Hint.hint_number', cascade='all, delete-orphan')

class Flag(db.Model):
    __tablename__ = 'flags'

    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=False)
    flag_value = db.Column(db.String(200), nullable=False)
    points = db.Column(db.Integer, default=100, nullable=False)
    title = db.Column(db.String(120), default="Authentic Flag", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class Hint(db.Model):
    __tablename__ = 'hints'

    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=False)
    hint_number = db.Column(db.Integer, nullable=False) # 1, 2, 3
    title = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=False)
    penalty = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class UserHintUnlock(db.Model):
    __tablename__ = 'user_hint_unlocks'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=False)
    hint_id = db.Column(db.Integer, db.ForeignKey('hints.id'), nullable=False)
    penalty_applied = db.Column(db.Integer, default=0, nullable=False)
    unlocked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    hint = db.relationship('Hint', backref='unlocks')

class Submission(db.Model):
    __tablename__ = 'submissions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=False)
    flag_id = db.Column(db.Integer, db.ForeignKey('flags.id'), nullable=True)
    submitted_flag = db.Column(db.String(255), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    points_awarded = db.Column(db.Integer, default=0, nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(60), nullable=False)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
