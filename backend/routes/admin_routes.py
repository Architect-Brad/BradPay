from flask import Blueprint, request, jsonify, g, current_app
import hmac
import logging
from datetime import datetime, timezone
from data import (
    get_user_by_firebase_uid,
    update_kes_balance,
)
from routes.auth_routes import require_auth, require_user
from ledger import get_ledger
from bradsec import log_event, check_rate_limit, require_rate_limit
from models import get_db

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def require_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        api_key = current_app.config.get("ADMIN_API_KEY")
        if not api_key:
            return jsonify({"error": "Admin API key not configured"}), 500
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Invalid admin key"}), 401
        supplied = auth.split(" ", 1)[1]
        # hmac.compare_digest avoids leaking key length/prefix via response
        # timing differences, unlike a plain `==` string comparison.
        if not hmac.compare_digest(supplied, api_key):
            return jsonify({"error": "Invalid admin key"}), 401
        return f(*args, **kwargs)
    return decorated


def _get_system_user_id():
    conn = get_db()
    system = conn.execute(
        "SELECT id FROM users WHERE firebase_uid = '__system__'"
    ).fetchone()
    if system:
        conn.close()
        return system["id"]
    conn.execute(
        "INSERT INTO users (firebase_uid, display_name, pin_hash) VALUES ('__system__', 'System', 'x')"
    )
    conn.commit()
    system = conn.execute(
        "SELECT id FROM users WHERE firebase_uid = '__system__'"
    ).fetchone()
    conn.close()
    return system["id"]


def _record_admin_tx(uid, amount, type_, note):
    conn = None
    try:
        conn = get_db()
        user = conn.execute(
            "SELECT id FROM users WHERE firebase_uid = ?", (uid,)
        ).fetchone()
        if not user:
            return {"error": "User not found"}, 404

        system_id = _get_system_user_id()
        tx_ref = f"ADMIN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{user['id']}-{type_}"
        conn.execute(
            """INSERT INTO transactions (tx_ref, sender_id, recipient_id, amount, fee, type, status, note)
               VALUES (?, ?, ?, ?, 0, ?, 'completed', ?)""",
            (tx_ref, system_id, user["id"], abs(amount), type_, note or f"Admin {type_}"),
        )
        conn.commit()

        tx = conn.execute(
            "SELECT * FROM transactions WHERE tx_ref = ?", (tx_ref,)
        ).fetchone()
        return dict(tx)
    except Exception as e:
        if conn:
            conn.rollback()
        return {"error": str(e)}, 500
    finally:
        if conn:
            conn.close()


@admin_bp.route("/credit", methods=["POST"])
@require_admin
@require_rate_limit("admin_action")
def credit():
    data = request.get_json(silent=True) or {}
    uid = data.get("uid")
    amount = data.get("amount")
    note = data.get("note", "Admin credit")

    if not uid or not amount:
        return jsonify({"error": "uid and amount are required"}), 400
    try:
        amount = int(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a positive integer (cents)"}), 400

    user = get_user_by_firebase_uid(uid)
    if not user:
        return jsonify({"error": "User not found"}), 404

    update_kes_balance(uid, amount)
    tx = _record_admin_tx(uid, amount, "deposit", note)
    if isinstance(tx, tuple):
        return jsonify(tx[0]), tx[1]

    try:
        get_ledger().add_transaction(tx)
    except Exception:
        pass

    log_event("admin_credit", "info", uid, {"amount": amount, "note": note})
    return jsonify({
        "message": f"Credited KES {amount / 100:.2f}",
        "amount": amount,
        "uid": uid,
        "new_balance": (user.get("kes_balance", 0) or 0) + amount,
    })


@admin_bp.route("/debit", methods=["POST"])
@require_admin
@require_rate_limit("admin_action")
def debit():
    data = request.get_json(silent=True) or {}
    uid = data.get("uid")
    amount = data.get("amount")
    note = data.get("note", "Admin debit")

    if not uid or not amount:
        return jsonify({"error": "uid and amount are required"}), 400
    try:
        amount = int(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a positive integer (cents)"}), 400

    user = get_user_by_firebase_uid(uid)
    if not user:
        return jsonify({"error": "User not found"}), 404

    kes = user.get("kes_balance", 0)
    if kes < amount:
        return jsonify({"error": "Insufficient KES balance"}), 400

    update_kes_balance(uid, -amount)
    tx = _record_admin_tx(uid, amount, "withdrawal", note)
    if isinstance(tx, tuple):
        return jsonify(tx[0]), tx[1]

    try:
        get_ledger().add_transaction(tx)
    except Exception:
        pass

    log_event("admin_debit", "info", uid, {"amount": amount, "note": note})
    return jsonify({
        "message": f"Debited KES {amount / 100:.2f}",
        "amount": amount,
        "uid": uid,
        "new_balance": (user.get("kes_balance", 0) or 0) - amount,
    })


@admin_bp.route("/faucet", methods=["POST"])
@require_admin
@require_rate_limit("admin_action")
def faucet():
    data = request.get_json(silent=True) or {}
    uid = data.get("uid")
    amount = int(current_app.config.get("FAUCET_AMOUNT", 10000000))
    if not uid:
        return jsonify({"error": "uid is required"}), 400

    user = get_user_by_firebase_uid(uid)
    if not user:
        return jsonify({"error": "User not found"}), 404

    update_kes_balance(uid, amount)
    tx = _record_admin_tx(uid, amount, "deposit", f"Faucet credit — KES {amount / 100:.2f}")
    if isinstance(tx, tuple):
        return jsonify(tx[0]), tx[1]

    try:
        get_ledger().add_transaction(tx)
    except Exception:
        pass

    return jsonify({
        "message": f"Faucet credited KES {amount / 100:.2f}",
        "amount": amount,
        "new_balance": (user.get("kes_balance", 0) or 0) + amount,
    })
