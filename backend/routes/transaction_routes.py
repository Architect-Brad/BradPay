from flask import Blueprint, request, jsonify, g
from datetime import datetime, timezone
from routes.auth_routes import require_auth, require_user
from data import (
    create_transaction,
    get_transactions,
    get_user_by_firebase_uid,
    get_user_by_phone_or_email,
    get_balance,
    verify_pin,
)
from ledger import get_ledger
from bradsec import log_event, evaluate_transaction, check_rate_limit
import logging

logger = logging.getLogger(__name__)

tx_bp = Blueprint("transactions", __name__, url_prefix="/api/transactions")


@tx_bp.route("/balance", methods=["GET"])
@require_auth
@require_user
def balance():
    return jsonify({"balance": g.current_user["balance"]})


@tx_bp.route("/send", methods=["POST"])
@require_auth
@require_user
def send():
    data = request.get_json(silent=True) or {}
    recipient_uid = data.get("recipientUid") or data.get("recipient")
    amount = data.get("amount")
    note = data.get("note")
    pin = data.get("pin")
    offline_id = data.get("offlineId")

    if not recipient_uid:
        return jsonify({"error": "Recipient UID is required"}), 400

    if not pin:
        return jsonify({"error": "PIN is required to send money"}), 400

    if not verify_pin(g.firebase_uid, pin):
        return jsonify({"error": "Incorrect PIN"}), 403

    try:
        amount = int(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400

    if not check_rate_limit(g.firebase_uid, "send"):
        return jsonify({"error": "Send rate limit exceeded. Try again later."}), 429

    # Evaluate fraud BEFORE processing — auto-blocked transactions are rejected
    tx_ref = offline_id or f"BRADPAY-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{g.firebase_uid[:8]}"
    fraud = evaluate_transaction(g.firebase_uid, recipient_uid, amount, tx_ref)
    if fraud.get("auto_blocked"):
        log_event("fraud_flag", "high", g.firebase_uid, {
            "tx_ref": tx_ref, "amount": amount, "score": fraud["score"],
            "rules": fraud["rules_triggered"], "auto_blocked": True,
        })
        return jsonify({
            "error": "Transaction blocked by fraud detection",
            "fraud": fraud,
        }), 403

    if fraud["flagged"]:
        logger.warning("Flagged transaction %s: score=%d reasons=%s", tx_ref, fraud["score"], fraud["rules_triggered"])

    log_event("send", "info", g.firebase_uid, {
        "recipient_uid": recipient_uid, "amount": amount, "note": note, "offline_id": offline_id,
    })

    result = create_transaction(
        sender_uid=g.firebase_uid,
        recipient_uid=recipient_uid,
        amount=amount,
        note=note,
        offline_id=offline_id,
    )

    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]

    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 400

    get_ledger().add_transaction(result)

    return jsonify({"message": "Transfer successful", "transaction": result}), 201


@tx_bp.route("/history", methods=["GET"])
@require_auth
@require_user
def history():
    limit = request.args.get("limit", 50, type=int)
    txs = get_transactions(g.firebase_uid, limit=min(limit, 200))
    return jsonify({"transactions": txs})


@tx_bp.route("/lookup", methods=["POST"])
@require_auth
@require_user
def lookup():
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier")
    if not identifier:
        return jsonify({"error": "Email, phone, or UID is required"}), 400
    identifier = identifier.strip()

    user = get_user_by_firebase_uid(identifier)
    if not user:
        user = get_user_by_phone_or_email(identifier)

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "uid": user.get("firebase_uid") or user.get("id"),
        "displayName": user.get("display_name") or user.get("displayName"),
        "email": user.get("email"),
        "phone": user.get("phone"),
    })
