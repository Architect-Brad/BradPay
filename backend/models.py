import sqlite3
import os
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.environ.get(
    "BRADPAY_DB_PATH",
    os.path.join(os.path.dirname(__file__), "bradpay.db"),
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT UNIQUE NOT NULL,
            email TEXT,
            display_name TEXT,
            phone TEXT,
            pin_hash TEXT NOT NULL,
            balance INTEGER NOT NULL DEFAULT 0,
            locked_balance INTEGER NOT NULL DEFAULT 0,
            kes_balance INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

                CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_uid TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('buy','sell')),
            price INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            filled INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_uid) REFERENCES users(firebase_uid)
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buy_order_id INTEGER NOT NULL,
            sell_order_id INTEGER NOT NULL,
            buyer_uid TEXT NOT NULL,
            seller_uid TEXT NOT NULL,
            amount INTEGER NOT NULL,
            price INTEGER NOT NULL,
            buyer_fee INTEGER NOT NULL DEFAULT 0,
            seller_fee INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (buy_order_id) REFERENCES orders(id),
            FOREIGN KEY (sell_order_id) REFERENCES orders(id)
        );

        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_uid);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_orders_type_price ON orders(type, price);
        CREATE INDEX IF NOT EXISTS idx_trades_buyer ON trades(buyer_uid);
        CREATE INDEX IF NOT EXISTS idx_trades_seller ON trades(seller_uid);

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_ref TEXT UNIQUE NOT NULL,
            sender_id INTEGER NOT NULL,
            recipient_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            fee INTEGER NOT NULL DEFAULT 0,
            type TEXT NOT NULL DEFAULT 'transfer',
            status TEXT NOT NULL DEFAULT 'pending',
            note TEXT,
            offline_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            synced_at TEXT,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (recipient_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender_id);
        CREATE INDEX IF NOT EXISTS idx_tx_recipient ON transactions(recipient_id);
        CREATE INDEX IF NOT EXISTS idx_tx_offline ON transactions(offline_id);
        CREATE INDEX IF NOT EXISTS idx_tx_status ON transactions(status);
        CREATE INDEX IF NOT EXISTS idx_users_firebase_uid ON users(firebase_uid);
        CREATE TABLE IF NOT EXISTS mpesa_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_uid TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('deposit','withdrawal')),
            phone TEXT NOT NULL,
            amount INTEGER NOT NULL,
            checkout_id TEXT,
            conversation_id TEXT,
            result_code INTEGER,
            result_desc TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT,
            FOREIGN KEY (user_uid) REFERENCES users(firebase_uid)
        );

        CREATE INDEX IF NOT EXISTS idx_mpesa_checkout ON mpesa_transactions(checkout_id);
        CREATE INDEX IF NOT EXISTS idx_mpesa_conversation ON mpesa_transactions(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_mpesa_user ON mpesa_transactions(user_uid);

        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firebase_uid TEXT UNIQUE NOT NULL,
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
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            verified_at TEXT,
            FOREIGN KEY (firebase_uid) REFERENCES users(firebase_uid)
        );

        CREATE TABLE IF NOT EXISTS agent_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_uid TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('float_topup','float_withdrawal','commission','cash_in','cash_out')),
            amount INTEGER NOT NULL,
            user_uid TEXT,
            commission INTEGER DEFAULT 0,
            reference TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (agent_uid) REFERENCES agents(firebase_uid)
        );

        CREATE TABLE IF NOT EXISTS tariffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('transfer','deposit','withdrawal','agent_commission','float_topup')),
            percentage INTEGER,
            flat_fee INTEGER,
            min_amount INTEGER,
            max_amount INTEGER,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN kes_balance INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    conn.commit()
    conn.close()


def create_user(firebase_uid, email=None, display_name=None, phone=None, pin="1234"):
    conn = get_db()
    try:
        pin_hash = generate_password_hash(pin)
        conn.execute(
            """INSERT INTO users (firebase_uid, email, display_name, phone, pin_hash)
               VALUES (?, ?, ?, ?, ?)""",
            (firebase_uid, email, display_name, phone, pin_hash),
        )
        conn.commit()
        user = conn.execute(
            "SELECT * FROM users WHERE firebase_uid = ?", (firebase_uid,)
        ).fetchone()
        return dict(user)
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_user_by_firebase_uid(firebase_uid):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE firebase_uid = ?", (firebase_uid,)
    ).fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return dict(user) if user else None


def verify_pin(firebase_uid, pin):
    conn = get_db()
    user = conn.execute(
        "SELECT pin_hash FROM users WHERE firebase_uid = ?", (firebase_uid,)
    ).fetchone()
    conn.close()
    if not user:
        return False
    return check_password_hash(user["pin_hash"], pin)


