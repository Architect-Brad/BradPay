from flask import Blueprint, request, jsonify, g
import logging

from routes.auth_routes import require_auth, require_user
from daraja import stk_push, b2c, query_status
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


@daraja_bp.route("/stkpush", methods=["POST"])
@require_auth
@require_user
def stkpush():
    data = request.get_json(silent=True) or {}
    amount = data.get("amount")
    phone = data.get("phone")

    if not amount or not phone:
        return jsonify({"error": "amount and phone are required"}), 400

    if amount < 100:
        return jsonify({"error": "Minimum amount is KES 1.00 (100 cents)"}), 400

    user_uid = g.firebase_uid
    callback_url = request.url_root.rstrip("/") + "/api/daraja/callback"

    result = stk_push(phone, amount, account_ref="BradPay", callback_url=callback_url)

    if "error" in result:
        logger.error(f"STK Push failed for {user_uid}: {result['error']}")
        return jsonify({"error": result["error"]}), 502

    checkout_id = result.get("CheckoutRequestID")
    if checkout_id:
        create_mpesa_transaction(
            user_uid=user_uid,
            type="deposit",
            phone=phone,
            amount=amount,
            checkout_id=checkout_id,
        )

    return jsonify({
        "checkout_id": checkout_id,
        "message": "STK Push sent. Check your phone to complete payment.",
    })


@daraja_bp.route("/callback", methods=["POST"])
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

        update_mpesa_transaction_status(checkout_id, result_code, result_desc)

        if result_code == 0:
            metadata = stk.get("CallbackMetadata", {}).get("Item", [])
            amount = None
            for item in metadata:
                if item.get("Name") == "Amount":
                    amount = item.get("Value")
                    break
            if amount:
                tx = get_mpesa_transaction_by_checkout_id(checkout_id)
                if tx:
                    update_kes_balance(tx["user_uid"], amount)

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

    if amount < 100:
        return jsonify({"error": "Minimum amount is KES 1.00 (100 cents)"}), 400

    user_uid = g.firebase_uid
    kes_balance = get_kes_balance(user_uid)

    if kes_balance is None or kes_balance < amount:
        return jsonify({"error": "Insufficient KES balance"}), 400

    root = request.url_root.rstrip("/")
    callback_url = root + "/api/daraja/b2c_callback"
    timeout_url = root + "/api/daraja/b2c_timeout"

    result = b2c(
        phone, amount,
        remarks="Withdrawal from BradPay",
        callback_url=callback_url,
        timeout_url=timeout_url,
    )

    if "error" in result:
        logger.error(f"B2C failed for {user_uid}: {result['error']}")
        return jsonify({"error": result["error"]}), 502

    conversation_id = result.get("ConversationID")
    update_kes_balance(user_uid, -amount)

    if conversation_id:
        create_mpesa_transaction(
            user_uid=user_uid,
            type="withdrawal",
            phone=phone,
            amount=amount,
            conversation_id=conversation_id,
        )

    return jsonify({
        "conversation_id": conversation_id,
        "message": "Withdrawal initiated. Funds will be sent to your M-PESA.",
    })


@daraja_bp.route("/b2c_callback", methods=["POST"])
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

        update_mpesa_transaction_status(conversation_id, result_code, result_desc)

        if result_code != 0:
            tx = get_mpesa_transaction_by_conversation_id(conversation_id)
            if tx:
                update_kes_balance(tx["user_uid"], tx["amount"])

        return jsonify({"ResultCode": 0, "ResultDesc": "Success"})
    except Exception as e:
        logger.error(f"B2C callback error: {e}")
        return jsonify({"ResultCode": 1, "ResultDesc": str(e)})


@daraja_bp.route("/b2c_timeout", methods=["POST"])
def b2c_timeout():
    data = request.get_json(silent=True) or {}
    logger.warning(f"B2C timeout: {data}")
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
    return jsonify({"kes_balance": kes_balance or 0})
