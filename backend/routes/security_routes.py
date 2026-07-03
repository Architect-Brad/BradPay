from flask import Blueprint, request, jsonify, g, current_app
import logging

from routes.auth_routes import require_auth, require_user
from routes.admin_routes import require_admin
from bradsec import (
    log_event, get_events, count_events,
    check_rate_limit, get_rate_limit_remaining,
    evaluate_transaction, get_flagged_transactions,
    resolve_flag, get_flag_stats, get_security_summary,
    get_settings, update_settings,
)

logger = logging.getLogger(__name__)
security_bp = Blueprint("security", __name__, url_prefix="/api/security")


@security_bp.route("/events", methods=["GET"])
@require_auth
def list_events():
    uid = g.firebase_uid
    event_type = request.args.get("type")
    severity = request.args.get("severity")
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    events = get_events(uid=uid, event_type=event_type, severity=severity, limit=limit, offset=offset)
    total = count_events(uid=uid, event_type=event_type, severity=severity)
    return jsonify({"events": events, "total": total})


@security_bp.route("/events/count", methods=["GET"])
@require_auth
def event_count():
    uid = g.firebase_uid
    severity = request.args.get("severity")
    since = request.args.get("since")
    total = count_events(uid=uid, severity=severity, since=since)
    return jsonify({"count": total})


@security_bp.route("/evaluate", methods=["POST"])
@require_auth
@require_user
def evaluate():
    data = request.get_json(silent=True) or {}
    recipient_uid = data.get("recipient_uid")
    amount = data.get("amount")
    tx_ref = data.get("tx_ref")

    if not recipient_uid or not amount:
        return jsonify({"error": "recipient_uid and amount are required"}), 400
    try:
        amount = int(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a positive integer"}), 400

    result = evaluate_transaction(g.firebase_uid, recipient_uid, amount, tx_ref)
    return jsonify(result)


@security_bp.route("/rate-limit", methods=["GET"])
@require_auth
def rate_limit_status():
    uid = g.firebase_uid
    action = request.args.get("action")
    if action:
        remaining = get_rate_limit_remaining(uid, action)
        return jsonify({"action": action, "remaining": remaining})
    # return all
    from bradsec import RATE_LIMITS
    statuses = {}
    for act in RATE_LIMITS:
        statuses[act] = get_rate_limit_remaining(uid, act)
    return jsonify({"limits": statuses})


# ── Settings ──

@security_bp.route("/settings", methods=["GET"])
@require_admin
def list_settings():
    return jsonify(get_settings())


@security_bp.route("/settings", methods=["POST"])
@require_admin
def save_settings():
    data = request.get_json(silent=True) or {}
    allowed = {"auto_block_enabled": bool, "auto_block_threshold": int}
    overrides = {}
    for key, typ in allowed.items():
        val = data.get(key)
        if val is not None:
            try:
                overrides[key] = typ(val)
            except (ValueError, TypeError):
                return jsonify({"error": f"Invalid type for {key}"}), 400
    result = update_settings(overrides)
    return jsonify({"message": "Settings updated", "settings": result})


# ── Admin endpoints ──

@security_bp.route("/flags", methods=["GET"])
@require_admin
def list_flags():
    status = request.args.get("status")
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    flags = get_flagged_transactions(status=status, limit=limit, offset=offset)
    stats = get_flag_stats()
    return jsonify({"flags": flags, "stats": stats})


@security_bp.route("/flags/<int:flag_id>/resolve", methods=["POST"])
@require_admin
def handle_resolve(flag_id):
    data = request.get_json(silent=True) or {}
    resolution = data.get("resolution")
    if resolution not in ("approved", "blocked"):
        return jsonify({"error": "resolution must be 'approved' or 'blocked'"}), 400
    note = data.get("note", "")
    result = resolve_flag(flag_id, "admin", resolution, note)
    if not result:
        return jsonify({"error": "Flag not found"}), 404
    return jsonify({"message": f"Flag {resolution}", "flag": result})


@security_bp.route("/dashboard", methods=["GET"])
@require_admin
def admin_dashboard():
    limit = int(request.args.get("limit", 20))
    summary = get_security_summary()
    events = get_events(severity="high", limit=limit) if summary["high_severity_24h"] > 0 else get_events(limit=limit)
    flags = get_flagged_transactions(status="open", limit=10)
    return jsonify({
        "summary": summary,
        "recent_events": events,
        "open_flags": flags,
    })