def get_balance(firebase_uid):
    conn = get_db()
    user = conn.execute(
        "SELECT balance FROM users WHERE firebase_uid = ?", (firebase_uid,)
    ).fetchone()
    conn.close()
    return user["balance"] if user else None


def create_transaction(sender_uid, recipient_uid, amount, note=None, offline_id=None):
    conn = get_db()
    try:
        sender = conn.execute(
            "SELECT id, firebase_uid, balance FROM users WHERE firebase_uid = ?", (sender_uid,)
        ).fetchone()
        if not sender:
            return {"error": "Sender not found"}, 404

        recipient = conn.execute(
            "SELECT id, balance FROM users WHERE firebase_uid = ?", (recipient_uid,)
        ).fetchone()
        if not recipient:
            return {"error": "Recipient not found"}, 404

        total_amount = amount
        if sender["balance"] < total_amount:
            return {"error": "Insufficient balance"}, 400

        fee = 0
        tx_ref = f"BRADPAY-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{sender['id']}-{recipient['id']}"

        conn.execute("BEGIN TRANSACTION")
        conn.execute(
            "UPDATE users SET balance = balance - ?, updated_at = datetime('now') WHERE id = ?",
            (total_amount, sender["id"]),
        )
        conn.execute(
            "UPDATE users SET balance = balance + ?, updated_at = datetime('now') WHERE id = ?",
            (amount, recipient["id"]),
        )
        conn.execute(
            """INSERT INTO transactions (tx_ref, sender_id, recipient_id, amount, fee, type, status, note, offline_id)
               VALUES (?, ?, ?, ?, ?, 'transfer', 'completed', ?, ?)""",
            (tx_ref, sender["id"], recipient["id"], amount, fee, note, offline_id),
        )
        conn.commit()

        tx = conn.execute(
            "SELECT * FROM transactions WHERE tx_ref = ?", (tx_ref,)
        ).fetchone()
        return dict(tx)
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        conn.close()


def get_transactions(firebase_uid, limit=50):
    conn = get_db()
    user = conn.execute(
        "SELECT id FROM users WHERE firebase_uid = ?", (firebase_uid,)
    ).fetchone()
    if not user:
        conn.close()
        return []
    user_id = user["id"]
    rows = conn.execute(
        """SELECT t.*,
                  u1.firebase_uid as sender_uid, u1.display_name as sender_name,
                  u2.firebase_uid as recipient_uid, u2.display_name as recipient_name
           FROM transactions t
           JOIN users u1 ON t.sender_id = u1.id
           JOIN users u2 ON t.recipient_id = u2.id
           WHERE t.sender_id = ? OR t.recipient_id = ?
           ORDER BY t.created_at DESC
           LIMIT ?""",
        (user_id, user_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_user_by_phone_or_email(identifier):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ? OR phone = ?",
        (identifier, identifier),
    ).fetchone()
    conn.close()
    return dict(user) if user else None


# ── BradTrade ──

def create_order(user_uid, order_type, price, amount):
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, balance, locked_balance FROM users WHERE firebase_uid = ?",
            (user_uid,),
        ).fetchone()
        if not user:
            return {"error": "User not found"}, 404

        if order_type == "sell":
            available = user["balance"] - (user["locked_balance"] or 0)
            if available < amount:
                return {"error": "Insufficient available balance"}, 400
            conn.execute(
                "UPDATE users SET locked_balance = COALESCE(locked_balance, 0) + ? WHERE firebase_uid = ?",
                (amount, user_uid),
            )

        conn.execute(
            """INSERT INTO orders (user_uid, type, price, amount)
               VALUES (?, ?, ?, ?)""",
            (user_uid, order_type, price, amount),
        )
        conn.commit()
        order = conn.execute(
            "SELECT * FROM orders WHERE id = last_insert_rowid()"
        ).fetchone()
        return dict(order)
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        conn.close()


def cancel_order(user_uid, order_id):
    conn = get_db()
    try:
        order = conn.execute(
            "SELECT * FROM orders WHERE id = ? AND user_uid = ?",
            (order_id, user_uid),
        ).fetchone()
        if not order:
            return {"error": "Order not found"}, 404
        if order["status"] not in ("open", "partial"):
            return {"error": "Order cannot be cancelled"}, 400

        remaining = order["amount"] - order["filled"]
        if order["type"] == "sell" and remaining > 0:
            conn.execute(
                "UPDATE users SET locked_balance = MAX(COALESCE(locked_balance,0) - ?, 0) WHERE firebase_uid = ?",
                (remaining, user_uid),
            )

        conn.execute(
            "UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,)
        )
        conn.commit()
        return {"message": "Order cancelled", "order_id": order_id}
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        conn.close()


