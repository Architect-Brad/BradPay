from flask import Blueprint, request, jsonify
import logging

from data import (
    get_active_tariffs,
    get_tariff_by_type,
    create_tariff,
    update_tariff,
)

logger = logging.getLogger(__name__)
tariff_bp = Blueprint("tariffs", __name__, url_prefix="/api/tariffs")


@tariff_bp.route("", methods=["GET"])
def list_tariffs():
    tariffs = get_active_tariffs()
    return jsonify({"tariffs": tariffs})


@tariff_bp.route("/<type_>", methods=["GET"])
def tariffs_by_type(type_):
    valid = ("transfer", "deposit", "withdrawal", "agent_commission", "float_topup")
    if type_ not in valid:
        return jsonify({"error": f"Invalid type. Must be one of: {', '.join(valid)}"}), 400
    tariffs = get_tariff_by_type(type_)
    return jsonify({"tariffs": tariffs})


@tariff_bp.route("", methods=["POST"])
def create():
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    type_ = data.get("type")
    if not name or not type_:
        return jsonify({"error": "name and type are required"}), 400
    tariff = create_tariff(
        name=name,
        type_=type_,
        percentage=data.get("percentage"),
        flat_fee=data.get("flat_fee"),
        min_amount=data.get("min_amount"),
        max_amount=data.get("max_amount"),
    )
    return jsonify({"tariff": tariff}), 201


@tariff_bp.route("/<tariff_id>", methods=["PATCH"])
def update(tariff_id):
    data = request.get_json(silent=True) or {}
    allowed = ("name", "type", "percentage", "flat_fee", "min_amount", "max_amount", "is_active")
    kwargs = {k: v for k, v in data.items() if k in allowed}
    if not kwargs:
        return jsonify({"error": "No valid fields to update"}), 400
    if "is_active" in kwargs:
        kwargs["is_active"] = bool(kwargs["is_active"])
    tariff = update_tariff(tariff_id, **kwargs)
    if not tariff:
        return jsonify({"error": "Tariff not found"}), 404
    return jsonify({"tariff": tariff})
