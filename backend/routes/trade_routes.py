from flask import Blueprint, request, jsonify, g
from routes.auth_routes import require_auth, require_user
from data import (
    create_order,
    cancel_order,
    get_orders,
    get_order_book,
    get_trades,
    get_user_with_locked,
)
from trade_engine import match_orders

trade_bp = Blueprint("trade", __name__, url_prefix="/api/trade")


@trade_bp.route("/orderbook", methods=["GET"])
def orderbook():
    book = get_order_book(limit=25)
    return jsonify(book)


@trade_bp.route("/orders", methods=["GET"])
@require_auth
@require_user
def list_orders():
    status_filter = request.args.get("status")
    orders = get_orders(g.firebase_uid, status_filter)
    return jsonify({"orders": orders})


@trade_bp.route("/orders", methods=["POST"])
@require_auth
@require_user
def place_order():
    data = request.get_json(silent=True) or {}
    order_type = data.get("type")
    price = data.get("price")
    amount = data.get("amount")

    if order_type not in ("buy", "sell"):
        return jsonify({"error": "Type must be 'buy' or 'sell'"}), 400

    try:
        price = int(price)
        amount = int(amount)
        if price <= 0 or amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid price or amount"}), 400

    result = create_order(g.firebase_uid, order_type, price, amount)
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 400

    trades = match_orders(result)

    return jsonify({
        "message": f"{order_type.capitalize()} order placed",
        "order": result,
        "trades": trades,
    }), 201


@trade_bp.route("/orders/<order_id>", methods=["DELETE"])
@require_auth
@require_user
def remove_order(order_id):
    result = cancel_order(g.firebase_uid, order_id)
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@trade_bp.route("/trades", methods=["GET"])
@require_auth
@require_user
def trade_history():
    trades = get_trades(g.firebase_uid, limit=50)
    return jsonify({"trades": trades})


@trade_bp.route("/balance", methods=["GET"])
@require_auth
@require_user
def trade_balance():
    user = get_user_with_locked(g.firebase_uid)
    if not user:
        return jsonify({"error": "User not found"}), 404
    total = user.get("balance", 0)
    locked = user.get("locked_balance", 0)
    return jsonify({
        "total": total,
        "locked": locked,
        "available": total - locked,
    })


@trade_bp.route("/recent", methods=["GET"])
def recent_trades():
    trades = get_trades(limit=30)
    return jsonify({"trades": trades})
