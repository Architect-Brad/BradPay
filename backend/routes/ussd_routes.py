from flask import Blueprint, request, jsonify
from ussd import handle_ussd

ussd_bp = Blueprint("ussd", __name__, url_prefix="/api/ussd")


@ussd_bp.route("/callback", methods=["POST"])
def callback():
    data = request.get_json(silent=True) or request.form.to_dict()
    session_id = data.get("sessionId")
    phone = data.get("phoneNumber", "")
    text = data.get("text", "")

    result = handle_ussd(session_id, phone, text)
    return jsonify(result)
