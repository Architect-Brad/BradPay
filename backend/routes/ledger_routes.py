from flask import Blueprint, request, jsonify
from routes.auth_routes import require_auth, require_user
from ledger import get_ledger

ledger_bp = Blueprint("ledger", __name__, url_prefix="/api/ledger")


@ledger_bp.route("/chain", methods=["GET"])
def get_chain():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 10, type=int)
    per_page = min(per_page, 50)
    ledger = get_ledger()

    start = max(0, len(ledger.chain) - page * per_page)
    end = max(0, len(ledger.chain) - (page - 1) * per_page)

    chain_slice = ledger.chain[start:end] if start < end else []
    return jsonify({
        "chain": chain_slice,
        "length": len(ledger.chain),
        "pending": len(ledger.pending_transactions),
        "difficulty": ledger.difficulty,
        "page": page,
        "per_page": per_page,
        "valid": ledger.validate(),
    })


@ledger_bp.route("/block/<int:index>", methods=["GET"])
def get_block(index):
    ledger = get_ledger()
    block = ledger.get_block(index)
    if not block:
        return jsonify({"error": "Block not found"}), 404
    return jsonify({"block": block})


@ledger_bp.route("/proof/<tx_ref>", methods=["GET"])
@require_auth
def get_proof(tx_ref):
    ledger = get_ledger()
    proof = ledger.get_transaction_proof(tx_ref)
    if not proof:
        return jsonify({"error": "Transaction not found on ledger"}), 404
    return jsonify({"proof": proof})


@ledger_bp.route("/mine", methods=["POST"])
@require_auth
@require_user
def force_mine():
    ledger = get_ledger()
    block = ledger.force_mine()
    if block:
        return jsonify({"message": "Block mined", "block": block}), 201
    return jsonify({"message": "No pending transactions to mine"}), 200


@ledger_bp.route("/status", methods=["GET"])
def status():
    ledger = get_ledger()
    return jsonify({
        "blocks": len(ledger.chain),
        "pending_transactions": len(ledger.pending_transactions),
        "difficulty": ledger.difficulty,
        "valid": ledger.validate(),
        "last_block_hash": ledger.chain[-1]["hash"] if ledger.chain else None,
    })
