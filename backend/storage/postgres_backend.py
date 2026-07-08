"""Postgres/Neon backend implementing StorageBackend ABC.
Used when DATABASE_URL env var is set.
"""

import os
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_conn = None


def _get_conn():
    global _conn
    if _conn is None:
        import psycopg2
        import psycopg2.extras
        _conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        _conn.autocommit = False
    return _conn


def _dict_row(cursor):
    """Convert cursor to list of dicts."""
    if cursor.description is None:
        return []
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _one(cursor):
    rows = _dict_row(cursor)
    return rows[0] if rows else None


def init_bradsec():
    pass


def init_db():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            firebase_uid TEXT UNIQUE NOT NULL,
            email TEXT,
            display_name TEXT,
            phone TEXT,
            pin_hash TEXT NOT NULL,
            balance INTEGER NOT NULL DEFAULT 0,
            locked_balance INTEGER NOT NULL DEFAULT 0,
            kes_balance INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_uid TEXT NOT NULL REFERENCES users(firebase_uid),
            type TEXT NOT NULL CHECK(type IN ('buy','sell')),
            price INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            filled INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            buy_order_id INTEGER NOT NULL REFERENCES orders(id),
            sell_order_id INTEGER NOT NULL REFERENCES orders(id),
            buyer_uid TEXT NOT NULL,
            seller_uid TEXT NOT NULL,
            amount INTEGER NOT NULL,
            price INTEGER NOT NULL,
            buyer_fee INTEGER NOT NULL DEFAULT 0,
            seller_fee INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            tx_ref TEXT UNIQUE NOT NULL,
            sender_id INTEGER NOT NULL REFERENCES users(id),
            recipient_id INTEGER NOT NULL REFERENCES users(id),
            amount INTEGER NOT NULL,
            fee INTEGER NOT NULL DEFAULT 0,
            type TEXT NOT NULL DEFAULT 'transfer',
            status TEXT NOT NULL DEFAULT 'pending',
            note TEXT,
            offline_id TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            synced_at TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS mpesa_transactions (
            id SERIAL PRIMARY KEY,
            user_uid TEXT NOT NULL REFERENCES users(firebase_uid),
            type TEXT NOT NULL CHECK(type IN ('deposit','withdrawal')),
            phone TEXT NOT NULL,
            amount INTEGER NOT NULL,
            checkout_id TEXT,
            conversation_id TEXT,
            result_code INTEGER,
            result_desc TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS agents (
            id SERIAL PRIMARY KEY,
            firebase_uid TEXT UNIQUE NOT NULL REFERENCES users(firebase_uid),
            business_name TEXT NOT NULL,
            contact_phone TEXT,
            email TEXT,
            id_number TEXT,
            kra_pin TEXT,
            location TEXT,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','active','suspended','rejected')),
            float_balance INTEGER NOT NULL DEFAULT 0,
            commission_rate INTEGER NOT NULL DEFAULT 100,
            total_commission_earned INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            verified_at TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS agent_transactions (
            id SERIAL PRIMARY KEY,
            agent_uid TEXT NOT NULL REFERENCES agents(firebase_uid),
            type TEXT NOT NULL CHECK(type IN ('float_topup','float_withdrawal','commission','cash_in','cash_out')),
            amount INTEGER NOT NULL,
            user_uid TEXT,
            commission INTEGER DEFAULT 0,
            reference TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS tariffs (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('transfer','deposit','withdrawal','agent_commission','float_topup')),
            percentage INTEGER,
            flat_fee INTEGER,
            min_amount INTEGER,
            max_amount INTEGER,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS security_events (
            id SERIAL PRIMARY KEY,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            uid TEXT,
            details TEXT,
            ip_address TEXT,
            user_agent TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS flagged_transactions (
            id SERIAL PRIMARY KEY,
            tx_ref TEXT NOT NULL,
            sender_uid TEXT,
            recipient_uid TEXT,
            amount INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            rules_triggered TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            reviewed_by TEXT,
            reviewed_at TIMESTAMP,
            resolution_note TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS rate_limit_counts (
            id SERIAL PRIMARY KEY,
            uid TEXT NOT NULL,
            action TEXT NOT NULL,
            window_start DOUBLE PRECISION NOT NULL,
            count INTEGER NOT NULL DEFAULT 1,
            UNIQUE(uid, action, window_start)
        );
        CREATE INDEX IF NOT EXISTS idx_users_firebase_uid ON users(firebase_uid);
        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_uid);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_orders_type_price ON orders(type, price);
        CREATE INDEX IF NOT EXISTS idx_trades_buyer ON trades(buyer_uid);
        CREATE INDEX IF NOT EXISTS idx_trades_seller ON trades(seller_uid);
        CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender_id);
        CREATE INDEX IF NOT EXISTS idx_tx_recipient ON transactions(recipient_id);
        CREATE INDEX IF NOT EXISTS idx_tx_offline ON transactions(offline_id);
        CREATE INDEX IF NOT EXISTS idx_tx_status ON transactions(status);
        CREATE INDEX IF NOT EXISTS idx_mpesa_checkout ON mpesa_transactions(checkout_id);
        CREATE INDEX IF NOT EXISTS idx_mpesa_conversation ON mpesa_transactions(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_mpesa_user ON mpesa_transactions(user_uid);
        CREATE INDEX IF NOT EXISTS idx_sec_events_uid ON security_events(uid);
        CREATE INDEX IF NOT EXISTS idx_sec_events_type ON security_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_sec_events_severity ON security_events(severity);
        CREATE INDEX IF NOT EXISTS idx_sec_events_created ON security_events(created_at);
        CREATE INDEX IF NOT EXISTS idx_flags_status ON flagged_transactions(status);
        CREATE INDEX IF NOT EXISTS idx_flags_tx ON flagged_transactions(tx_ref);
        CREATE INDEX IF NOT EXISTS idx_rate_limit_lookup ON rate_limit_counts(uid, action, window_start);
    """)
    conn.commit()
    cur.close()


def create_user(firebase_uid, email=None, display_name=None, phone=None, pin="1234"):
    conn = _get_conn()
    cur = conn.cursor()
    try:
        pin_hash = generate_password_hash(pin)
        cur.execute(
            "INSERT INTO users (firebase_uid, email, display_name, phone, pin_hash) VALUES (%s, %s, %s, %s, %s)",
            (firebase_uid, email, display_name, phone, pin_hash),
        )
        conn.commit()
        cur.execute("SELECT * FROM users WHERE firebase_uid = %s", (firebase_uid,))
        return _one(cur)
    except Exception:
        conn.rollback()
        return None
    finally:
        cur.close()


def get_user_by_firebase_uid(firebase_uid):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE firebase_uid = %s", (firebase_uid,))
    result = _one(cur)
    cur.close()
    return result


def get_user_by_id(user_id):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    result = _one(cur)
    cur.close()
    return result


def verify_pin(firebase_uid, pin):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pin_hash FROM users WHERE firebase_uid = %s", (firebase_uid,))
    row = _one(cur)
    cur.close()
    if not row:
        return False
    return check_password_hash(row["pin_hash"], pin)


def get_balance(firebase_uid):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE firebase_uid = %s", (firebase_uid,))
    row = _one(cur)
    cur.close()
    return row["balance"] if row else None


def get_user_by_phone_or_email(identifier):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s OR phone = %s", (identifier, identifier))
    result = _one(cur)
    cur.close()
    return result


def get_user_with_locked(firebase_uid):
    return get_user_by_firebase_uid(firebase_uid)


def update_kes_balance(user_uid, amount_delta):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET kes_balance = GREATEST(COALESCE(kes_balance, 0) + %s, 0), updated_at = NOW() WHERE firebase_uid = %s",
        (amount_delta, user_uid),
    )
    conn.commit()
    cur.close()


def get_kes_balance(user_uid):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT kes_balance FROM users WHERE firebase_uid = %s", (user_uid,))
    row = _one(cur)
    cur.close()
    return row["kes_balance"] if row else None


def create_transaction(sender_uid, recipient_uid, amount, note=None, offline_id=None):
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, firebase_uid, balance FROM users WHERE firebase_uid = %s", (sender_uid,))
        sender = _one(cur)
        if not sender:
            return {"error": "Sender not found"}, 404

        cur.execute("SELECT id, balance FROM users WHERE firebase_uid = %s", (recipient_uid,))
        recipient = _one(cur)
        if not recipient:
            return {"error": "Recipient not found"}, 404

        if sender["balance"] < amount:
            return {"error": "Insufficient balance"}, 400

        fee = 0
        tx_ref = f"BRADPAY-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{sender['id']}-{recipient['id']}"

        cur.execute("UPDATE users SET balance = balance - %s, updated_at = NOW() WHERE id = %s", (amount, sender["id"]))
        cur.execute("UPDATE users SET balance = balance + %s, updated_at = NOW() WHERE id = %s", (amount, recipient["id"]))
        cur.execute(
            "INSERT INTO transactions (tx_ref, sender_id, recipient_id, amount, fee, type, status, note, offline_id) VALUES (%s, %s, %s, %s, %s, 'transfer', 'completed', %s, %s)",
            (tx_ref, sender["id"], recipient["id"], amount, fee, note, offline_id),
        )
        conn.commit()

        cur.execute("SELECT * FROM transactions WHERE tx_ref = %s", (tx_ref,))
        return _one(cur)
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cur.close()


def get_transactions(firebase_uid, limit=50):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE firebase_uid = %s", (firebase_uid,))
    user = _one(cur)
    if not user:
        cur.close()
        return []
    cur.execute(
        """SELECT t.*, u1.firebase_uid as sender_uid, u1.display_name as sender_name,
                  u2.firebase_uid as recipient_uid, u2.display_name as recipient_name
           FROM transactions t
           JOIN users u1 ON t.sender_id = u1.id
           JOIN users u2 ON t.recipient_id = u2.id
           WHERE t.sender_id = %s OR t.recipient_id = %s
           ORDER BY t.created_at DESC LIMIT %s""",
        (user["id"], user["id"], limit),
    )
    rows = _dict_row(cur)
    cur.close()
    return rows


def create_order(user_uid, order_type, price, amount):
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, balance, locked_balance FROM users WHERE firebase_uid = %s", (user_uid,))
        user = _one(cur)
        if not user:
            return {"error": "User not found"}, 404

        if order_type == "sell":
            available = user["balance"] - (user["locked_balance"] or 0)
            if available < amount:
                return {"error": "Insufficient available balance"}, 400
            cur.execute(
                "UPDATE users SET locked_balance = COALESCE(locked_balance, 0) + %s WHERE firebase_uid = %s",
                (amount, user_uid),
            )

        cur.execute(
            "INSERT INTO orders (user_uid, type, price, amount) VALUES (%s, %s, %s, %s) RETURNING *",
            (user_uid, order_type, price, amount),
        )
        conn.commit()
        return _one(cur)
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cur.close()


def cancel_order(user_uid, order_id):
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM orders WHERE id = %s AND user_uid = %s", (order_id, user_uid))
        order = _one(cur)
        if not order:
            return {"error": "Order not found"}, 404
        if order["status"] not in ("open", "partial"):
            return {"error": "Order cannot be cancelled"}, 400

        remaining = order["amount"] - order["filled"]
        if order["type"] == "sell" and remaining > 0:
            cur.execute(
                "UPDATE users SET locked_balance = GREATEST(COALESCE(locked_balance,0) - %s, 0) WHERE firebase_uid = %s",
                (remaining, user_uid),
            )

        cur.execute("UPDATE orders SET status = 'cancelled' WHERE id = %s", (order_id,))
        conn.commit()
        return {"message": "Order cancelled", "order_id": order_id}
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        cur.close()


def get_orders(user_uid, status_filter=None):
    conn = _get_conn()
    cur = conn.cursor()
    if status_filter:
        cur.execute(
            "SELECT * FROM orders WHERE user_uid = %s AND status = %s ORDER BY created_at DESC",
            (user_uid, status_filter),
        )
    else:
        cur.execute("SELECT * FROM orders WHERE user_uid = %s ORDER BY created_at DESC", (user_uid,))
    rows = _dict_row(cur)
    cur.close()
    return rows


def get_order_book(limit=15):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM orders WHERE type='buy' AND status IN ('open','partial') ORDER BY price DESC, created_at ASC LIMIT %s",
        (limit,),
    )
    buys = _dict_row(cur)
    cur.execute(
        "SELECT * FROM orders WHERE type='sell' AND status IN ('open','partial') ORDER BY price ASC, created_at ASC LIMIT %s",
        (limit,),
    )
    sells = _dict_row(cur)
    cur.close()
    buy_agg = {}
    for d in buys:
        p = d["price"]
        remaining = d["amount"] - d["filled"]
        if p in buy_agg:
            buy_agg[p]["amount"] += remaining
            buy_agg[p]["count"] += 1
        else:
            buy_agg[p] = {"price": p, "amount": remaining, "count": 1}
    sell_agg = {}
    for d in sells:
        p = d["price"]
        remaining = d["amount"] - d["filled"]
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
    conn = _get_conn()
    cur = conn.cursor()
    try:
        buyer_fee = max(1, amount // 1000)
        seller_fee = max(1, amount // 1000)
        cur.execute("UPDATE users SET balance = balance + %s WHERE firebase_uid = %s", (amount - buyer_fee, buyer_uid))
        cur.execute(
            "UPDATE users SET balance = balance - %s, locked_balance = GREATEST(COALESCE(locked_balance,0) - %s, 0) WHERE firebase_uid = %s",
            (amount, amount, seller_uid),
        )
        cur.execute(
            "INSERT INTO trades (buy_order_id, sell_order_id, buyer_uid, seller_uid, amount, price, buyer_fee, seller_fee) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (buy_order_id, sell_order_id, buyer_uid, seller_uid, amount, price, buyer_fee, seller_fee),
        )
        for oid in (buy_order_id, sell_order_id):
            cur.execute(
                "UPDATE orders SET filled = filled + %s, status = CASE WHEN filled + %s >= amount THEN 'filled'::text ELSE 'partial'::text END WHERE id = %s",
                (amount, amount, oid),
            )
        conn.commit()
        return {"success": True, "amount": amount, "price": price}
    except Exception as e:
        conn.rollback()
        return {"error": str(e), "success": False}
    finally:
        cur.close()


def get_trades(user_uid=None, limit=50):
    conn = _get_conn()
    cur = conn.cursor()
    if user_uid:
        cur.execute(
            "SELECT * FROM trades WHERE buyer_uid = %s OR seller_uid = %s ORDER BY created_at DESC LIMIT %s",
            (user_uid, user_uid, limit),
        )
    else:
        cur.execute("SELECT * FROM trades ORDER BY created_at DESC LIMIT %s", (limit,))
    rows = _dict_row(cur)
    cur.close()
    return rows


def create_mpesa_transaction(user_uid, type_, phone, amount, checkout_id=None, conversation_id=None):
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO mpesa_transactions (user_uid, type, phone, amount, checkout_id, conversation_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (user_uid, type_, phone, amount, checkout_id, conversation_id),
        )
        conn.commit()
        return _one(cur)
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}
    finally:
        cur.close()


def get_mpesa_transactions(user_uid, limit=50):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM mpesa_transactions WHERE user_uid = %s ORDER BY created_at DESC LIMIT %s",
        (user_uid, limit),
    )
    rows = _dict_row(cur)
    cur.close()
    return rows


def get_mpesa_transaction_by_checkout_id(checkout_id):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM mpesa_transactions WHERE checkout_id = %s", (checkout_id,))
    result = _one(cur)
    cur.close()
    return result


def get_mpesa_transaction_by_conversation_id(conversation_id):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM mpesa_transactions WHERE conversation_id = %s", (conversation_id,))
    result = _one(cur)
    cur.close()
    return result


def update_mpesa_transaction_status(identifier, result_code, result_desc):
    conn = _get_conn()
    cur = conn.cursor()
    status = "completed" if result_code == 0 else "failed"
    cur.execute(
        "UPDATE mpesa_transactions SET result_code = %s, result_desc = %s, status = %s, updated_at = NOW() WHERE checkout_id = %s OR conversation_id = %s",
        (result_code, result_desc, status, identifier, identifier),
    )
    conn.commit()
    cur.close()


def create_agent(firebase_uid, business_name, contact_phone=None, email=None, id_number=None, kra_pin=None, location=None):
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO agents (firebase_uid, business_name, contact_phone, email, id_number, kra_pin, location) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (firebase_uid, business_name, contact_phone, email, id_number, kra_pin, location),
        )
        conn.commit()
        return _one(cur)
    except Exception as e:
        return {"error": str(e)}
    finally:
        cur.close()


def get_agent(firebase_uid):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM agents WHERE firebase_uid = %s", (firebase_uid,))
    result = _one(cur)
    cur.close()
    return result


def get_agent_by_id(agent_id):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM agents WHERE id = %s", (agent_id,))
    result = _one(cur)
    cur.close()
    return result


def update_agent_status(firebase_uid, status):
    conn = _get_conn()
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    if status == "active":
        cur.execute("UPDATE agents SET status = %s, verified_at = %s WHERE firebase_uid = %s", (status, now, firebase_uid))
    else:
        cur.execute("UPDATE agents SET status = %s WHERE firebase_uid = %s", (status, firebase_uid))
    conn.commit()
    cur.close()


def update_agent_float(agent_uid, amount_delta):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE agents SET float_balance = GREATEST(COALESCE(float_balance, 0) + %s, 0) WHERE firebase_uid = %s",
        (amount_delta, agent_uid),
    )
    conn.commit()
    cur.close()


def get_all_agents(status=None):
    conn = _get_conn()
    cur = conn.cursor()
    if status:
        cur.execute("SELECT * FROM agents WHERE status = %s ORDER BY created_at DESC", (status,))
    else:
        cur.execute("SELECT * FROM agents ORDER BY created_at DESC")
    rows = _dict_row(cur)
    cur.close()
    return rows


def create_agent_transaction(agent_uid, type_, amount, user_uid=None, commission=0, reference=None):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO agent_transactions (agent_uid, type, amount, user_uid, commission, reference) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
        (agent_uid, type_, amount, user_uid, commission, reference),
    )
    conn.commit()
    result = _one(cur)
    cur.close()
    return result


def get_agent_transactions(agent_uid, limit=50):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM agent_transactions WHERE agent_uid = %s ORDER BY created_at DESC LIMIT %s",
        (agent_uid, limit),
    )
    rows = _dict_row(cur)
    cur.close()
    return rows


def create_tariff(name, type_, percentage=None, flat_fee=None, min_amount=None, max_amount=None):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tariffs (name, type, percentage, flat_fee, min_amount, max_amount) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
        (name, type_, percentage, flat_fee, min_amount, max_amount),
    )
    conn.commit()
    result = _one(cur)
    cur.close()
    return result


def get_active_tariffs():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tariffs WHERE is_active = TRUE ORDER BY type, name")
    rows = _dict_row(cur)
    cur.close()
    return rows


def get_tariff_by_type(type_):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tariffs WHERE type = %s AND is_active = TRUE ORDER BY min_amount ASC", (type_,))
    rows = _dict_row(cur)
    cur.close()
    return rows


def update_tariff(tariff_id, **kwargs):
    conn = _get_conn()
    cur = conn.cursor()
    fields = {k: v for k, v in kwargs.items() if v is not None}
    if not fields:
        cur.close()
        return None
    sets = ", ".join(f"{k} = %s" for k in fields)
    vals = list(fields.values()) + [tariff_id]
    cur.execute(f"UPDATE tariffs SET {sets} WHERE id = %s RETURNING *", vals)
    conn.commit()
    result = _one(cur)
    cur.close()
    return result


def log_event(event_type, severity="info", uid=None, details=None, ip_address=None, user_agent=None):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO security_events (event_type, severity, uid, details, ip_address, user_agent) VALUES (%s, %s, %s, %s, %s, %s)",
        (event_type, severity, uid, json.dumps(details) if details else None, ip_address, user_agent),
    )
    conn.commit()
    cur.close()


def get_events(limit=50, offset=0, event_type=None, severity=None, uid=None):
    conn = _get_conn()
    cur = conn.cursor()
    clauses = []
    params = []
    if uid:
        clauses.append("uid = %s")
        params.append(uid)
    if event_type:
        clauses.append("event_type = %s")
        params.append(event_type)
    if severity:
        clauses.append("severity = %s")
        params.append(severity)
    where = " AND ".join(clauses) if clauses else "TRUE"
    cur.execute(
        f"SELECT * FROM security_events WHERE {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
        (*params, limit, offset),
    )
    rows = _dict_row(cur)
    cur.close()
    return rows


def count_events(event_type=None, severity=None, uid=None):
    conn = _get_conn()
    cur = conn.cursor()
    clauses = []
    params = []
    if uid:
        clauses.append("uid = %s")
        params.append(uid)
    if event_type:
        clauses.append("event_type = %s")
        params.append(event_type)
    if severity:
        clauses.append("severity = %s")
        params.append(severity)
    where = " AND ".join(clauses) if clauses else "TRUE"
    cur.execute(f"SELECT COUNT(*) as cnt FROM security_events WHERE {where}", params)
    row = _one(cur)
    cur.close()
    return row["cnt"]


def check_rate_limit(uid, action):
    from bradsec import RATE_LIMITS
    cfg = RATE_LIMITS.get(action)
    if not cfg:
        return True
    conn = _get_conn()
    cur = conn.cursor()
    now = time.time()
    w_start = now - (now % cfg["window"])
    cur.execute(
        "SELECT count FROM rate_limit_counts WHERE uid = %s AND action = %s AND window_start = %s",
        (uid, action, w_start),
    )
    row = _one(cur)
    if row and row["count"] >= cfg["max"]:
        cur.close()
        return False
    if row:
        cur.execute(
            "UPDATE rate_limit_counts SET count = count + 1 WHERE uid = %s AND action = %s AND window_start = %s",
            (uid, action, w_start),
        )
    else:
        cur.execute(
            "INSERT INTO rate_limit_counts (uid, action, window_start, count) VALUES (%s, %s, %s, 1)",
            (uid, action, w_start),
        )
    conn.commit()
    cur.close()
    return True


def get_rate_limit_remaining(uid, action):
    from bradsec import RATE_LIMITS
    cfg = RATE_LIMITS.get(action)
    if not cfg:
        return -1
    conn = _get_conn()
    cur = conn.cursor()
    now = time.time()
    w_start = now - (now % cfg["window"])
    cur.execute(
        "SELECT count FROM rate_limit_counts WHERE uid = %s AND action = %s AND window_start = %s",
        (uid, action, w_start),
    )
    row = _one(cur)
    cur.close()
    used = row["count"] if row else 0
    return max(0, cfg["max"] - used)


def reset_rate_limit(uid, action):
    conn = _get_conn()
    cur = conn.cursor()
    now = time.time()
    from bradsec import RATE_LIMITS
    cfg = RATE_LIMITS.get(action, {"window": 3600})
    w_start = now - (now % cfg["window"])
    cur.execute(
        "DELETE FROM rate_limit_counts WHERE uid = %s AND action = %s AND window_start = %s",
        (uid, action, w_start),
    )
    conn.commit()
    cur.close()


def evaluate_transaction(sender_uid, recipient_uid, amount, tx_ref=None):
    conn = _get_conn()
    cur = conn.cursor()
    ref = tx_ref or f"FRAUD-{int(time.time())}-{sender_uid[:8]}"
    cur.execute(
        "INSERT INTO flagged_transactions (tx_ref, sender_uid, recipient_uid, amount, score, rules_triggered) VALUES (%s, %s, %s, %s, %s, %s)",
        (ref, sender_uid, recipient_uid, amount, 0, "[]"),
    )
    conn.commit()
    cur.close()


def get_flagged_transactions(status=None, limit=50, offset=0):
    conn = _get_conn()
    cur = conn.cursor()
    if status:
        cur.execute(
            "SELECT * FROM flagged_transactions WHERE status = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (status, limit, offset),
        )
    else:
        cur.execute("SELECT * FROM flagged_transactions ORDER BY created_at DESC LIMIT %s OFFSET %s", (limit, offset))
    rows = _dict_row(cur)
    cur.close()
    return rows


def resolve_flag(flag_id, status, reviewer_uid, note=None):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM flagged_transactions WHERE id = %s", (flag_id,))
    flag = _one(cur)
    if not flag:
        cur.close()
        return None
    cur.execute(
        "UPDATE flagged_transactions SET status = %s, reviewed_by = %s, reviewed_at = NOW(), resolution_note = %s WHERE id = %s",
        (status, reviewer_uid, note or "", flag_id),
    )
    conn.commit()
    cur.close()
    return flag


def get_flag_stats():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT status, COUNT(*) as cnt FROM flagged_transactions GROUP BY status")
    rows = _dict_row(cur)
    cur.close()
    stats = {r["status"]: r["cnt"] for r in rows}
    return {
        "open": stats.get("open", 0),
        "approved": stats.get("approved", 0),
        "blocked": stats.get("blocked", 0),
        "total": sum(stats.values()),
    }


def get_security_summary():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) as cnt FROM security_events WHERE severity IN ('high','critical') AND created_at >= NOW() - INTERVAL '24 hours'"
    )
    high = _one(cur)["cnt"]
    cur.execute("SELECT COUNT(*) as cnt FROM security_events WHERE created_at >= NOW() - INTERVAL '24 hours'")
    total_24h = _one(cur)["cnt"]
    cur.execute("SELECT * FROM security_events ORDER BY created_at DESC LIMIT 10")
    recent = _dict_row(cur)
    cur.close()
    return {
        "high_severity_24h": high,
        "total_events_24h": total_24h,
        "open_flags": get_flag_stats()["open"],
        "recent_events": recent,
    }


def close():
    global _conn
    if _conn:
        _conn.close()
        _conn = None