def get_orders(user_uid, status_filter=None):
    conn = get_db()
    try:
        if status_filter:
            rows = conn.execute(
                "SELECT * FROM orders WHERE user_uid = ? AND status = ? ORDER BY created_at DESC",
                (user_uid, status_filter),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM orders WHERE user_uid = ? ORDER BY created_at DESC",
                (user_uid,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_order_book(limit=15):
    conn = get_db()
    try:
        buys = conn.execute(
            """SELECT * FROM orders WHERE type='buy' AND status IN ('open','partial')
               ORDER BY price DESC, created_at ASC LIMIT ?""",
            (limit,),
        ).fetchall()

        sells = conn.execute(
            """SELECT * FROM orders WHERE type='sell' AND status IN ('open','partial')
               ORDER BY price ASC, created_at ASC LIMIT ?""",
            (limit,),
        ).fetchall()

        buy_agg = {}
        for o in buys:
            d = dict(o)
            p = d["price"]
            remaining = d["amount"] - d["filled"]
            if p in buy_agg:
                buy_agg[p]["amount"] += remaining
                buy_agg[p]["count"] += 1
            else:
                buy_agg[p] = {"price": p, "amount": remaining, "count": 1}

        sell_agg = {}
        for o in sells:
            d = dict(o)
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
    finally:
        conn.close()


def execute_trade(buy_order_id, sell_order_id, buyer_uid, seller_uid, amount, price):
    conn = get_db()
    try:
        buyer_fee = max(1, amount // 1000)
        seller_fee = max(1, amount // 1000)
        seller_payout = amount - seller_fee

        conn.execute("BEGIN TRANSACTION")

        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE firebase_uid = ?",
            (amount - buyer_fee, buyer_uid),
        )
        conn.execute(
            "UPDATE users SET balance = balance - ?, locked_balance = MAX(COALESCE(locked_balance,0) - ?, 0) WHERE firebase_uid = ?",
            (amount, amount, seller_uid),
        )

        conn.execute(
            """INSERT INTO trades (buy_order_id, sell_order_id, buyer_uid, seller_uid, amount, price, buyer_fee, seller_fee)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (buy_order_id, sell_order_id, buyer_uid, seller_uid, amount, price, buyer_fee, seller_fee),
        )

        conn.execute(
            "UPDATE orders SET filled = filled + ?, status = CASE WHEN filled + ? >= amount THEN 'filled' ELSE 'partial' END WHERE id = ?",
            (amount, amount, buy_order_id),
        )
        conn.execute(
            "UPDATE orders SET filled = filled + ?, status = CASE WHEN filled + ? >= amount THEN 'filled' ELSE 'partial' END WHERE id = ?",
            (amount, amount, sell_order_id),
        )

        conn.commit()
        return {"success": True, "amount": amount, "price": price}
    except Exception as e:
        conn.rollback()
        return {"error": str(e), "success": False}
    finally:
        conn.close()


def get_trades(user_uid=None, limit=50):
    conn = get_db()
    try:
        if user_uid:
            rows = conn.execute(
                """SELECT * FROM trades WHERE buyer_uid = ? OR seller_uid = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_uid, user_uid, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_user_with_locked(firebase_uid):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE firebase_uid = ?", (firebase_uid,)
    ).fetchone()
    conn.close()
    return dict(user) if user else None


# ── M-PESA Daraja ──

def create_mpesa_transaction(user_uid, type_, phone, amount, checkout_id=None, conversation_id=None):
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO mpesa_transactions (user_uid, type, phone, amount, checkout_id, conversation_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_uid, type_, phone, amount, checkout_id, conversation_id),
        )
        conn.commit()
        tx = conn.execute(
            "SELECT * FROM mpesa_transactions WHERE id = last_insert_rowid()"
        ).fetchone()
        return dict(tx)
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}
    finally:
        conn.close()


def get_mpesa_transactions(user_uid, limit=50):
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT * FROM mpesa_transactions WHERE user_uid = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_uid, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_mpesa_transaction_by_checkout_id(checkout_id):
    conn = get_db()
    tx = conn.execute(
        "SELECT * FROM mpesa_transactions WHERE checkout_id = ?", (checkout_id,)
    ).fetchone()
    conn.close()
    return dict(tx) if tx else None


def get_mpesa_transaction_by_conversation_id(conversation_id):
    conn = get_db()
    tx = conn.execute(
        "SELECT * FROM mpesa_transactions WHERE conversation_id = ?", (conversation_id,)
    ).fetchone()
    conn.close()
    return dict(tx) if tx else None


def update_mpesa_transaction_status(identifier, result_code, result_desc):
    conn = get_db()
    status = "completed" if result_code == 0 else "failed"
    conn.execute(
        """UPDATE mpesa_transactions
           SET result_code = ?, result_desc = ?, status = ?, updated_at = datetime('now')
           WHERE checkout_id = ? OR conversation_id = ?""",
        (result_code, result_desc, status, identifier, identifier),
    )
    conn.commit()
    conn.close()


def update_kes_balance(user_uid, amount_delta):
    conn = get_db()
    conn.execute(
        """UPDATE users SET kes_balance = MAX(COALESCE(kes_balance, 0) + ?, 0),
            updated_at = datetime('now') WHERE firebase_uid = ?""",
        (amount_delta, user_uid),
    )
    conn.commit()
    conn.close()


def get_kes_balance(user_uid):
    conn = get_db()
    user = conn.execute(
        "SELECT kes_balance FROM users WHERE firebase_uid = ?", (user_uid,)
    ).fetchone()
    conn.close()
    return user["kes_balance"] if user else None


# ── Agent functions ──

def create_agent(firebase_uid, business_name, contact_phone=None, email=None, id_number=None, kra_pin=None, location=None):
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO agents (firebase_uid, business_name, contact_phone, email, id_number, kra_pin, location)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (firebase_uid, business_name, contact_phone, email, id_number, kra_pin, location),
        )
        conn.commit()
        agent = conn.execute("SELECT * FROM agents WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(agent)
    except Exception as e:
        conn.close()
        return {"error": str(e)}
    finally:
        conn.close()


def get_agent(firebase_uid):
    conn = get_db()
    agent = conn.execute(
        "SELECT * FROM agents WHERE firebase_uid = ?", (firebase_uid,)
    ).fetchone()
    conn.close()
    return dict(agent) if agent else None


def get_agent_by_id(agent_id):
    conn = get_db()
    agent = conn.execute(
        "SELECT * FROM agents WHERE id = ?", (agent_id,)
    ).fetchone()
    conn.close()
    return dict(agent) if agent else None


def update_agent_status(firebase_uid, status):
    conn = get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    verified = f", verified_at = '{now}'" if status == "active" else ""
    conn.execute(
        f"UPDATE agents SET status = ?{verified} WHERE firebase_uid = ?",
        (status, firebase_uid),
    )
    conn.commit()
    conn.close()


def update_agent_float(agent_uid, amount_delta):
    conn = get_db()
    conn.execute(
        """UPDATE agents SET float_balance = MAX(COALESCE(float_balance, 0) + ?, 0)
           WHERE firebase_uid = ?""",
        (amount_delta, agent_uid),
    )
    conn.commit()
    conn.close()


def get_all_agents(status=None):
    conn = get_db()
    if status:
        rows = conn.execute("SELECT * FROM agents WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM agents ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_agent_transaction(agent_uid, type_, amount, user_uid=None, commission=0, reference=None):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO agent_transactions (agent_uid, type, amount, user_uid, commission, reference)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (agent_uid, type_, amount, user_uid, commission, reference),
    )
    conn.commit()
    tx = conn.execute("SELECT * FROM agent_transactions WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(tx)


def get_agent_transactions(agent_uid, limit=50):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM agent_transactions WHERE agent_uid = ? ORDER BY created_at DESC LIMIT ?",
        (agent_uid, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Tariff functions ──

def create_tariff(name, type_, percentage=None, flat_fee=None, min_amount=None, max_amount=None):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO tariffs (name, type, percentage, flat_fee, min_amount, max_amount)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, type_, percentage, flat_fee, min_amount, max_amount),
    )
    conn.commit()
    t = conn.execute("SELECT * FROM tariffs WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(t)


def get_active_tariffs():
    conn = get_db()
    rows = conn.execute("SELECT * FROM tariffs WHERE is_active = 1 ORDER BY type, name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tariff_by_type(type_):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM tariffs WHERE type = ? AND is_active = 1 ORDER BY min_amount ASC",
        (type_,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_tariff(tariff_id, **kwargs):
    conn = get_db()
    fields = {k: v for k, v in kwargs.items() if v is not None}
    if not fields:
        conn.close()
        return None
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [tariff_id]
    conn.execute(f"UPDATE tariffs SET {sets} WHERE id = ?", vals)
    conn.commit()
    t = conn.execute("SELECT * FROM tariffs WHERE id = ?", (tariff_id,)).fetchone()
    conn.close()
    return dict(t)
