import os
import json
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash

_db = None
_firestore_module = None


def get_firestore():
    global _db, _firestore_module
    if _db is None:
        import firebase_admin
        from firebase_admin import credentials
        import google.cloud.firestore as fs

        _firestore_module = fs

        service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        if service_account_json:
            cred = credentials.Certificate(json.loads(service_account_json))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()

        _db = fs.Client()
    return _db


def _inc(amount):
    return _firestore_module.Increment(amount)


def _desc():
    return _firestore_module.Query.DESCENDING


def init_db():
    pass


def _user_ref(uid):
    return get_firestore().collection("users").document(uid)


def _tx_collection():
    return get_firestore().collection("transactions")


def create_user(firebase_uid, email=None, display_name=None, phone=None, pin="1234"):
    ref = _user_ref(firebase_uid)
    if ref.get().exists:
        return None

    pin_hash = generate_password_hash(pin)
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "firebase_uid": firebase_uid,
        "email": email or "",
        "display_name": display_name or "",
        "phone": phone or "",
        "pin_hash": pin_hash,
        "balance": 0,
        "locked_balance": 0,
        "created_at": now,
        "updated_at": now,
    }
    ref.set(data)
    data["id"] = firebase_uid
    return data


def get_user_by_firebase_uid(firebase_uid):
    doc = _user_ref(firebase_uid).get()
    if not doc.exists:
        return None
    user = doc.to_dict()
    user["id"] = firebase_uid
    return user


def get_user_by_id(user_id):
    return get_user_by_firebase_uid(user_id)


def verify_pin(user_id, pin):
    user = get_user_by_firebase_uid(user_id)
    if not user:
        return False
    return check_password_hash(user["pin_hash"], pin)


def get_balance(user_id):
    user = get_user_by_firebase_uid(user_id)
    return user["balance"] if user else None


