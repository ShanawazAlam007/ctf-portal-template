#!/usr/bin/env python3
"""
CTF Competition Reset Utility
Resets player submissions, scores, and optionally player accounts for a new tournament season.
Admin accounts are safely preserved.
"""

import os
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app import app, db
from models import User, Submission, UserHintUnlock, AuditLog, Challenge, Flag, Hint

def reset_scores():
    print("[!] WARNING: This will delete ALL player flag submissions and hint unlocks, resetting the leaderboard!")
    print("[!] Challenges and user accounts will be preserved.")
    confirm = input("Type 'RESET-SCORES' to confirm: ")
    if confirm != 'RESET-SCORES':
        print("[-] Operation aborted.")
        return

    with app.app_context():
        num_unlocks = UserHintUnlock.query.delete()
        num_subs = Submission.query.delete()
        audit = AuditLog(
            action="SCORES_RESET",
            details=f"Admin initiated score reset. {num_subs} submissions and {num_unlocks} hint unlocks removed."
        )
        db.session.add(audit)
        db.session.commit()
        print(f"[+] Successfully purged {num_subs} submissions and {num_unlocks} hint unlocks. Leaderboard has been reset to zero.")

def reset_all_players():
    print("[!] CRITICAL WARNING: This will delete ALL player accounts, submissions, and hint unlocks!")
    print("[!] Only administrator accounts and challenges will be preserved.")
    confirm = input("Type 'RESET-ALL-PLAYERS' to confirm: ")
    if confirm != 'RESET-ALL-PLAYERS':
        print("[-] Operation aborted.")
        return

    with app.app_context():
        UserHintUnlock.query.delete()
        num_subs = Submission.query.delete()
        players = User.query.filter(User.role != 'admin').all()
        num_players = len(players)
        for p in players:
            db.session.delete(p)
        
        audit = AuditLog(
            action="COMPETITION_FULL_RESET",
            details=f"Full tournament player reset. Deleted {num_players} players and {num_subs} submissions."
        )
        db.session.add(audit)
        db.session.commit()
        print(f"[+] Full reset completed. Deleted {num_players} player accounts and {num_subs} submissions.")

def reset_all_challenges():
    print("[!] CRITICAL WARNING: This will delete ALL challenges, flags, hints, and associated submissions!")
    confirm = input("Type 'DELETE-CHALLENGES' to confirm: ")
    if confirm != 'DELETE-CHALLENGES':
        print("[-] Operation aborted.")
        return

    with app.app_context():
        UserHintUnlock.query.delete()
        Submission.query.delete()
        Hint.query.delete()
        Flag.query.delete()
        num_challs = Challenge.query.delete()
        db.session.commit()
        print(f"[+] Successfully removed {num_challs} challenges.")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 reset_competition.py --scores-only")
        print("  python3 reset_competition.py --all-players")
        print("  python3 reset_competition.py --all-challenges")
        sys.exit(1)

    if sys.argv[1] == '--scores-only':
        reset_scores()
    elif sys.argv[1] == '--all-players':
        reset_all_players()
    elif sys.argv[1] == '--all-challenges':
        reset_all_challenges()
    else:
        print(f"[-] Unknown option: {sys.argv[1]}")
        sys.exit(1)
