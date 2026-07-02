import sqlite3
import os
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import g, request, jsonify, current_app

logger = logging.getLogger(__name__)

BRADSEC_EVENT_TYPES = (
    "login_success", "login_failure", "registration", "logout",
    "send", "receive", "deposit", "withdrawal",
    "admin_credit", "admin_debit",
    "agent_cash_in", "agent_cash_out", "float_topup", "float_transfer",
    "rate_limit_hit", "fraud_flag", "fraud_resolve",
    "pin_change", "pin_failure",
    "suspicious_ip", "suspicious_device",
)

BRADSEC_SEVERITIES = ("info", "low", "medium", "high", "critical")

FRAUD_RULES = {
    "velocity": {"label": "High transaction velocity", "severity": "high", "score": 40},
    "amount_anomaly": {"label": "Unusually large transaction", "severity": "high", "score": 35},
    "new_account": {"label": "New account — elevated risk", "severity": "medium", "score": 25},
    "rapid_recipient": {"label": "Rapid same-recipient transfers", "severity": "medium", "score": 30},
    "balance_drain": {"label": "Balance drain attempt", "severity": "medium", "score": 20},
    "unusual_hours": {"label": "Transaction during unusual hours", "severity": "low", "score": 10},
    "round_numbers": {"label": "Pattern — round number amounts", "severity": "low", "score": 5},
}

RATE_LIMITS = {
    "send":          {"max": 10, "window": 3600},
    "login":         {"max": 5,  "window": 900},
    "register":      {"max": 3,  "window": 3600},
    "stkpush":       {"max": 3,  "window": 300},
    "cash_in":       {"max": 20, "window": 3600},
    "cash_out":      {"max": 20, "window": 3600},
    "admin_action":  {"max": 30, "window": 3600},
}

FLAG_THRESHOLD = 40

# ── DB ──

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
    logger.info("BradSec tables initialized")


# ── Event Logging ──

def log_event(event_type, severity="info", uid=None, details=None, ip_address=None, user_agent=None):
    if event_type not in BRADSEC_EVENT_TYPES:
        event_type = "suspicious_ip"
    if severity not in BRADSEC_SEVERITIES:
        severity = "info"

    conn = get_db()
    conn.execute(
        """INSERT INTO security_events (event_type, severity, uid, details, ip_address, user_agent)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (event_type, severity, uid, json.dumps(details) if details else None, ip_address, user_agent),
    )
    conn.commit()
    conn.close()
    logger.info("BradSec event: %s [%s] uid=%s", event_type, severity, uid)


def get_events(uid=None, event_type=None, severity=None, limit=50, offset=0):
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


def count_events(uid=None, event_type=None, severity=None, since=None):
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
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    where = " AND ".join(clauses) if clauses else "1"
    row = conn.execute(f"SELECT COUNT(*) as cnt FROM security_events WHERE {where}", params).fetchone()
    conn.close()
    return row["cnt"]


# ── Rate Limiting ──

def _window_key(action):
    cfg = RATE_LIMITS.get(action, {"max": 10, "window": 3600})
    now = time.time()
    return now - (now % cfg["window"])


def check_rate_limit(uid, action):
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
        log_event("rate_limit_hit", "medium", uid, {"action": action, "max": cfg["max"], "window": cfg["window"]})
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


# ── Fraud Detection ──

def _get_user_created_at(uid):
    conn = get_db()
    row = conn.execute("SELECT created_at FROM users WHERE firebase_uid = ?", (uid,)).fetchone()
    conn.close()
    return row["created_at"] if row else None


def _count_recent_actions(uid, action, seconds):
    since = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM security_events WHERE uid = ? AND event_type = ? AND created_at >= ?",
        (uid, action, since),
    ).fetchone()
    conn.close()
    return row["cnt"]


def _count_recent_recipient(sender_uid, recipient_uid, seconds):
    conn = get_db()
    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM transactions t
           JOIN users s ON t.sender_id = s.id
           JOIN users r ON t.recipient_id = r.id
           WHERE s.firebase_uid = ? AND r.firebase_uid = ?
           AND t.created_at >= datetime('now', ?)""",
        (sender_uid, recipient_uid, f"-{seconds} seconds"),
    ).fetchone()
    conn.close()
    return row["cnt"]