def create_transaction(sender_uid, recipient_uid, amount, note=None, offline_id=None):
    sender = get_user_by_firebase_uid(sender_uid)
    if not sender:
        return {"error": "Sender not found"}, 404

    recipient = get_user_by_firebase_uid(recipient_uid)
    if not recipient:
        return {"error": "Recipient not found"}, 404

    if sender["balance"] < amount:
        return {"error": "Insufficient balance"}, 400

    tx_ref = f"BRADPAY-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{sender_uid[:8]}-{recipient_uid[:8]}"

    tx_data = {
        "tx_ref": tx_ref,
        "sender_uid": sender_uid,
        "recipient_uid": recipient_uid,
        "sender_name": sender.get("display_name", ""),
        "recipient_name": recipient.get("display_name", ""),
        "amount": amount,
        "fee": 0,
        "type": "transfer",
        "status": "completed",
        "note": note or "",
        "offline_id": offline_id or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    db = get_firestore()
    db.collection("users").document(sender_uid).update({
        "balance": _inc(-amount),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    db.collection("users").document(recipient_uid).update({
        "balance": _inc(amount),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    _tx_collection().add(tx_data)
    return tx_data


def get_transactions(user_id, limit=50):
    db = get_firestore()
    docs = (
        db.collection("transactions")
        .where("sender_uid", "==", user_id)
        .order_by("created_at", direction=_desc())
        .limit(limit)
        .stream()
    )
    txs = [{"id": d.id, **d.to_dict()} for d in docs]

    docs2 = (
        db.collection("transactions")
        .where("recipient_uid", "==", user_id)
        .order_by("created_at", direction=_desc())
        .limit(limit)
        .stream()
    )
    for d in docs2:
        txs.append({"id": d.id, **d.to_dict()})

    txs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return txs[:limit]


def get_user_by_phone_or_email(identifier):
    db = get_firestore()
    if "@" in identifier:
        docs = db.collection("users").where("email", "==", identifier).limit(1).stream()
    else:
        docs = db.collection("users").where("phone", "==", identifier).limit(1).stream()
    for d in docs:
        user = d.to_dict()
        user["id"] = d.id
        return user
    return None


# ── BradTrade ──

def _orders_collection():
    return get_firestore().collection("orders")


def _trades_collection():
    return get_firestore().collection("trades")


def create_order(user_uid, order_type, price, amount):
    db = get_firestore()
    user_ref = _user_ref(user_uid)
    user_doc = user_ref.get()
    if not user_doc.exists:
        return {"error": "User not found"}, 404
    user = user_doc.to_dict()

    if order_type == "sell":
        available = user.get("balance", 0) - user.get("locked_balance", 0)
        if available < amount:
            return {"error": "Insufficient available balance"}, 400
        user_ref.update({"locked_balance": _inc(amount)})

    now = datetime.now(timezone.utc).isoformat()
    order_data = {
        "user_uid": user_uid,
        "type": order_type,
        "price": price,
        "amount": amount,
        "filled": 0,
        "status": "open",
        "created_at": now,
    }
    _, ref = _orders_collection().add(order_data)
    order_data["id"] = ref.id
    return order_data


def cancel_order(user_uid, order_id):
    db = get_firestore()
    ref = _orders_collection().document(order_id)
    doc = ref.get()
    if not doc.exists:
        return {"error": "Order not found"}, 404
    order = doc.to_dict()
    if order["user_uid"] != user_uid:
        return {"error": "Not your order"}, 403
    if order["status"] not in ("open", "partial"):
        return {"error": "Order cannot be cancelled"}, 400

    remaining = order["amount"] - order["filled"]
    if order["type"] == "sell" and remaining > 0:
        _user_ref(user_uid).update({"locked_balance": _inc(-remaining)})

    ref.update({"status": "cancelled"})
    return {"message": "Order cancelled", "order_id": order_id}


def get_orders(user_uid, status_filter=None):
    db = get_firestore()
    query = _orders_collection().where("user_uid", "==", user_uid)
    if status_filter:
        query = query.where("status", "==", status_filter)
    query = query.order_by("created_at", direction=_desc())
    docs = query.stream()
    return [{"id": d.id, **d.to_dict()} for d in docs]


def get_order_book(limit=15):
    db = get_firestore()
    buy_docs = (
        _orders_collection()
        .where("type", "==", "buy")
        .where("status", "in", ["open", "partial"])
        .order_by("price", direction=_desc())
        .order_by("created_at")
        .limit(limit)
        .stream()
    )
    sell_docs = (
        _orders_collection()
        .where("type", "==", "sell")
        .where("status", "in", ["open", "partial"])
        .order_by("price")
        .order_by("created_at")
        .limit(limit)
        .stream()
    )

    buy_agg = {}
    for d in buy_docs:
        o = d.to_dict()
        p = o["price"]
        remaining = o["amount"] - o.get("filled", 0)
        if p in buy_agg:
            buy_agg[p]["amount"] += remaining
            buy_agg[p]["count"] += 1
        else:
            buy_agg[p] = {"price": p, "amount": remaining, "count": 1}

    sell_agg = {}
    for d in sell_docs:
        o = d.to_dict()
        p = o["price"]
        remaining = o["amount"] - o.get("filled", 0)
        if p in sell_agg:
            sell_agg[p]["amount"] += remaining
            sell_agg[p]["count"] += 1
        else:
            sell_agg[p] = {"price": p, "amount": remaining, "count": 1}

    return {
        "bids": sorted(buy_agg.values(), key=lambda x: -x["price"]),
        "asks": sorted(sell_agg.values(), key=lambda x: x["price"]),
    }


def execute_trade(buy_order_id, sell_order_id, buyer_uid, seller_uid, amount, price):
    db = get_firestore()
    try:
        buyer_fee = max(1, amount // 1000)
        seller_fee = max(1, amount // 1000)
        seller_payout = amount - seller_fee

        db.collection("users").document(buyer_uid).update({
            "balance": _inc(amount - buyer_fee),
        })
        db.collection("users").document(seller_uid).update({
            "balance": _inc(-amount),
            "locked_balance": _inc(-amount),
        })

        now = datetime.now(timezone.utc).isoformat()
        _trades_collection().add({
            "buy_order_id": buy_order_id,
            "sell_order_id": sell_order_id,
            "buyer_uid": buyer_uid,
            "seller_uid": seller_uid,
            "amount": amount,
            "price": price,
            "buyer_fee": buyer_fee,
            "seller_fee": seller_fee,
            "created_at": now,
        })

        for oid, otype in [(buy_order_id, "buy"), (sell_order_id, "sell")]:
            oref = db.collection("orders").document(oid)
            oref.update({
                "filled": _inc(amount),
            })
            odoc = oref.get()
            if odoc.exists:
                o = odoc.to_dict()
                if o.get("filled", 0) >= o.get("amount", 0):
                    oref.update({"status": "filled"})
                elif o.get("filled", 0) > 0:
                    oref.update({"status": "partial"})

        return {"success": True, "amount": amount, "price": price}
    except Exception as e:
        return {"error": str(e), "success": False}


def get_trades(user_uid=None, limit=50):
    db = get_firestore()
    try:
        if user_uid:
            bdocs = (
                _trades_collection()
                .where("buyer_uid", "==", user_uid)
                .order_by("created_at", direction=_desc())
                .limit(limit)
                .stream()
            )
            sdocs = (
                _trades_collection()
                .where("seller_uid", "==", user_uid)
                .order_by("created_at", direction=_desc())
                .limit(limit)
                .stream()
            )
            trades = [{"id": d.id, **d.to_dict()} for d in bdocs]
            trades += [{"id": d.id, **d.to_dict()} for d in sdocs]
            trades.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return trades[:limit]
        else:
            docs = (
                _trades_collection()
                .order_by("created_at", direction=_desc())
                .limit(limit)
                .stream()
            )
            return [{"id": d.id, **d.to_dict()} for d in docs]
    except Exception:
        return []


def get_user_with_locked(firebase_uid):
    return get_user_by_firebase_uid(firebase_uid)
