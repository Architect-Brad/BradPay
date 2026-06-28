from flask import Blueprint, request, jsonify, g
from routes.auth_routes import require_auth, require_user
from data import (
    create_transaction,
    get_transactions,
    get_user_by_firebase_uid,
    get_balance,
)

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
    offline_id = data.get("offlineId")

    if not recipient_uid:
        return jsonify({"error": "Recipient UID is required"}), 400

    try:
        amount = int(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400

    result = create_transaction(
        sender_id=g.current_user["id"],
        recipient_uid=recipient_uid,
        amount=amount,
        note=note,
        offline_id=offline_id,
    )

    if isinstance(result, dict) and "error" in result:
        status = result.get("_status", 400)
        return jsonify(result), status

    return jsonify({"message": "Transfer successful", "transaction": result}), 201


@tx_bp.route("/history", methods=["GET"])
@require_auth
@require_user
def history():
    limit = request.args.get("limit", 50, type=int)
    txs = get_transactions(g.current_user["id"], limit=min(limit, 200))
    return jsonify({"transactions": txs})


@tx_bp.route("/lookup", methods=["POST"])
@require_auth
@require_user
def lookup():
    data = request.get_json(silent=True) or {}
    identifier = data.get("identifier")
    if not identifier:
        return jsonify({"error": "Email, phone, or UID is required"}), 400

    user = get_user_by_firebase_uid(identifier)
    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "uid": user["firebase_uid"],
        "displayName": user["display_name"],
        "email": user["email"],
        "phone": user["phone"],
    })
