"""SQLite implementation of BradSec functions.
Used by bradsec.py when FIREBASE_SERVICE_ACCOUNT is not set.
"""

import sqlite3
import os
import json
import time
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def get_db():
    db_path = os.environ.get("BRADPAY_DB_PATH", "bradpay.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_bradsec():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            uid TEXT,
            details TEXT,
            ip_address TEXT,
            user_agent TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_sec_events_uid ON security_events(uid);
        CREATE INDEX IF NOT EXISTS idx_sec_events_type ON security_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_sec_events_severity ON security_events(severity);
        CREATE INDEX IF NOT EXISTS idx_sec_events_created ON security_events(created_at);
        CREATE TABLE IF NOT EXISTS flagged_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_ref TEXT NOT NULL,
            sender_uid TEXT,
            recipient_uid TEXT,
            amount INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            rules_triggered TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            reviewed_by TEXT,
            reviewed_at TEXT,
            resolution_note TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_flags_status ON flagged_transactions(status);
        CREATE INDEX IF NOT EXISTS idx_flags_tx ON flagged_transactions(tx_ref);
        CREATE TABLE IF NOT EXISTS rate_limit_counts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL,
            action TEXT NOT NULL,
            window_start REAL NOT NULL,
            count INTEGER NOT NULL DEFAULT 1,
            UNIQUE(uid, action, window_start)
        );
        CREATE INDEX IF NOT EXISTS idx_rate_limit_lookup ON rate_limit_counts(uid, action, window_start);
    """)
    conn.commit()
    conn.close()


def log_event(event_type, severity="info", uid=None, details=None, ip_address=None, user_agent=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO security_events (event_type, severity, uid, details, ip_address, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
        (event_type, severity, uid, json.dumps(details) if details else None, ip_address, user_agent),
    )
    conn.commit()
    conn.close()


def get_events(limit=50, offset=0, event_type=None, severity=None, uid=None):
    conn = get_db()
    clauses = []
    params = []
    if uid:
        clauses.append("uid = ?")
        params.append(uid)
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    where = " AND ".join(clauses) if clauses else "1"
    rows = conn.execute(
        f"SELECT * FROM security_events WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_events(event_type=None, severity=None, uid=None):
    conn = get_db()
    clauses = []
    params = []
    if uid:
        clauses.append("uid = ?")
        params.append(uid)
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if severity:
        clauses.append("severity = ?")
        params.append(severity)
    where = " AND ".join(clauses) if clauses else "1"
    row = conn.execute(f"SELECT COUNT(*) as cnt FROM security_events WHERE {where}", params).fetchone()
    conn.close()
    return row["cnt"]


def _window_key(action):
    from bradsec import RATE_LIMITS
    cfg = RATE_LIMITS.get(action, {"max": 10, "window": 3600})
    now = time.time()
    return now - (now % cfg["window"])


def check_rate_limit(uid, action):
    from bradsec import RATE_LIMITS
    cfg = RATE_LIMITS.get(action)
    if not cfg:
        return True
    w_start = _window_key(action)
    conn = get_db()
    row = conn.execute(
        "SELECT count FROM rate_limit_counts WHERE uid = ? AND action = ? AND window_start = ?",
        (uid, action, w_start),
    ).fetchone()
    if row and row["count"] >= cfg["max"]:
        conn.close()
        return False
    if row:
        conn.execute(
            "UPDATE rate_limit_counts SET count = count + 1 WHERE uid = ? AND action = ? AND window_start = ?",
            (uid, action, w_start),
        )
    else:
        conn.execute(
            "INSERT INTO rate_limit_counts (uid, action, window_start, count) VALUES (?, ?, ?, 1)",
            (uid, action, w_start),
        )
    conn.commit()
    conn.close()
    return True


def get_rate_limit_remaining(uid, action):
    from bradsec import RATE_LIMITS
    cfg = RATE_LIMITS.get(action)
    if not cfg:
        return -1
    w_start = _window_key(action)
    conn = get_db()
    row = conn.execute(
        "SELECT count FROM rate_limit_counts WHERE uid = ? AND action = ? AND window_start = ?",
        (uid, action, w_start),
    ).fetchone()
    conn.close()
    used = row["count"] if row else 0
    return max(0, cfg["max"] - used)


def reset_rate_limit(uid, action):
    w_start = _window_key(action)
    conn = get_db()
    conn.execute(
        "DELETE FROM rate_limit_counts WHERE uid = ? AND action = ? AND window_start = ?",
        (uid, action, w_start),
    )
    conn.commit()
    conn.close()


def get_user_by_firebase_uid(firebase_uid):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE firebase_uid = ?", (firebase_uid,)).fetchone()
    conn.close()
    return dict(user) if user else None


def get_transactions(firebase_uid, limit=100):
    conn = get_db()
    user = conn.execute("SELECT id FROM users WHERE firebase_uid = ?", (firebase_uid,)).fetchone()
    if not user:
        conn.close()
        return []
    rows = conn.execute(
        """SELECT t.*, u1.firebase_uid as sender_uid, u2.firebase_uid as recipient_uid
           FROM transactions t
           JOIN users u1 ON t.sender_id = u1.id
           JOIN users u2 ON t.recipient_id = u2.id
           WHERE t.sender_id = ? OR t.recipient_id = ?
           ORDER BY t.created_at DESC LIMIT ?""",
        (user["id"], user["id"], limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def evaluate_transaction(sender_uid, recipient_uid, amount, tx_ref=None):
    import json, time
    conn = get_db()
    conn.execute(
        "INSERT INTO flagged_transactions (tx_ref, sender_uid, recipient_uid, amount, score, rules_triggered) VALUES (?, ?, ?, ?, ?, ?)",
        (tx_ref or f"FRAUD-{int(time.time())}-{sender_uid[:8]}", sender_uid, recipient_uid, amount, 0, "[]"),
    )
    conn.commit()
    conn.close()


def get_flagged_transactions(status=None, limit=50, offset=0):
    conn = get_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM flagged_transactions WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (status, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM flagged_transactions ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resolve_flag(flag_id, status, reviewer_uid, note=None):
    conn = get_db()
    flag = conn.execute("SELECT * FROM flagged_transactions WHERE id = ?", (flag_id,)).fetchone()
    if not flag:
        conn.close()
        return None
    conn.execute(
        "UPDATE flagged_transactions SET status = ?, reviewed_by = ?, reviewed_at = datetime('now'), resolution_note = ? WHERE id = ?",
        (status, reviewer_uid, note or "", flag_id),
    )
    conn.commit()
    conn.close()
    return dict(flag)


def get_flag_stats():
    conn = get_db()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM flagged_transactions GROUP BY status"
    ).fetchall()
    conn.close()
    stats = {r["status"]: r["cnt"] for r in rows}
    return {
        "open": stats.get("open", 0),
        "approved": stats.get("approved", 0),
        "blocked": stats.get("blocked", 0),
        "total": sum(stats.values()),
    }


def get_security_summary():
    conn = get_db()
    high = conn.execute(
        "SELECT COUNT(*) as cnt FROM security_events WHERE severity IN ('high','critical') AND created_at >= datetime('now', '-24 hours')"
    ).fetchone()
    total_24h = conn.execute(
        "SELECT COUNT(*) as cnt FROM security_events WHERE created_at >= datetime('now', '-24 hours')"
    ).fetchone()
    recent = conn.execute(
        "SELECT * FROM security_events ORDER BY created_at DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return {
        "high_severity_24h": high["cnt"],
        "total_events_24h": total_24h["cnt"],
        "open_flags": get_flag_stats()["open"],
        "recent_events": [dict(r) for r in recent],
    }
