from flask import Blueprint, request, jsonify, g
import logging

from routes.auth_routes import require_auth, require_user
from routes.admin_routes import require_admin
from data import (
    create_agent,
    get_agent,
    get_agent_by_id,
    update_agent_status,
    get_all_agents,
    get_agent_transactions,
)

logger = logging.getLogger(__name__)
agent_bp = Blueprint("agents", __name__, url_prefix="/api/agents")


def _result_or_error(result):
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    if isinstance(result, dict) and "error" in result and "message" not in result:
        return jsonify(result), 400
    return jsonify(result)


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

    if isinstance(agent, dict) and "error" in agent:
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
@require_admin
def verify():
    """Admin-only: activate / suspend / reject an agent."""
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
@require_admin
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
    try:
        amount = int(amount)
        if amount < 1:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid amount"}), 400

    from data import agent_float_topup
    return _result_or_error(agent_float_topup(g.firebase_uid, amount))


@agent_bp.route("/float/transfer", methods=["POST"])
@require_auth
@require_user
def float_transfer():
    data = request.get_json(silent=True) or {}
    to_agent_uid = data.get("to_agent_uid")
    amount = data.get("amount")
    if not to_agent_uid or amount is None:
        return jsonify({"error": "to_agent_uid and amount are required"}), 400
    try:
        amount = int(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a positive integer"}), 400

    from data import agent_float_transfer
    return _result_or_error(agent_float_transfer(g.firebase_uid, to_agent_uid, amount))


@agent_bp.route("/cash-in", methods=["POST"])
@require_auth
def cash_in():
    data = request.get_json(silent=True) or {}
    user_phone = data.get("phone")
    amount = data.get("amount")
    if not user_phone or amount is None:
        return jsonify({"error": "phone and amount are required"}), 400
    try:
        amount = int(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a positive integer"}), 400

    from data import agent_cash_in
    return _result_or_error(agent_cash_in(g.firebase_uid, user_phone, amount))


@agent_bp.route("/cash-out", methods=["POST"])
@require_auth
def cash_out():
    data = request.get_json(silent=True) or {}
    user_phone = data.get("phone")
    amount = data.get("amount")
    if not user_phone or amount is None:
        return jsonify({"error": "phone and amount are required"}), 400
    try:
        amount = int(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a positive integer"}), 400

    from data import agent_cash_out
    return _result_or_error(agent_cash_out(g.firebase_uid, user_phone, amount))
