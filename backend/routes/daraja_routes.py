from flask import Blueprint, request, jsonify, g
import logging

from routes.auth_routes import require_auth, require_user
from daraja import stk_push, b2c, query_status, cents_to_kes, kes_to_cents
from safaricom import require_safaricom_ip
from data import (
    create_mpesa_transaction,
    get_mpesa_transactions,
    get_mpesa_transaction_by_checkout_id,
    get_mpesa_transaction_by_conversation_id,
    update_mpesa_transaction_status,
    update_kes_balance,
    get_kes_balance,
)

logger = logging.getLogger(__name__)

daraja_bp = Blueprint("daraja", __name__, url_prefix="/api/daraja")


def _claim_callback(identifier, result_code, result_desc):
    """Prefer atomic claim; fall back if backend lacks the helper."""
    try:
        from data import claim_mpesa_callback
        return claim_mpesa_callback(identifier, result_code, result_desc)
    except ImportError:
        tx = (
            get_mpesa_transaction_by_checkout_id(identifier)
            or get_mpesa_transaction_by_conversation_id(identifier)
        )
        if not tx:
            return None, False
        if tx.get("status") != "pending":
            return tx, False
        update_mpesa_transaction_status(identifier, result_code, result_desc)
        tx["status"] = "completed" if result_code == 0 else "failed"
        return tx, True


