import os
import json
import time
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash

_db = None
_firestore_module = None


def get_firestore():
    global _db, _firestore_module
    if _db is None:
        import firebase_admin
        from firebase_admin import credentials
        from firebase_admin import firestore as fs

        _firestore_module = fs

        service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        if service_account_json:
            cred = credentials.Certificate(json.loads(service_account_json))
            try:
                firebase_admin.initialize_app(cred)
            except ValueError:
                pass
        else:
            try:
                firebase_admin.initialize_app()
            except ValueError:
                pass

        _db = fs.client()
    return _db


def _inc(amount):
    if _firestore_module:
        return _firestore_module.Increment(amount)
    from google.cloud.firestore_v1 import Increment
    return Increment(amount)


def _desc():
    if _firestore_module:
        return _firestore_module.Query.DESCENDING
    from google.cloud.firestore_v1 import Query
    return Query.DESCENDING


def init_db():
    pass


def init_bradsec():
    pass


def get_bradsec_settings():
    db = get_firestore()
    doc = db.collection("bradsec_settings").document("config").get()
    return doc.to_dict() if doc.exists else {}


def set_bradsec_settings(settings):
    db = get_firestore()
    db.collection("bradsec_settings").document("config").set(settings, merge=True)


def _user_ref(uid):
    return get_firestore().collection("users").document(uid)


def _tx_collection():
    return get_firestore().collection("transactions")


def create_user(firebase_uid, email=None, display_name=None, phone=None, pin=None):
    from validators import validate_pin
    pin = validate_pin(pin)
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
        "kes_balance": 0,
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


def calculate_fee(type_, amount):
    """Mirrors models.calculate_fee. percentage is basis points (100 = 1%)."""
    tiers = get_tariff_by_type(type_)
    for tier in tiers:
        min_amt = tier.get("min_amount") or 0
        max_amt = tier.get("max_amount")
        if amount < min_amt:
            continue
        if max_amt is not None and amount > max_amt:
            continue
        flat = tier.get("flat_fee") or 0
        pct = tier.get("percentage") or 0
        return flat + (amount * pct) // 10000
    return 0