def evaluate_transaction(sender_uid, recipient_uid, amount, tx_ref=None):
    triggered = []
    total_score = 0

    # 1. Velocity: >5 sends in 5 minutes
    recent_sends = _count_recent_actions(sender_uid, "send", 300)
    if recent_sends >= 5:
        triggered.append(FRAUD_RULES["velocity"])
        total_score += FRAUD_RULES["velocity"]["score"]

    # 2. Amount anomaly: >100,000 KES
    if amount > 10_000_000:
        triggered.append(FRAUD_RULES["amount_anomaly"])
        total_score += FRAUD_RULES["amount_anomaly"]["score"]

    # 3. New account risk: <24h old, sending >10,000 KES
    created = _get_user_created_at(sender_uid)
    if created and amount > 1_000_000:
        try:
            created_dt = datetime.fromisoformat(created)
            if datetime.now(timezone.utc) - created_dt < timedelta(hours=24):
                triggered.append(FRAUD_RULES["new_account"])
                total_score += FRAUD_RULES["new_account"]["score"]
        except (ValueError, TypeError):
            pass

    # 4. Rapid same-recipient: 3+ in 10 minutes
    recent_recipient = _count_recent_recipient(sender_uid, recipient_uid, 600)
    if recent_recipient >= 3:
        triggered.append(FRAUD_RULES["rapid_recipient"])
        total_score += FRAUD_RULES["rapid_recipient"]["score"]

    # 5. Balance drain: >90% of balance
    conn = get_db()
    user = conn.execute(
        "SELECT kes_balance FROM users WHERE firebase_uid = ?", (sender_uid,)
    ).fetchone()
    conn.close()
    if user:
        kes = user["kes_balance"] or 0
        if kes > 0 and amount > kes * 0.9:
            triggered.append(FRAUD_RULES["balance_drain"])
            total_score += FRAUD_RULES["balance_drain"]["score"]

    # 6. Unusual hours: 11PM-5AM
    hour = datetime.now(timezone.utc).hour
    if hour < 5 or hour >= 23:
        triggered.append(FRAUD_RULES["unusual_hours"])
        total_score += FRAUD_RULES["unusual_hours"]["score"]

    # 7. Round numbers
    if amount % 100000 == 0 and amount >= 500000:
        triggered.append(FRAUD_RULES["round_numbers"])
        total_score += FRAUD_RULES["round_numbers"]["score"]

    total_score = min(total_score, 100)
    is_flagged = total_score >= FLAG_THRESHOLD

    if is_flagged:
        ref = tx_ref or f"FRAUD-{int(time.time())}-{sender_uid[:8]}"
        conn = get_db()
        conn.execute(
            """INSERT INTO flagged_transactions (tx_ref, sender_uid, recipient_uid, amount, score, rules_triggered)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ref, sender_uid, recipient_uid, amount, total_score,
             json.dumps([r["label"] for r in triggered])),
        )
        conn.commit()
        conn.close()
        log_event("fraud_flag", "high", sender_uid, {
            "tx_ref": ref, "amount": amount, "score": total_score,
            "rules": [r["label"] for r in triggered],
        })

    return {
        "score": total_score,
        "flagged": is_flagged,
        "threshold": FLAG_THRESHOLD,
        "rules_triggered": [r["label"] for r in triggered],
    }


# ── Flag Management (Admin) ──

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


def resolve_flag(flag_id, admin_uid, resolution, note=""):
    conn = get_db()
    flag = conn.execute("SELECT * FROM flagged_transactions WHERE id = ?", (flag_id,)).fetchone()
    if not flag:
        conn.close()
        return None
    conn.execute(
        "UPDATE flagged_transactions SET status = ?, reviewed_by = ?, reviewed_at = datetime('now'), resolution_note = ? WHERE id = ?",
        (resolution, admin_uid, note, flag_id),
    )
    conn.commit()
    conn.close()
    log_event("fraud_resolve", "info", admin_uid, {"flag_id": flag_id, "resolution": resolution})
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


# ── Flask Decorator ──

def require_rate_limit(action):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            uid = getattr(g, "firebase_uid", None)
            if not uid:
                return f(*args, **kwargs)
            if not check_rate_limit(uid, action):
                return jsonify({
                    "error": "Rate limit exceeded",
                    "action": action,
                    "retry_after": RATE_LIMITS.get(action, {}).get("window", 3600),
                }), 429
            return f(*args, **kwargs)
        return decorated
    return decorator
