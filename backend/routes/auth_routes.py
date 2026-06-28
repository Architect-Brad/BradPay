from flask import Blueprint, request, jsonify, g
from functools import wraps
from firebase_verify import verify_firebase_token
from data import create_user, get_user_by_firebase_uid, get_user_by_id

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
        return jsonify({"error": result["error"]}), 401

    user = get_user_by_firebase_uid(result["uid"])
    return jsonify({
        "valid": True,
        "uid": result["uid"],
        "email": result.get("email"),
        "name": result.get("name"),
        "registered": user is not None,
        "user": user,
    })


@auth_bp.route("/register", methods=["POST"])
@require_auth
def register():
    data = request.get_json(silent=True) or {}
    pin = data.get("pin", "1234")

    if len(str(pin)) < 4:
        return jsonify({"error": "PIN must be at least 4 digits"}), 400

    existing = get_user_by_firebase_uid(g.firebase_uid)
    if existing:
        return jsonify({"error": "User already registered", "user": existing}), 409

    user = create_user(
        firebase_uid=g.firebase_uid,
        email=g.firebase_user.get("email"),
        display_name=data.get("displayName") or g.firebase_user.get("name"),
        phone=data.get("phone"),
        pin=pin,
    )

    if not user:
        return jsonify({"error": "Registration failed"}), 500

    return jsonify({"message": "Registration successful", "user": user}), 201


@auth_bp.route("/me", methods=["GET"])
@require_auth
@require_user
def me():
    return jsonify({"user": g.current_user})