def create_transaction(sender_uid, recipient_uid, amount, note=None, offline_id=None):
    if amount is None or amount <= 0:
        return {"error": "Amount must be a positive integer"}, 400

    if sender_uid == recipient_uid:
        return {"error": "Cannot send money to yourself"}, 400

    db = get_firestore()
    sender_ref = _user_ref(sender_uid)
    recipient_ref = _user_ref(recipient_uid)

    # Offline idempotency (best-effort query before the transactional write).
    if offline_id:
        docs = (
            _tx_collection()
            .where("offline_id", "==", offline_id)
            .where("sender_uid", "==", sender_uid)
            .limit(1)
            .stream()
        )
        for d in docs:
            existing = d.to_dict()
            existing["id"] = d.id
            existing["idempotent_replay"] = True
            return existing

    fee = calculate_fee("transfer", amount)
    total_debit = amount + fee
    tx_ref = f"BRADPAY-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{sender_uid[:8]}-{recipient_uid[:8]}"
    result = {}

    @_firestore_module.transactional
    def _run(transaction):
        sender_snap = sender_ref.get(transaction=transaction)
        if not sender_snap.exists:
            result["error"] = ("Sender not found", 404)
            return
        recipient_snap = recipient_ref.get(transaction=transaction)
        if not recipient_snap.exists:
            result["error"] = ("Recipient not found", 404)
            return

        sender = sender_snap.to_dict()
        recipient = recipient_snap.to_dict()

        # Balance is re-read inside the transaction, so Firestore will retry
        # the whole transaction if another write touches this document
        # concurrently - this is what closes the race, not just the check.
        if sender.get("balance", 0) < total_debit:
            result["error"] = ("Insufficient balance", 400)
            return

        now = datetime.now(timezone.utc).isoformat()
        tx_data = {
            "tx_ref": tx_ref,
            "sender_uid": sender_uid,
            "recipient_uid": recipient_uid,
            "sender_name": sender.get("display_name", ""),
            "recipient_name": recipient.get("display_name", ""),
            "amount": amount,
            "fee": fee,
            "type": "transfer",
            "status": "completed",
            "note": note or "",
            "offline_id": offline_id or "",
            "created_at": now,
        }

        transaction.update(sender_ref, {
            "balance": sender["balance"] - total_debit,
            "kes_balance": max(0, sender.get("kes_balance", 0) - total_debit),
            "updated_at": now,
        })
        transaction.update(recipient_ref, {
            "balance": recipient["balance"] + amount,
            "kes_balance": recipient.get("kes_balance", 0) + amount,
            "updated_at": now,
        })
        if fee > 0:
            fees_ref = _user_ref("__fees__")
            fees_snap = fees_ref.get(transaction=transaction)
            if fees_snap.exists:
                transaction.update(fees_ref, {"balance": fees_snap.to_dict().get("balance", 0) + fee})
            else:
                transaction.set(fees_ref, {
                    "firebase_uid": "__fees__", "display_name": "BradPay Fees",
                    "balance": fee, "locked_balance": 0, "kes_balance": 0,
                    "created_at": now, "updated_at": now,
                })
        transaction.set(_tx_collection().document(), tx_data)
        result["tx"] = tx_data

    _run(db.transaction())

    if "error" in result:
        msg, code = result["error"]
        return {"error": msg}, code
    return result["tx"]


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
    result = {}

    @_firestore_module.transactional
    def _run(transaction):
        user_doc = user_ref.get(transaction=transaction)
        if not user_doc.exists:
            result["error"] = ("User not found", 404)
            return
        user = user_doc.to_dict()

        available = user.get("balance", 0) - user.get("locked_balance", 0)
        if available < amount:
            result["error"] = ("Insufficient available balance", 400)
            return
        # Lock for both buy and sell so bids cannot overcommit.
        transaction.update(user_ref, {"locked_balance": user.get("locked_balance", 0) + amount})

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
        new_ref = _orders_collection().document()
        transaction.set(new_ref, order_data)
        order_data["id"] = new_ref.id
        result["order"] = order_data

    _run(db.transaction())

    if "error" in result:
        msg, code = result["error"]
        return {"error": msg}, code
    return result["order"]


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
    if remaining > 0:
        _user_ref(user_uid).update({"locked_balance": _inc(-remaining)})

    ref.update({"status": "cancelled"})
    return {"message": "Order cancelled", "order_id": order_id}


def get_orders(user_uid, status_filter=None):
    db = get_firestore()
    query = _orders_collection().where("user_uid", "==", user_uid)
    if status_filter:
        query = query.where("status", "==", status_filter)
    docs = query.stream()
    results = [{"id": d.id, **d.to_dict()} for d in docs]
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return results


