from flask import Blueprint, request, jsonify, g
import logging

from routes.auth_routes import require_auth, require_user
from data import (
    create_agent,
    get_agent,
    get_agent_by_id,
    update_agent_status,
    update_agent_float,
    get_all_agents,
    create_agent_transaction,
    get_agent_transactions,
    get_active_tariffs,
    get_tariff_by_type,
)

logger = logging.getLogger(__name__)
agent_bp = Blueprint("agents", __name__, url_prefix="/api/agents")


@agent_bp.route("/register", methods=["POST"])
@require_auth
@require_user
def register():
    data = request.get_json(silent=True) or {}
    business_name = data.get("business_name", "").strip()
    if not business_name:
        return jsonify({"error": "Business name is required"}), 400

    user_uid = g.firebase_uid
    existing = get_agent(user_uid)
    if existing:
        return jsonify({"error": "Already registered as an agent", "agent": existing}), 409

    agent = create_agent(
        firebase_uid=user_uid,
        business_name=business_name,
        contact_phone=data.get("contact_phone") or g.current_user.get("phone"),
        email=data.get("email") or g.firebase_user.get("email"),
        id_number=data.get("id_number"),
        kra_pin=data.get("kra_pin"),
        location=data.get("location"),
    )

    if "error" in agent:
        return jsonify(agent), 500

    return jsonify({"message": "Agent registration submitted for verification", "agent": agent}), 201


@agent_bp.route("/profile", methods=["GET"])
@require_auth
def profile():
    user_uid = g.firebase_uid
    agent = get_agent(user_uid)
    if not agent:
        return jsonify({"error": "Not registered as an agent"}), 404
    return jsonify({"agent": agent})


@agent_bp.route("/verify", methods=["POST"])
@require_auth
def verify():
    data = request.get_json(silent=True) or {}
    agent_uid = data.get("agent_uid")
    status = data.get("status", "active")

    if not agent_uid:
        return jsonify({"error": "agent_uid is required"}), 400
    if status not in ("active", "suspended", "rejected"):
        return jsonify({"error": "Invalid status"}), 400

    agent = get_agent(agent_uid)
    if not agent:
        return jsonify({"error": "Agent not found"}), 404

    update_agent_status(agent_uid, status)
    return jsonify({"message": f"Agent {status}", "agent_uid": agent_uid})


@agent_bp.route("/transactions", methods=["GET"])
@require_auth
def transactions():
    user_uid = g.firebase_uid
    agent = get_agent(user_uid)
    if not agent:
        return jsonify({"error": "Not an agent"}), 404
    txs = get_agent_transactions(agent["firebase_uid"])
    return jsonify({"transactions": txs})


@agent_bp.route("/all", methods=["GET"])
@require_auth
def all_agents():
    status = request.args.get("status")
    agents = get_all_agents(status)
    return jsonify({"agents": agents})


@agent_bp.route("/float-topup", methods=["POST"])
@require_auth
@require_user
def float_topup():
    data = request.get_json(silent=True) or {}
    amount = data.get("amount")
    if not amount or amount < 1:
        return jsonify({"error": "Invalid amount"}), 400

    user_uid = g.firebase_uid
    agent = get_agent(user_uid)
    if not agent:
        return jsonify({"error": "Not an agent"}), 404
    if agent["status"] != "active":
        return jsonify({"error": "Agent not active"}), 403

    kes_balance = g.current_user.get("kes_balance", 0)
    if kes_balance < amount:
        return jsonify({"error": "Insufficient KES balance"}), 400

    from data import update_kes_balance
    update_kes_balance(user_uid, -amount)
    update_agent_float(user_uid, amount)

    create_agent_transaction(user_uid, "float_topup", amount, reference=f"float_{user_uid[:8]}_{amount}")
    return jsonify({"message": "Float topped up", "amount": amount})


@agent_bp.route("/cash-in", methods=["POST"])
@require_auth
def cash_in():
    data = request.get_json(silent=True) or {}
    user_phone = data.get("phone")
    amount = data.get("amount")
    if not user_phone or not amount:
        return jsonify({"error": "phone and amount are required"}), 400

    agent_uid = g.firebase_uid
    agent = get_agent(agent_uid)
    if not agent or agent["status"] != "active":
        return jsonify({"error": "Agent not active"}), 403
    if agent.get("float_balance", 0) < amount:
        return jsonify({"error": "Insufficient float"}), 400

    from data import get_user_by_phone_or_email, update_kes_balance
    user = get_user_by_phone_or_email(user_phone)
    if not user:
        return jsonify({"error": "User not found"}), 404

    update_agent_float(agent_uid, -amount)
    update_kes_balance(user["firebase_uid"], amount)
    create_agent_transaction(agent_uid, "cash_in", amount, user_uid=user["firebase_uid"], reference=f"cashin_{user_phone}")

    tariffs = get_tariff_by_type("agent_commission")
    commission = 0
    for t in tariffs:
        if t.get("percentage") and (not t.get("min_amount") or amount >= t["min_amount"]):
            commission = int(amount * t["percentage"] / 10000)
            break
    if commission > 0:
        update_agent_float(agent_uid, commission)
        create_agent_transaction(agent_uid, "commission", commission, reference=f"comm_{agent_uid[:8]}_{amount}")

    return jsonify({"message": "Cash-in successful", "amount": amount})


@agent_bp.route("/cash-out", methods=["POST"])
@require_auth
def cash_out():
    data = request.get_json(silent=True) or {}
    user_phone = data.get("phone")
    amount = data.get("amount")
    if not user_phone or not amount:
        return jsonify({"error": "phone and amount are required"}), 400

    agent_uid = g.firebase_uid
    agent = get_agent(agent_uid)
    if not agent or agent["status"] != "active":
        return jsonify({"error": "Agent not active"}), 403

    from data import get_user_by_phone_or_email, update_kes_balance
    user = get_user_by_phone_or_email(user_phone)
    if not user:
        return jsonify({"error": "User not found"}), 404

    user_kes = user.get("kes_balance", 0)
    if user_kes < amount:
        return jsonify({"error": "User insufficient KES balance"}), 400

    update_kes_balance(user["firebase_uid"], -amount)
    update_agent_float(agent_uid, amount)
    create_agent_transaction(agent_uid, "cash_out", amount, user_uid=user["firebase_uid"], reference=f"cashout_{user_phone}")
    return jsonify({"message": "Cash-out successful", "amount": amount})
