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

        CREATE TABLE IF NOT EXISTS ledger_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            chain_json TEXT NOT NULL,
            pending_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN kes_balance INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    conn.commit()
    conn.close()


def init_bradsec():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            uid TEXT,
            details TEXT,
            ip_address TEXT,
            user_agent TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_sec_events_uid ON security_events(uid);
        CREATE INDEX IF NOT EXISTS idx_sec_events_type ON security_events(event_type);
        CREATE INDEX IF NOT EXISTS idx_sec_events_severity ON security_events(severity);
        CREATE INDEX IF NOT EXISTS idx_sec_events_created ON security_events(created_at);

        CREATE TABLE IF NOT EXISTS flagged_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_ref TEXT NOT NULL,
            sender_uid TEXT,
            recipient_uid TEXT,
            amount INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            rules_triggered TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            reviewed_by TEXT,
            reviewed_at TEXT,
            resolution_note TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_flags_status ON flagged_transactions(status);
        CREATE INDEX IF NOT EXISTS idx_flags_tx ON flagged_transactions(tx_ref);

        CREATE TABLE IF NOT EXISTS bradsec_settings (
            key TEXT PRIMARY KEY NOT NULL,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS rate_limit_counts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL,
            action TEXT NOT NULL,
            window_start REAL NOT NULL,
            count INTEGER NOT NULL DEFAULT 1,
            UNIQUE(uid, action, window_start)
        );
        CREATE INDEX IF NOT EXISTS idx_rate_limit_lookup ON rate_limit_counts(uid, action, window_start);
    """)
    conn.commit()
    conn.close()


from validators import validate_pin as _validate_pin


def create_user(firebase_uid, email=None, display_name=None, phone=None, pin=None):
    pin = _validate_pin(pin)
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


def calculate_fee(type_, amount):
    """Look up the active tariff for this transaction type and compute the
    fee. `percentage` is stored in basis points (100 = 1%). Falls back to 0
    if no tariff is configured, so this never blocks a transaction."""
    tiers = get_tariff_by_type(type_)
    for tier in tiers:
        min_amt = tier["min_amount"] or 0
        max_amt = tier["max_amount"]
        if amount < min_amt:
            continue
        if max_amt is not None and amount > max_amt:
            continue
        flat = tier["flat_fee"] or 0
        pct = tier["percentage"] or 0
        return flat + (amount * pct) // 10000
    return 0


def _get_or_create_fees_account(conn):
    row = conn.execute(
        "SELECT id FROM users WHERE firebase_uid = '__fees__'"
    ).fetchone()
    if row:
        return row["id"]
    conn.execute(
        "INSERT INTO users (firebase_uid, display_name, pin_hash) "
        "VALUES ('__fees__', 'BradPay Fees', 'x')"
    )
    return conn.execute(
        "SELECT id FROM users WHERE firebase_uid = '__fees__'"
    ).fetchone()["id"]


def create_transaction(sender_uid, recipient_uid, amount, note=None, offline_id=None):
    if amount is None or amount <= 0:
        return {"error": "Amount must be a positive integer"}, 400

    if sender_uid == recipient_uid:
        return {"error": "Cannot send money to yourself"}, 400

    conn = get_db()
    try:
        # BEGIN IMMEDIATE grabs the write lock up front so no other writer
        # can interleave between our balance check and our balance update -
        # this closes the race where two concurrent transfers from the same
        # account could both pass the balance check before either commits.
        conn.execute("BEGIN IMMEDIATE")

        # Offline / retry idempotency: same offline_id must not double-debit.
        if offline_id:
            existing = conn.execute(
                "SELECT * FROM transactions WHERE offline_id = ? AND sender_id = "
                "(SELECT id FROM users WHERE firebase_uid = ?)",
                (offline_id, sender_uid),
            ).fetchone()
            if existing:
                conn.commit()
                tx = dict(existing)
                tx["sender_uid"] = sender_uid
                recip = conn.execute(
                    "SELECT firebase_uid FROM users WHERE id = ?", (tx["recipient_id"],)
                ).fetchone()
                tx["recipient_uid"] = recip["firebase_uid"] if recip else recipient_uid
                tx["idempotent_replay"] = True
                return tx

        sender = conn.execute(
            "SELECT id, firebase_uid, balance FROM users WHERE firebase_uid = ?", (sender_uid,)
        ).fetchone()
        if not sender:
            conn.rollback()
            return {"error": "Sender not found"}, 404

        recipient = conn.execute(
            "SELECT id, firebase_uid, balance FROM users WHERE firebase_uid = ?", (recipient_uid,)
        ).fetchone()
        if not recipient:
            conn.rollback()
            return {"error": "Recipient not found"}, 404

        fee = calculate_fee("transfer", amount)
        total_debit = amount + fee

        if sender["balance"] < total_debit:
            conn.rollback()
            return {"error": "Insufficient balance"}, 400

        tx_ref = f"BRADPAY-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{sender['id']}-{recipient['id']}"

        # Conditional UPDATE re-checks the balance atomically at write time.
        # If another transaction already drained the balance since our
        # SELECT above, rowcount will be 0 and we abort instead of allowing
        # an overdraft.
        cur = conn.execute(
            "UPDATE users SET balance = balance - ?, updated_at = datetime('now') "
            "WHERE id = ? AND balance >= ?",
            (total_debit, sender["id"], total_debit),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return {"error": "Insufficient balance"}, 400

        conn.execute(
            "UPDATE users SET balance = balance + ?, updated_at = datetime('now') WHERE id = ?",
            (amount, recipient["id"]),
        )
        if fee > 0:
            fees_account_id = _get_or_create_fees_account(conn)
            conn.execute(
                "UPDATE users SET balance = balance + ?, updated_at = datetime('now') WHERE id = ?",
                (fee, fees_account_id),
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
        result = dict(tx)
        # Ledger / clients expect UIDs, not internal integer ids.
        result["sender_uid"] = sender_uid
        result["recipient_uid"] = recipient_uid
        result["sender_name"] = None
        result["recipient_name"] = None
        return result
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
        conn.execute("BEGIN IMMEDIATE")
        user = conn.execute(
            "SELECT id, balance, locked_balance FROM users WHERE firebase_uid = ?",
            (user_uid,),
        ).fetchone()
        if not user:
            conn.rollback()
            return {"error": "User not found"}, 404

        # Both buy and sell lock `amount` of available balance so bids cannot
        # overcommit capital and asks cannot sell what they don't have.
        available = user["balance"] - (user["locked_balance"] or 0)
        if available < amount:
            conn.rollback()
            return {"error": "Insufficient available balance"}, 400
        cur = conn.execute(
            "UPDATE users SET locked_balance = COALESCE(locked_balance, 0) + ? "
            "WHERE firebase_uid = ? AND balance - COALESCE(locked_balance, 0) >= ?",
            (amount, user_uid, amount),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return {"error": "Insufficient available balance"}, 400

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
        # Both buy and sell lock funds; release remaining lock on cancel.
        if remaining > 0:
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
    if buyer_uid == seller_uid:
        return {"error": "Cannot match orders from the same user", "success": False}

    conn = get_db()
    try:
        buyer_fee = max(1, amount // 1000)
        seller_fee = max(1, amount // 1000)

        conn.execute("BEGIN IMMEDIATE")

        # Seller: release lock and debit the filled amount (asset transfer).
        # Buyer: release bid lock (collateral) and credit net amount from seller.
        cur = conn.execute(
            "UPDATE users SET balance = balance - ?, "
            "locked_balance = MAX(COALESCE(locked_balance,0) - ?, 0) "
            "WHERE firebase_uid = ? AND balance >= ? AND COALESCE(locked_balance,0) >= ?",
            (amount, amount, seller_uid, amount, amount),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return {"error": "Seller insufficient locked balance", "success": False}

        # Buyer unlocks bid collateral and receives net fill; fees conserved.
        net_to_buyer = amount - buyer_fee - seller_fee
        if net_to_buyer < 0:
            conn.rollback()
            return {"error": "Fees exceed trade amount", "success": False}
        cur = conn.execute(
            "UPDATE users SET locked_balance = MAX(COALESCE(locked_balance,0) - ?, 0), "
            "balance = balance + ? "
            "WHERE firebase_uid = ? AND COALESCE(locked_balance,0) >= ?",
            (amount, net_to_buyer, buyer_uid, amount),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return {"error": "Buyer insufficient locked balance", "success": False}

        fees_id = _get_or_create_fees_account(conn)
        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (buyer_fee + seller_fee, fees_id),
        )

        conn.execute(
            """INSERT INTO trades (buy_order_id, sell_order_id, buyer_uid, seller_uid, amount, price, buyer_fee, seller_fee)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (int(buy_order_id), int(sell_order_id), buyer_uid, seller_uid, amount, price, buyer_fee, seller_fee),
        )

        conn.execute(
            "UPDATE orders SET filled = filled + ?, status = CASE WHEN filled + ? >= amount THEN 'filled' ELSE 'partial' END WHERE id = ?",
            (amount, amount, int(buy_order_id)),
        )
        conn.execute(
            "UPDATE orders SET filled = filled + ?, status = CASE WHEN filled + ? >= amount THEN 'filled' ELSE 'partial' END WHERE id = ?",
            (amount, amount, int(sell_order_id)),
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
    """Legacy non-atomic status update. Prefer claim_mpesa_callback for money moves."""
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


def claim_mpesa_callback(identifier, result_code, result_desc):
    """Atomically claim a pending M-PESA tx for callback processing.

    Returns (tx_dict, claimed: bool). claimed is False if already finalized
    (idempotent replay) or not found.
    """
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        tx = conn.execute(
            """SELECT * FROM mpesa_transactions
               WHERE checkout_id = ? OR conversation_id = ?""",
            (identifier, identifier),
        ).fetchone()
        if not tx:
            conn.rollback()
            return None, False
        tx = dict(tx)
        if tx["status"] != "pending":
            conn.rollback()
            return tx, False
        status = "completed" if result_code == 0 else "failed"
        conn.execute(
            """UPDATE mpesa_transactions
               SET result_code = ?, result_desc = ?, status = ?, updated_at = datetime('now')
               WHERE id = ? AND status = 'pending'""",
            (result_code, result_desc, status, tx["id"]),
        )
        if conn.total_changes == 0:
            conn.rollback()
            return tx, False
        conn.commit()
        tx["status"] = status
        tx["result_code"] = result_code
        tx["result_desc"] = result_desc
        return tx, True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_kes_balance(user_uid, amount_delta):
    """Credit/debit the main wallet (`balance`).

    kes_balance is kept in sync for backward-compatible reads. Debits use a
    conditional UPDATE so concurrent withdrawals cannot overdraw (returns False
    if insufficient funds). Credits always return True if the user exists.
    """
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if amount_delta < 0:
            need = -amount_delta
            cur = conn.execute(
                """UPDATE users SET balance = balance - ?,
                       kes_balance = MAX(COALESCE(kes_balance, 0) - ?, 0),
                       updated_at = datetime('now')
                   WHERE firebase_uid = ? AND balance >= ?""",
                (need, need, user_uid, need),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return False
        else:
            cur = conn.execute(
                """UPDATE users SET balance = balance + ?,
                       kes_balance = COALESCE(kes_balance, 0) + ?,
                       updated_at = datetime('now')
                   WHERE firebase_uid = ?""",
                (amount_delta, amount_delta, user_uid),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return False
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_kes_balance(user_uid):
    """Return spendable wallet balance (unified with P2P `balance`)."""
    conn = get_db()
    user = conn.execute(
        "SELECT balance FROM users WHERE firebase_uid = ?", (user_uid,)
    ).fetchone()
    conn.close()
    return user["balance"] if user else None


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
    """Non-atomic float adjust. Prefer atomic_* helpers for money moves."""
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if amount_delta < 0:
            need = -amount_delta
            cur = conn.execute(
                """UPDATE agents SET float_balance = float_balance - ?
                   WHERE firebase_uid = ? AND float_balance >= ?""",
                (need, agent_uid, need),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return False
        else:
            cur = conn.execute(
                """UPDATE agents SET float_balance = COALESCE(float_balance, 0) + ?
                   WHERE firebase_uid = ?""",
                (amount_delta, agent_uid),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return False
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def agent_float_topup(user_uid, amount):
    """Move `amount` from user wallet into agent float atomically."""
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        agent = conn.execute(
            "SELECT * FROM agents WHERE firebase_uid = ?", (user_uid,)
        ).fetchone()
        if not agent or agent["status"] != "active":
            conn.rollback()
            return {"error": "Agent not active"}, 403
        cur = conn.execute(
            """UPDATE users SET balance = balance - ?,
                   kes_balance = MAX(COALESCE(kes_balance,0) - ?, 0),
                   updated_at = datetime('now')
               WHERE firebase_uid = ? AND balance >= ?""",
            (amount, amount, user_uid, amount),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return {"error": "Insufficient balance"}, 400
        conn.execute(
            "UPDATE agents SET float_balance = COALESCE(float_balance,0) + ? WHERE firebase_uid = ?",
            (amount, user_uid),
        )
        conn.execute(
            """INSERT INTO agent_transactions (agent_uid, type, amount, reference)
               VALUES (?, 'float_topup', ?, ?)""",
            (user_uid, amount, f"float_{user_uid[:8]}_{amount}"),
        )
        conn.commit()
        return {"message": "Float topped up", "amount": amount}
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        conn.close()


def agent_float_transfer(from_uid, to_uid, amount):
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        from_agent = conn.execute(
            "SELECT * FROM agents WHERE firebase_uid = ?", (from_uid,)
        ).fetchone()
        to_agent = conn.execute(
            "SELECT * FROM agents WHERE firebase_uid = ?", (to_uid,)
        ).fetchone()
        if not from_agent:
            conn.rollback()
            return {"error": "You are not an agent"}, 404
        if from_agent["status"] != "active":
            conn.rollback()
            return {"error": "Your agent account is not active"}, 403
        if not to_agent:
            conn.rollback()
            return {"error": "Recipient agent not found"}, 404
        if to_agent["status"] != "active":
            conn.rollback()
            return {"error": "Recipient agent is not active"}, 403
        cur = conn.execute(
            "UPDATE agents SET float_balance = float_balance - ? WHERE firebase_uid = ? AND float_balance >= ?",
            (amount, from_uid, amount),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return {"error": "Insufficient float balance"}, 400
        conn.execute(
            "UPDATE agents SET float_balance = COALESCE(float_balance,0) + ? WHERE firebase_uid = ?",
            (amount, to_uid),
        )
        ref = f"float_xfer_{from_uid[:8]}_{to_uid[:8]}_{amount}"
        conn.execute(
            """INSERT INTO agent_transactions (agent_uid, type, amount, user_uid, reference)
               VALUES (?, 'float_withdrawal', ?, ?, ?)""",
            (from_uid, amount, to_uid, ref),
        )
        conn.execute(
            """INSERT INTO agent_transactions (agent_uid, type, amount, user_uid, reference)
               VALUES (?, 'float_topup', ?, ?, ?)""",
            (to_uid, amount, from_uid, ref),
        )
        conn.commit()
        return {
            "message": f"Float transfer of KES {amount / 100:.2f} sent",
            "amount": amount,
            "from_agent": from_uid,
            "to_agent": to_uid,
        }
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        conn.close()


def agent_cash_in(agent_uid, user_phone, amount):
    """Agent float → user wallet. Commission taken from amount (conserved)."""
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        agent = conn.execute(
            "SELECT * FROM agents WHERE firebase_uid = ?", (agent_uid,)
        ).fetchone()
        if not agent or agent["status"] != "active":
            conn.rollback()
            return {"error": "Agent not active"}, 403
        user = conn.execute(
            "SELECT * FROM users WHERE phone = ? OR email = ?",
            (user_phone, user_phone),
        ).fetchone()
        if not user:
            conn.rollback()
            return {"error": "User not found"}, 404

        tiers = conn.execute(
            "SELECT * FROM tariffs WHERE type = 'agent_commission' AND is_active = 1 ORDER BY min_amount ASC"
        ).fetchall()
        commission = 0
        for t in tiers:
            min_amt = t["min_amount"] or 0
            max_amt = t["max_amount"]
            if amount < min_amt:
                continue
            if max_amt is not None and amount > max_amt:
                continue
            flat = t["flat_fee"] or 0
            pct = t["percentage"] or 0
            commission = flat + (amount * pct) // 10000
            break
        if commission >= amount:
            commission = 0
        user_credit = amount - commission

        cur = conn.execute(
            "UPDATE agents SET float_balance = float_balance - ? WHERE firebase_uid = ? AND float_balance >= ?",
            (amount, agent_uid, amount),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return {"error": "Insufficient float"}, 400

        # Net float: -amount + commission (commission retained by agent from the cash-in).
        if commission > 0:
            conn.execute(
                """UPDATE agents SET float_balance = COALESCE(float_balance,0) + ?,
                       total_commission_earned = COALESCE(total_commission_earned,0) + ?
                   WHERE firebase_uid = ?""",
                (commission, commission, agent_uid),
            )

        conn.execute(
            """UPDATE users SET balance = balance + ?,
                   kes_balance = COALESCE(kes_balance,0) + ?,
                   updated_at = datetime('now')
               WHERE firebase_uid = ?""",
            (user_credit, user_credit, user["firebase_uid"]),
        )
        conn.execute(
            """INSERT INTO agent_transactions (agent_uid, type, amount, user_uid, commission, reference)
               VALUES (?, 'cash_in', ?, ?, ?, ?)""",
            (agent_uid, amount, user["firebase_uid"], commission, f"cashin_{user_phone}"),
        )
        if commission > 0:
            conn.execute(
                """INSERT INTO agent_transactions (agent_uid, type, amount, reference)
                   VALUES (?, 'commission', ?, ?)""",
                (agent_uid, commission, f"comm_{agent_uid[:8]}_{amount}"),
            )
        conn.commit()
        return {
            "message": "Cash-in successful",
            "amount": amount,
            "credited": user_credit,
            "commission": commission,
        }
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
        conn.close()


def agent_cash_out(agent_uid, user_phone, amount):
    """User wallet → agent float atomically."""
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        agent = conn.execute(
            "SELECT * FROM agents WHERE firebase_uid = ?", (agent_uid,)
        ).fetchone()
        if not agent or agent["status"] != "active":
            conn.rollback()
            return {"error": "Agent not active"}, 403
        user = conn.execute(
            "SELECT * FROM users WHERE phone = ? OR email = ?",
            (user_phone, user_phone),
        ).fetchone()
        if not user:
            conn.rollback()
            return {"error": "User not found"}, 404
        cur = conn.execute(
            """UPDATE users SET balance = balance - ?,
                   kes_balance = MAX(COALESCE(kes_balance,0) - ?, 0),
                   updated_at = datetime('now')
               WHERE firebase_uid = ? AND balance >= ?""",
            (amount, amount, user["firebase_uid"], amount),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return {"error": "User insufficient balance"}, 400
        conn.execute(
            "UPDATE agents SET float_balance = COALESCE(float_balance,0) + ? WHERE firebase_uid = ?",
            (amount, agent_uid),
        )
        conn.execute(
            """INSERT INTO agent_transactions (agent_uid, type, amount, user_uid, reference)
               VALUES (?, 'cash_out', ?, ?, ?)""",
            (agent_uid, amount, user["firebase_uid"], f"cashout_{user_phone}"),
        )
        conn.commit()
        return {"message": "Cash-out successful", "amount": amount}
    except Exception as e:
        conn.rollback()
        return {"error": str(e)}, 500
    finally:
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


# ── Ledger persistence ──
# The ledger chain lives in the same database as everything else instead of
# a bare JSON file on local disk. A local file (as used previously) does not
# survive across instances/cold starts on serverless platforms unless it's
# backed by something durable - storing it here means the ledger persists
# wherever DATABASE_URL already points (which for production should be
# Postgres, not SQLite - see README deployment notes).

import json as _json


def save_ledger_state(chain, pending):
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO ledger_state (id, chain_json, pending_json, updated_at)
               VALUES (1, ?, ?, datetime('now'))
               ON CONFLICT(id) DO UPDATE SET
                 chain_json = excluded.chain_json,
                 pending_json = excluded.pending_json,
                 updated_at = datetime('now')""",
            (_json.dumps(chain), _json.dumps(pending)),
        )
        conn.commit()
    finally:
        conn.close()


def load_ledger_state():
    conn = get_db()
    try:
        row = conn.execute("SELECT chain_json, pending_json FROM ledger_state WHERE id = 1").fetchone()
        if not row:
            return None
        return _json.loads(row["chain_json"]), _json.loads(row["pending_json"])
    finally:
        conn.close()