def get_order_book(limit=15):
    db = get_firestore()
    col = _orders_collection()
    buy_agg = {}
    sell_agg = {}

    buy_list = []
    sell_list = []

    for status in ("open", "partial"):
        buy_docs = (
            col.where("type", "==", "buy")
            .where("status", "==", status)
            .limit(limit * 5)
            .stream()
        )
        for d in buy_docs:
            buy_list.append(d.to_dict())

        sell_docs = (
            col.where("type", "==", "sell")
            .where("status", "==", status)
            .limit(limit * 5)
            .stream()
        )
        for d in sell_docs:
            sell_list.append(d.to_dict())

    buy_list.sort(key=lambda x: (-x["price"], x.get("created_at", "")))
    sell_list.sort(key=lambda x: (x["price"], x.get("created_at", "")))

    for o in buy_list[:limit]:
        p = o["price"]
        remaining = o["amount"] - o.get("filled", 0)
        if p in buy_agg:
            buy_agg[p]["amount"] += remaining
            buy_agg[p]["count"] += 1
        else:
            buy_agg[p] = {"price": p, "amount": remaining, "count": 1}

    for o in sell_list[:limit]:
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
    if buyer_uid == seller_uid:
        return {"error": "Cannot match orders from the same user", "success": False}
    db = get_firestore()
    try:
        buyer_fee = max(1, amount // 1000)
        seller_fee = max(1, amount // 1000)
        net_to_buyer = amount - buyer_fee - seller_fee
        if net_to_buyer < 0:
            return {"error": "Fees exceed trade amount", "success": False}

        db.collection("users").document(seller_uid).update({
            "balance": _inc(-amount),
            "locked_balance": _inc(-amount),
        })
        db.collection("users").document(buyer_uid).update({
            "balance": _inc(net_to_buyer),
            "locked_balance": _inc(-amount),
        })
        fees_ref = _user_ref("__fees__")
        fees_snap = fees_ref.get()
        if fees_snap.exists:
            fees_ref.update({"balance": _inc(buyer_fee + seller_fee)})
        else:
            fees_ref.set({
                "firebase_uid": "__fees__", "display_name": "BradPay Fees",
                "balance": buyer_fee + seller_fee, "locked_balance": 0, "kes_balance": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
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

        for oid in (buy_order_id, sell_order_id):
            oref = db.collection("orders").document(str(oid))
            oref.update({"filled": _inc(amount)})
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


# ── M-PESA Daraja ──

def _mpesa_collection():
    return get_firestore().collection("mpesa_transactions")


def create_mpesa_transaction(user_uid, type_, phone, amount, checkout_id=None, conversation_id=None):
    now = datetime.now(timezone.utc).isoformat()
    tx_data = {
        "user_uid": user_uid,
        "type": type_,
        "phone": phone,
        "amount": amount,
        "checkout_id": checkout_id or "",
        "conversation_id": conversation_id or "",
        "result_code": None,
        "result_desc": "",
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    _, ref = _mpesa_collection().add(tx_data)
    tx_data["id"] = ref.id
    return tx_data


def get_mpesa_transactions(user_uid, limit=50):
    db = get_firestore()
    docs = (
        _mpesa_collection()
        .where("user_uid", "==", user_uid)
        .order_by("created_at", direction=_desc())
        .limit(limit)
        .stream()
    )
    return [{"id": d.id, **d.to_dict()} for d in docs]


def get_mpesa_transaction_by_checkout_id(checkout_id):
    docs = (
        _mpesa_collection()
        .where("checkout_id", "==", checkout_id)
        .limit(1)
        .stream()
    )
    for d in docs:
        return {"id": d.id, **d.to_dict()}
    return None


def get_mpesa_transaction_by_conversation_id(conversation_id):
    docs = (
        _mpesa_collection()
        .where("conversation_id", "==", conversation_id)
        .limit(1)
        .stream()
    )
    for d in docs:
        return {"id": d.id, **d.to_dict()}
    return None


def update_mpesa_transaction_status(identifier, result_code, result_desc):
    status = "completed" if result_code == 0 else "failed"
    now = datetime.now(timezone.utc).isoformat()
    docs = (
        _mpesa_collection()
        .where("checkout_id", "==", identifier)
        .limit(1)
        .stream()
    )
    found = False
    for d in docs:
        d.reference.update({
            "result_code": result_code,
            "result_desc": result_desc,
            "status": status,
            "updated_at": now,
        })
        found = True
    if not found:
        docs2 = (
            _mpesa_collection()
            .where("conversation_id", "==", identifier)
            .limit(1)
            .stream()
        )
        for d in docs2:
            d.reference.update({
                "result_code": result_code,
                "result_desc": result_desc,
                "status": status,
                "updated_at": now,
            })


def claim_mpesa_callback(identifier, result_code, result_desc):
    """Claim a pending M-PESA tx. Returns (tx, claimed)."""
    tx = get_mpesa_transaction_by_checkout_id(identifier)
    if not tx:
        tx = get_mpesa_transaction_by_conversation_id(identifier)
    if not tx:
        return None, False
    if tx.get("status") != "pending":
        return tx, False
    status = "completed" if result_code == 0 else "failed"
    now = datetime.now(timezone.utc).isoformat()
    # Conditional-style: only update if still pending (best-effort without txn).
    ref = _mpesa_collection().document(tx["id"])
    snap = ref.get()
    if not snap.exists or snap.to_dict().get("status") != "pending":
        return tx, False
    ref.update({
        "result_code": result_code,
        "result_desc": result_desc,
        "status": status,
        "updated_at": now,
    })
    tx["status"] = status
    tx["result_code"] = result_code
    tx["result_desc"] = result_desc
    return tx, True


def update_kes_balance(user_uid, amount_delta):
    """Credit/debit main wallet `balance` (kes_balance kept in sync). Returns bool."""
    db = get_firestore()
    user_ref = db.collection("users").document(user_uid)
    result = {"ok": False}

    @_firestore_module.transactional
    def _run(transaction):
        snap = user_ref.get(transaction=transaction)
        if not snap.exists:
            return
        data = snap.to_dict()
        bal = data.get("balance", 0) or 0
        if amount_delta < 0 and bal < -amount_delta:
            return
        new_bal = bal + amount_delta
        transaction.update(user_ref, {
            "balance": new_bal,
            "kes_balance": new_bal,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        result["ok"] = True

    _run(db.transaction())
    return result["ok"]


def get_kes_balance(user_uid):
    user = get_user_by_firebase_uid(user_uid)
    if user:
        return user.get("balance", 0)
    return None


# ── Agent functions ──

def _agents_collection():
    db = get_firestore()
    return db.collection("agents")


def create_agent(firebase_uid, business_name, contact_phone=None, email=None, id_number=None, kra_pin=None, location=None):
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "firebase_uid": firebase_uid,
        "business_name": business_name,
        "contact_phone": contact_phone,
        "email": email,
        "id_number": id_number,
        "kra_pin": kra_pin,
        "location": location,
        "status": "pending",
        "float_balance": 0,
        "commission_rate": 100,
        "total_commission_earned": 0,
        "created_at": now,
        "verified_at": None,
    }
    _agents_collection().document(firebase_uid).set(data)
    return data


def get_agent(firebase_uid):
    doc = _agents_collection().document(firebase_uid).get()
    return doc.to_dict() if doc.exists else None


def get_agent_by_id(agent_id):
    return get_agent(agent_id)


def update_agent_status(firebase_uid, status):
    now = datetime.now(timezone.utc).isoformat()
    update = {"status": status}
    if status == "active":
        update["verified_at"] = now
    _agents_collection().document(firebase_uid).update(update)


def update_agent_float(agent_uid, amount_delta):
    agent = get_agent(agent_uid)
    if not agent:
        return False
    new_float = agent.get("float_balance", 0) + amount_delta
    if new_float < 0:
        return False
    _agents_collection().document(agent_uid).update({"float_balance": new_float})
    return True


def get_all_agents(status=None):
    coll = _agents_collection()
    if status:
        docs = coll.where("status", "==", status).order_by("created_at", direction="DESCENDING").stream()
    else:
        docs = coll.order_by("created_at", direction="DESCENDING").stream()
    return [d.to_dict() for d in docs]


def create_agent_transaction(agent_uid, type_, amount, user_uid=None, commission=0, reference=None):
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "agent_uid": agent_uid,
        "type": type_,
        "amount": amount,
        "user_uid": user_uid,
        "commission": commission,
        "reference": reference,
        "status": "completed",
        "created_at": now,
    }
    _agents_collection().document(agent_uid).collection("transactions").add(data)
    return data


def get_agent_transactions(agent_uid, limit=50):
    docs = (
        _agents_collection()
        .document(agent_uid)
        .collection("transactions")
        .order_by("created_at", direction="DESCENDING")
        .limit(limit)
        .stream()
    )
    return [d.to_dict() for d in docs]


def agent_float_topup(user_uid, amount):
    agent = get_agent(user_uid)
    if not agent or agent.get("status") != "active":
        return {"error": "Agent not active"}, 403
    if not update_kes_balance(user_uid, -amount):
        return {"error": "Insufficient balance"}, 400
    update_agent_float(user_uid, amount)
    create_agent_transaction(user_uid, "float_topup", amount, reference=f"float_{user_uid[:8]}_{amount}")
    return {"message": "Float topped up", "amount": amount}


def agent_float_transfer(from_uid, to_uid, amount):
    from_agent = get_agent(from_uid)
    to_agent = get_agent(to_uid)
    if not from_agent:
        return {"error": "You are not an agent"}, 404
    if from_agent.get("status") != "active":
        return {"error": "Your agent account is not active"}, 403
    if not to_agent:
        return {"error": "Recipient agent not found"}, 404
    if to_agent.get("status") != "active":
        return {"error": "Recipient agent is not active"}, 403
    if not update_agent_float(from_uid, -amount):
        return {"error": "Insufficient float balance"}, 400
    update_agent_float(to_uid, amount)
    ref = f"float_xfer_{from_uid[:8]}_{to_uid[:8]}_{amount}"
    create_agent_transaction(from_uid, "float_withdrawal", amount, user_uid=to_uid, reference=ref)
    create_agent_transaction(to_uid, "float_topup", amount, user_uid=from_uid, reference=ref)
    return {
        "message": f"Float transfer of KES {amount / 100:.2f} sent",
        "amount": amount,
        "from_agent": from_uid,
        "to_agent": to_uid,
    }


def agent_cash_in(agent_uid, user_phone, amount):
    agent = get_agent(agent_uid)
    if not agent or agent.get("status") != "active":
        return {"error": "Agent not active"}, 403
    user = get_user_by_phone_or_email(user_phone)
    if not user:
        return {"error": "User not found"}, 404
    commission = calculate_fee("agent_commission", amount)
    if commission >= amount:
        commission = 0
    user_credit = amount - commission
    if not update_agent_float(agent_uid, -amount):
        return {"error": "Insufficient float"}, 400
    if commission > 0:
        update_agent_float(agent_uid, commission)
        _agents_collection().document(agent_uid).update({
            "total_commission_earned": _inc(commission),
        })
    update_kes_balance(user["firebase_uid"], user_credit)
    create_agent_transaction(
        agent_uid, "cash_in", amount, user_uid=user["firebase_uid"],
        commission=commission, reference=f"cashin_{user_phone}",
    )
    if commission > 0:
        create_agent_transaction(agent_uid, "commission", commission, reference=f"comm_{agent_uid[:8]}_{amount}")
    return {
        "message": "Cash-in successful",
        "amount": amount,
        "credited": user_credit,
        "commission": commission,
    }


def agent_cash_out(agent_uid, user_phone, amount):
    agent = get_agent(agent_uid)
    if not agent or agent.get("status") != "active":
        return {"error": "Agent not active"}, 403
    user = get_user_by_phone_or_email(user_phone)
    if not user:
        return {"error": "User not found"}, 404
    if not update_kes_balance(user["firebase_uid"], -amount):
        return {"error": "User insufficient balance"}, 400
    update_agent_float(agent_uid, amount)
    create_agent_transaction(
        agent_uid, "cash_out", amount, user_uid=user["firebase_uid"],
        reference=f"cashout_{user_phone}",
    )
    return {"message": "Cash-out successful", "amount": amount}


# ── Tariff functions ──

def _tariffs_collection():
    db = get_firestore()
    return db.collection("tariffs")


def create_tariff(name, type_, percentage=None, flat_fee=None, min_amount=None, max_amount=None):
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "name": name,
        "type": type_,
        "percentage": percentage,
        "flat_fee": flat_fee,
        "min_amount": min_amount,
        "max_amount": max_amount,
        "is_active": True,
        "created_at": now,
    }
    _, ref = _tariffs_collection().add(data)
    data["id"] = ref.id
    return data


def get_active_tariffs():
    docs = _tariffs_collection().where("is_active", "==", True).stream()
    return [d.to_dict() for d in docs]


def get_tariff_by_type(type_):
    docs = (
        _tariffs_collection()
        .where("is_active", "==", True)
        .where("type", "==", type_)
        .stream()
    )
    return [d.to_dict() for d in docs]


def update_tariff(tariff_id, **kwargs):
    _tariffs_collection().document(tariff_id).update(kwargs)
    doc = _tariffs_collection().document(tariff_id).get()
    return doc.to_dict() if doc.exists else None


# ── BradSec ──

def _sec_events_collection():
    return get_firestore().collection("security_events")


def _flagged_tx_collection():
    return get_firestore().collection("flagged_transactions")


def _rate_limit_collection():
    return get_firestore().collection("rate_limits")


def log_event(event_type, severity="info", uid=None, details=None, ip_address=None, user_agent=None):
    allowed_types = (
        "login_success", "login_failure", "registration", "logout",
        "send", "receive", "deposit", "withdrawal",
        "admin_credit", "admin_debit",
        "agent_cash_in", "agent_cash_out", "float_topup", "float_transfer",
        "rate_limit_hit", "fraud_flag", "fraud_resolve",
        "pin_change", "pin_failure",
        "suspicious_ip", "suspicious_device",
    )
    allowed_sevs = ("info", "low", "medium", "high", "critical")
    if event_type not in allowed_types:
        event_type = "suspicious_ip"
    if severity not in allowed_sevs:
        severity = "info"
    now = datetime.now(timezone.utc).isoformat()
    _sec_events_collection().add({
        "event_type": event_type,
        "severity": severity,
        "uid": uid,
        "details": json.dumps(details) if details else None,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "created_at": now,
    })


def get_events(limit=50, offset=0, event_type=None, severity=None, uid=None):
    col = _sec_events_collection()
    docs = col.order_by("created_at", direction=_desc()).limit(limit + offset).stream()
    results = []
    for d in docs:
        data = d.to_dict()
        if uid and data.get("uid") != uid:
            continue
        if event_type and data.get("event_type") != event_type:
            continue
        if severity and data.get("severity") != severity:
            continue
        results.append({"id": d.id, **data})
    return results[offset:offset + limit]


def count_events(event_type=None, severity=None, uid=None):
    docs = _sec_events_collection().stream()
    count = 0
    for d in docs:
        data = d.to_dict()
        if uid and data.get("uid") != uid:
            continue
        if event_type and data.get("event_type") != event_type:
            continue
        if severity and data.get("severity") != severity:
            continue
        count += 1
    return count


def check_rate_limit(uid, action, max_count=10, window_seconds=60):
    from bradsec import RATE_LIMITS
    cfg = RATE_LIMITS.get(action)
    if not cfg:
        return True
    doc_ref = _rate_limit_collection().document(f"{uid}:{action}")
    doc = doc_ref.get()
    now = time.time()
    window_start = now - (now % cfg["window"])

    if doc.exists:
        data = doc.to_dict()
        if data.get("window_start") == window_start:
            if data["count"] >= cfg["max"]:
                return False
            doc_ref.update({"count": _inc(1)})
        else:
            doc_ref.set({"uid": uid, "action": action, "window_start": window_start, "count": 1})
    else:
        doc_ref.set({"uid": uid, "action": action, "window_start": window_start, "count": 1})
    return True


def get_rate_limit_remaining(uid, action, max_count=10, window_seconds=60):
    from bradsec import RATE_LIMITS
    cfg = RATE_LIMITS.get(action)
    if not cfg:
        return -1
    doc = _rate_limit_collection().document(f"{uid}:{action}").get()
    data = doc.to_dict() if doc.exists else {}
    used = data.get("count", 0)
    return max(0, cfg["max"] - used)


def reset_rate_limit(uid, action):
    _rate_limit_collection().document(f"{uid}:{action}").delete()


def evaluate_transaction(sender_uid, recipient_uid, amount, tx_ref=None, status="open"):
    from bradsec import FRAUD_RULES, FLAG_THRESHOLD
    import time
    from datetime import timedelta

    triggered = []
    total_score = 0
    now = datetime.now(timezone.utc)

    settings = get_bradsec_settings()
    auto_block = settings.get("auto_block_enabled", False)
    auto_block_threshold = settings.get("auto_block_threshold", 60)

    # 1. Velocity
    since = (now - timedelta(seconds=300)).isoformat()
    recent = _sec_events_collection().where("uid", "==", sender_uid).where("event_type", "==", "send").where("created_at", ">=", since).stream()
    if len(list(recent)) >= 5:
        triggered.append(FRAUD_RULES["velocity"])
        total_score += FRAUD_RULES["velocity"]["score"]

    # 2. Amount anomaly
    if amount > 10_000_000:
        triggered.append(FRAUD_RULES["amount_anomaly"])
        total_score += FRAUD_RULES["amount_anomaly"]["score"]

    # 3. New account
    user = get_user_by_firebase_uid(sender_uid)
    if user and amount > 1_000_000:
        created = user.get("created_at")
        if created:
            try:
                created_dt = datetime.fromisoformat(created)
                if now - created_dt < timedelta(hours=24):
                    triggered.append(FRAUD_RULES["new_account"])
                    total_score += FRAUD_RULES["new_account"]["score"]
            except (ValueError, TypeError):
                pass

    # 4. Rapid same-recipient
    since_tx = (now - timedelta(seconds=600)).isoformat()
    recent_tx = list(
        get_firestore().collection("transactions")
        .where("sender_uid", "==", sender_uid)
        .where("recipient_uid", "==", recipient_uid)
        .where("created_at", ">=", since_tx)
        .stream()
    )
    if len(recent_tx) >= 3:
        triggered.append(FRAUD_RULES["rapid_recipient"])
        total_score += FRAUD_RULES["rapid_recipient"]["score"]

    # 5. Balance drain
    if user:
        kes = user.get("kes_balance", 0)
        if kes > 0 and amount > kes * 0.9:
            triggered.append(FRAUD_RULES["balance_drain"])
            total_score += FRAUD_RULES["balance_drain"]["score"]

    # 6. Unusual hours
    hour = now.hour
    if hour < 5 or hour >= 23:
        triggered.append(FRAUD_RULES["unusual_hours"])
        total_score += FRAUD_RULES["unusual_hours"]["score"]

    # 7. Round numbers
    if amount % 100000 == 0 and amount >= 500000:
        triggered.append(FRAUD_RULES["round_numbers"])
        total_score += FRAUD_RULES["round_numbers"]["score"]

    total_score = min(total_score, 100)
    is_flagged = total_score >= FLAG_THRESHOLD
    is_auto_blocked = auto_block and is_flagged and total_score >= auto_block_threshold
    flag_status = "blocked" if is_auto_blocked else status

    if is_flagged:
        ref = tx_ref or f"FRAUD-{int(time.time())}-{sender_uid[:8]}"
        _flagged_tx_collection().add({
            "tx_ref": ref,
            "sender_uid": sender_uid,
            "recipient_uid": recipient_uid,
            "amount": amount,
            "score": total_score,
            "rules_triggered": json.dumps([r["label"] for r in triggered]),
            "status": flag_status,
            "created_at": now.isoformat(),
        })
        log_event("fraud_flag", "high", sender_uid, {
            "tx_ref": ref, "amount": amount, "score": total_score,
            "rules": [r["label"] for r in triggered],
            "auto_blocked": is_auto_blocked,
        })

    return {
        "score": total_score,
        "flagged": is_flagged,
        "auto_blocked": is_auto_blocked,
        "threshold": FLAG_THRESHOLD,
        "auto_block_threshold": auto_block_threshold if auto_block else None,
        "rules_triggered": [r["label"] for r in triggered],
    }


def get_flagged_transactions(status=None, limit=50, offset=0):
    col = _flagged_tx_collection()
    if status:
        docs = col.where("status", "==", status).order_by("created_at", direction=_desc()).limit(limit).offset(offset).stream()
    else:
        docs = col.order_by("created_at", direction=_desc()).limit(limit).offset(offset).stream()
    return [{"id": d.id, **d.to_dict()} for d in docs]


def resolve_flag(flag_id, status, reviewer_uid, note=None):
    ref = _flagged_tx_collection().document(flag_id)
    doc = ref.get()
    if not doc.exists:
        return None
    now = datetime.now(timezone.utc).isoformat()
    ref.update({
        "status": status,
        "reviewed_by": reviewer_uid,
        "reviewed_at": now,
        "resolution_note": note or "",
    })
    log_event("fraud_resolve", "info", reviewer_uid, {"flag_id": flag_id, "resolution": status})
    return {"id": flag_id, **doc.to_dict()}


def get_flag_stats():
    col = _flagged_tx_collection()
    all_flags = list(col.stream())
    stats = {"open": 0, "approved": 0, "blocked": 0}
    for d in all_flags:
        s = d.to_dict().get("status", "open")
        if s in stats:
            stats[s] += 1
    return {**stats, "total": sum(stats.values())}


def get_security_summary():
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    high = list(
        _sec_events_collection()
        .where("severity", "in", ["high", "critical"])
        .where("created_at", ">=", since)
        .stream()
    )
    total_24h = list(
        _sec_events_collection()
        .where("created_at", ">=", since)
        .stream()
    )
    recent = list(
        _sec_events_collection()
        .order_by("created_at", direction=_desc())
        .limit(10)
        .stream()
    )
    return {
        "high_severity_24h": len(high),
        "total_events_24h": len(total_24h),
        "open_flags": get_flag_stats()["open"],
        "recent_events": [{"id": d.id, **d.to_dict()} for d in recent],
    }


# ── Ledger persistence ──

def save_ledger_state(chain, pending):
    db = get_firestore()
    db.collection("system").document("ledger").set({
        "chain": chain,
        "pending": pending,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def load_ledger_state():
    db = get_firestore()
    doc = db.collection("system").document("ledger").get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    return data.get("chain", []), data.get("pending", [])
