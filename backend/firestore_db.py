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
