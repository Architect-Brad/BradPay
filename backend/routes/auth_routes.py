from flask import Blueprint, request, jsonify, g
from functools import wraps
from firebase_verify import verify_firebase_token
from data import create_user, get_user_by_firebase_uid, get_user_by_id
from bradsec import log_event, check_rate_limit

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401

        token = auth_header.split(" ", 1)[1]
        result = verify_firebase_token(token)
        if not result["valid"]:
            return jsonify({"error": result["error"]}), 401

        g.firebase_uid = result["uid"]
        g.firebase_user = result
        return f(*args, **kwargs)
    return decorated


def require_user(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_user_by_firebase_uid(g.firebase_uid)
        if not user:
            return jsonify({"error": "User not found. Please register."}), 404
        g.current_user = user
        return f(*args, **kwargs)
    return decorated


@auth_bp.route("/verify", methods=["POST"])
def verify():
    data = request.get_json(silent=True) or {}
    token = data.get("idToken")
    if not token:
        return jsonify({"error": "idToken is required"}), 400

    result = verify_firebase_token(token)
    if not result["valid"]:
        log_event("login_failure", "low", details={"reason": result.get("error", "Invalid token")})
        return jsonify({"error": result["error"]}), 401

    uid = result["uid"]
    if not check_rate_limit(uid, "login"):
        log_event("rate_limit_hit", "medium", uid, {"action": "login"})
        return jsonify({"error": "Too many login attempts. Try again later."}), 429

    user = get_user_by_firebase_uid(uid)
    log_event("login_success", "info", uid, {"registered": user is not None})
    return jsonify({
        "valid": True,
        "uid": uid,
        "email": result.get("email"),
        "name": result.get("name"),
        "registered": user is not None,
        "user": user,
    })


@auth_bp.route("/register", methods=["POST"])
@require_auth
def register():
    data = request.get_json(silent=True) or {}
    pin = data.get("pin")

    if pin is None:
        return jsonify({"error": "PIN is required"}), 400

    existing = get_user_by_firebase_uid(g.firebase_uid)
    if existing:
        return jsonify({"error": "User already registered", "user": existing}), 409

    try:
        user = create_user(
            firebase_uid=g.firebase_uid,
            email=g.firebase_user.get("email"),
            display_name=data.get("displayName") or g.firebase_user.get("name"),
            phone=data.get("phone"),
            pin=pin,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not user:
        return jsonify({"error": "Registration failed"}), 500

    log_event("registration", "info", g.firebase_uid, {"display_name": user.get("display_name")})
    return jsonify({"message": "Registration successful", "user": user}), 201


@auth_bp.route("/me", methods=["GET"])
@require_auth
@require_user
def me():
    return jsonify({"user": g.current_user})