@daraja_bp.route("/stkpush", methods=["POST"])
@require_auth
@require_user
def stkpush():
    data = request.get_json(silent=True) or {}
    amount = data.get("amount")
    phone = data.get("phone")

    if not amount or not phone:
        return jsonify({"error": "amount and phone are required"}), 400

    try:
        amount_cents = int(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be an integer (cents)"}), 400

    if amount_cents < 100:
        return jsonify({"error": "Minimum amount is KES 1.00 (100 cents)"}), 400

    # Daraja expects whole KES; we store/track cents internally.
    amount_kes = cents_to_kes(amount_cents)
    if amount_kes < 1:
        return jsonify({"error": "Minimum amount is KES 1"}), 400

    user_uid = g.firebase_uid
    callback_url = request.url_root.rstrip("/") + "/api/daraja/callback"

    result = stk_push(phone, amount_kes, account_ref="BradPay", callback_url=callback_url)

    if "error" in result:
        logger.error(f"STK Push failed for {user_uid}: {result['error']}")
        return jsonify({"error": result["error"]}), 502

    checkout_id = result.get("CheckoutRequestID")
    if checkout_id:
        create_mpesa_transaction(
            user_uid=user_uid,
            type_="deposit",
            phone=phone,
            amount=amount_cents,
            checkout_id=checkout_id,
        )

    return jsonify({
        "checkout_id": checkout_id,
        "message": "STK Push sent. Check your phone to complete payment.",
        "amount_cents": amount_cents,
        "amount_kes": amount_kes,
    })


@daraja_bp.route("/callback", methods=["POST"])
@require_safaricom_ip
def callback():
    data = request.get_json(silent=True) or {}
    logger.info(f"STK Push callback: {data}")

    try:
        stk = data.get("Body", {}).get("stkCallback", {})
        checkout_id = stk.get("CheckoutRequestID")
        result_code = stk.get("ResultCode")
        result_desc = stk.get("ResultDesc")

        if not checkout_id:
            return jsonify({"ResultCode": 1, "ResultDesc": "Missing CheckoutRequestID"})

        tx, claimed = _claim_callback(checkout_id, result_code, result_desc)
        if not claimed:
            # Already processed or unknown — acknowledge to stop retries.
            return jsonify({"ResultCode": 0, "ResultDesc": "Already processed"})

        if result_code == 0:
            metadata = stk.get("CallbackMetadata", {}).get("Item", [])
            paid_kes = None
            for item in metadata:
                if item.get("Name") == "Amount":
                    paid_kes = item.get("Value")
                    break
            # Prefer actual amount paid (KES whole); fall back to stored cents.
            if paid_kes is not None:
                credit_cents = kes_to_cents(paid_kes)
            else:
                credit_cents = int(tx.get("amount") or 0)
            if credit_cents > 0:
                update_kes_balance(tx["user_uid"], credit_cents)

        return jsonify({"ResultCode": 0, "ResultDesc": "Success"})
    except Exception as e:
        logger.error(f"Callback processing error: {e}")
        return jsonify({"ResultCode": 1, "ResultDesc": str(e)})


@daraja_bp.route("/b2c", methods=["POST"])
@require_auth
@require_user
def b2c_withdrawal():
    data = request.get_json(silent=True) or {}
    amount = data.get("amount")
    phone = data.get("phone")

    if not amount or not phone:
        return jsonify({"error": "amount and phone are required"}), 400

    try:
        amount_cents = int(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be an integer (cents)"}), 400

    if amount_cents < 100:
        return jsonify({"error": "Minimum amount is KES 1.00 (100 cents)"}), 400

    amount_kes = cents_to_kes(amount_cents)
    if amount_kes < 1:
        return jsonify({"error": "Minimum amount is KES 1"}), 400

    user_uid = g.firebase_uid
    kes_balance = get_kes_balance(user_uid)

    if kes_balance is None or kes_balance < amount_cents:
        return jsonify({"error": "Insufficient KES balance"}), 400

    # Debit first (atomic). Refund on Daraja failure or failed callback.
    if not update_kes_balance(user_uid, -amount_cents):
        return jsonify({"error": "Insufficient KES balance"}), 400

    root = request.url_root.rstrip("/")
    callback_url = root + "/api/daraja/b2c_callback"
    timeout_url = root + "/api/daraja/b2c_timeout"

    result = b2c(
        phone, amount_kes,
        remarks="Withdrawal from BradPay",
        callback_url=callback_url,
        timeout_url=timeout_url,
    )

    if "error" in result:
        update_kes_balance(user_uid, amount_cents)  # refund
        logger.error(f"B2C failed for {user_uid}: {result['error']}")
        return jsonify({"error": result["error"]}), 502

    conversation_id = result.get("ConversationID")
    if conversation_id:
        create_mpesa_transaction(
            user_uid=user_uid,
            type_="withdrawal",
            phone=phone,
            amount=amount_cents,
            conversation_id=conversation_id,
        )
    else:
        # No conversation id — cannot track callback; refund to be safe.
        update_kes_balance(user_uid, amount_cents)
        return jsonify({"error": "Withdrawal accepted but missing ConversationID"}), 502

    return jsonify({
        "conversation_id": conversation_id,
        "message": "Withdrawal initiated. Funds will be sent to your M-PESA.",
        "amount_cents": amount_cents,
        "amount_kes": amount_kes,
    })


@daraja_bp.route("/b2c_callback", methods=["POST"])
@require_safaricom_ip
def b2c_callback():
    data = request.get_json(silent=True) or {}
    logger.info(f"B2C callback: {data}")

    try:
        result = data.get("Result", {})
        conversation_id = result.get("ConversationID")
        result_code = result.get("ResultCode")
        result_desc = result.get("ResultDesc")

        if not conversation_id:
            return jsonify({"ResultCode": 1, "ResultDesc": "Missing ConversationID"})

        tx, claimed = _claim_callback(conversation_id, result_code, result_desc)
        if not claimed:
            return jsonify({"ResultCode": 0, "ResultDesc": "Already processed"})

        if result_code != 0:
            # Failed payout — refund once (claim guarantees single refund).
            if tx:
                update_kes_balance(tx["user_uid"], int(tx["amount"]))

        return jsonify({"ResultCode": 0, "ResultDesc": "Success"})
    except Exception as e:
        logger.error(f"B2C callback error: {e}")
        return jsonify({"ResultCode": 1, "ResultDesc": str(e)})


@daraja_bp.route("/b2c_timeout", methods=["POST"])
@require_safaricom_ip
def b2c_timeout():
    data = request.get_json(silent=True) or {}
    logger.warning(f"B2C timeout: {data}")

    try:
        result = data.get("Result", data)
        conversation_id = result.get("ConversationID") or data.get("ConversationID")
        if conversation_id:
            tx, claimed = _claim_callback(conversation_id, 1, "Timeout")
            if claimed and tx:
                update_kes_balance(tx["user_uid"], int(tx["amount"]))
        return jsonify({"ResultCode": 0, "ResultDesc": "Success"})
    except Exception as e:
        logger.error(f"B2C timeout error: {e}")
        return jsonify({"ResultCode": 0, "ResultDesc": "Success"})


@daraja_bp.route("/transactions", methods=["GET"])
@require_auth
@require_user
def mpesa_transactions():
    user_uid = g.firebase_uid
    txs = get_mpesa_transactions(user_uid)
    return jsonify({"transactions": txs})


@daraja_bp.route("/balance", methods=["GET"])
@require_auth
@require_user
def balance():
    user_uid = g.firebase_uid
    kes_balance = get_kes_balance(user_uid)
    return jsonify({"kes_balance": kes_balance or 0, "balance": kes_balance or 0})
