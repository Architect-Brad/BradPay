"""BradSec — Security, fraud detection, rate limiting for BradPay.

Dispatches to Firestore backend when FIREBASE_SERVICE_ACCOUNT is set,
otherwise uses direct SQLite.
"""

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
AUTO_BLOCK_ENABLED = os.environ.get("BRADSEC_AUTO_BLOCK", "").lower() in ("1", "true", "yes")
AUTO_BLOCK_THRESHOLD = int(os.environ.get("BRADSEC_AUTO_BLOCK_THRESHOLD", "60"))

_use_firestore = bool(os.environ.get("FIREBASE_SERVICE_ACCOUNT"))


def _backend():
    if _use_firestore:
        import firestore_db as backend
        return backend
    import bradsec_sqlite as backend
    return backend


def init_bradsec():
    _backend().init_bradsec()


def log_event(event_type, severity="info", uid=None, details=None, ip_address=None, user_agent=None):
    if event_type not in BRADSEC_EVENT_TYPES:
        event_type = "suspicious_ip"
    if severity not in BRADSEC_SEVERITIES:
        severity = "info"
    _backend().log_event(event_type, severity, uid, details, ip_address, user_agent)
    logger.info("BradSec event: %s [%s] uid=%s", event_type, severity, uid)


def get_events(uid=None, event_type=None, severity=None, limit=50, offset=0):
    return _backend().get_events(limit=limit, offset=offset, event_type=event_type, severity=severity, uid=uid)


def count_events(uid=None, event_type=None, severity=None, since=None):
    return _backend().count_events(event_type=event_type, severity=severity, uid=uid)


def check_rate_limit(uid, action):
    cfg = RATE_LIMITS.get(action)
    if not cfg:
        return True
    ok = _backend().check_rate_limit(uid, action)
    if not ok:
        log_event("rate_limit_hit", "medium", uid, {"action": action, "max": cfg["max"], "window": cfg["window"]})
    return ok


def get_rate_limit_remaining(uid, action):
    return _backend().get_rate_limit_remaining(uid, action)


def reset_rate_limit(uid, action):
    _backend().reset_rate_limit(uid, action)


def _get_user_created_at(uid):
    user = _backend().get_user_by_firebase_uid(uid)
    return user.get("created_at") if user else None


def _count_recent_actions(uid, action, seconds):
    return _backend().count_events(uid=uid, event_type=action)


def _count_recent_recipient(sender_uid, recipient_uid, seconds):
    txs = _backend().get_transactions(sender_uid, limit=100)
    since = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    count = 0
    for tx in txs:
        if tx.get("recipient_uid") == recipient_uid and tx.get("created_at", "") >= since:
            count += 1
    return count


def get_settings():
    merged = {
        "auto_block_enabled": AUTO_BLOCK_ENABLED,
        "auto_block_threshold": AUTO_BLOCK_THRESHOLD,
        "flag_threshold": FLAG_THRESHOLD,
    }
    db_settings = _backend().get_bradsec_settings()
    if db_settings:
        merged["auto_block_enabled"] = db_settings.get("auto_block_enabled", AUTO_BLOCK_ENABLED)
        merged["auto_block_threshold"] = db_settings.get("auto_block_threshold", AUTO_BLOCK_THRESHOLD)
    return merged


def update_settings(overrides):
    current = get_settings()
    current.update(overrides)
    _backend().set_bradsec_settings(current)
    return current


def evaluate_transaction(sender_uid, recipient_uid, amount, tx_ref=None):
    triggered = []
    total_score = 0
    settings = get_settings()
    auto_block = settings["auto_block_enabled"]
    auto_block_threshold = settings["auto_block_threshold"]

    recent_sends = _count_recent_actions(sender_uid, "send", 300)
    if recent_sends >= 5:
        triggered.append(FRAUD_RULES["velocity"])
        total_score += FRAUD_RULES["velocity"]["score"]

    if amount > 10_000_000:
        triggered.append(FRAUD_RULES["amount_anomaly"])
        total_score += FRAUD_RULES["amount_anomaly"]["score"]

    created = _get_user_created_at(sender_uid)
    if created and amount > 1_000_000:
        try:
            created_dt = datetime.fromisoformat(created)
            if datetime.now(timezone.utc) - created_dt < timedelta(hours=24):
                triggered.append(FRAUD_RULES["new_account"])
                total_score += FRAUD_RULES["new_account"]["score"]
        except (ValueError, TypeError):
            pass

    recent_recipient = _count_recent_recipient(sender_uid, recipient_uid, 600)
    if recent_recipient >= 3:
        triggered.append(FRAUD_RULES["rapid_recipient"])
        total_score += FRAUD_RULES["rapid_recipient"]["score"]

    user = _backend().get_user_by_firebase_uid(sender_uid)
    if user:
        # P2P spends `balance` (main wallet); kes_balance is a legacy mirror.
        wallet = user.get("balance", 0) or 0
        if wallet > 0 and amount > wallet * 0.9:
            triggered.append(FRAUD_RULES["balance_drain"])
            total_score += FRAUD_RULES["balance_drain"]["score"]

    hour = datetime.now(timezone.utc).hour
    if hour < 5 or hour >= 23:
        triggered.append(FRAUD_RULES["unusual_hours"])
        total_score += FRAUD_RULES["unusual_hours"]["score"]

    if amount % 100000 == 0 and amount >= 500000:
        triggered.append(FRAUD_RULES["round_numbers"])
        total_score += FRAUD_RULES["round_numbers"]["score"]

    total_score = min(total_score, 100)
    is_flagged = total_score >= FLAG_THRESHOLD
    is_auto_blocked = auto_block and is_flagged and total_score >= auto_block_threshold

    if is_flagged:
        ref = tx_ref or f"FRAUD-{int(time.time())}-{sender_uid[:8]}"
        flag_status = "blocked" if is_auto_blocked else "open"
        _backend().evaluate_transaction(sender_uid, recipient_uid, amount, ref, status=flag_status)
        log_event("fraud_flag", "high", sender_uid, {
            "tx_ref": ref, "amount": amount, "score": total_score,
            "rules": [r["label"] for r in triggered],
            "auto_blocked": is_auto_blocked,
        })

    return {
        "score": total_score,
        "flagged": is_flagged,
        "auto_blocked": is_auto_blocked,
        "threshold": FLAG_THRESHOLD,
        "auto_block_threshold": auto_block_threshold if auto_block else None,
        "rules_triggered": [r["label"] for r in triggered],
    }


def get_flagged_transactions(status=None, limit=50, offset=0):
    return _backend().get_flagged_transactions(status=status, limit=limit, offset=offset)


def resolve_flag(flag_id, admin_uid, resolution, note=""):
    result = _backend().resolve_flag(flag_id, resolution, admin_uid, note)
    if result:
        log_event("fraud_resolve", "info", admin_uid, {"flag_id": flag_id, "resolution": resolution})
    return result


def get_flag_stats():
    return _backend().get_flag_stats()


def get_security_summary():
    return _backend().get_security_summary()


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
