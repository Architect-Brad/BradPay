import os
import json
import time
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

from .backend import StorageBackend

logger = logging.getLogger(__name__)

BRADSEC_EVENT_TYPES = (
    "login_success", "login_failure", "registration", "logout",
    "send", "receive", "deposit", "withdrawal",
    "admin_credit", "admin_debit",
    "agent_cash_in", "agent_cash_out", "float_topup", "float_transfer",
    "rate_limit_hit", "fraud_flag", "fraud_resolve",
    "pin_change", "pin_failure",
    "suspicious_ip", "suspicious_device",
)

BRADSEC_SEVERITIES = ("info", "low", "medium", "high", "critical")

FRAUD_RULES = {
    "velocity": {"label": "High transaction velocity", "severity": "high", "score": 40},
    "amount_anomaly": {"label": "Unusually large transaction", "severity": "high", "score": 35},
    "new_account": {"label": "New account — elevated risk", "severity": "medium", "score": 25},
    "rapid_recipient": {"label": "Rapid same-recipient transfers", "severity": "medium", "score": 30},
    "balance_drain": {"label": "Balance drain attempt", "severity": "medium", "score": 20},
    "unusual_hours": {"label": "Transaction during unusual hours", "severity": "low", "score": 10},
    "round_numbers": {"label": "Pattern — round number amounts", "severity": "low", "score": 5},
}

RATE_LIMITS = {
    "send":          {"max": 10, "window": 3600},
    "login":         {"max": 5,  "window": 900},
    "register":      {"max": 3,  "window": 3600},
    "stkpush":       {"max": 3,  "window": 300},
    "cash_in":       {"max": 20, "window": 3600},
    "cash_out":      {"max": 20, "window": 3600},
    "admin_action":  {"max": 30, "window": 3600},
}

FLAG_THRESHOLD = 40


class SqliteBackend(StorageBackend):

    def __init__(self, db_path=None):
        self._db_path = db_path or os.environ.get(
            "BRADPAY_DB_PATH",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "bradpay.db"),
        )

    def _get_db(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ── Schema ──

    def init_schema(self):
        conn = self._get_db()
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
        try:
            conn.execute("ALTER TABLE users ADD COLUMN kes_balance INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        conn.commit()
        conn.close()

    # ── Users ──

    def create_user(self, firebase_uid, email=None, display_name=None, phone=None, pin="1234"):
        conn = self._get_db()
        try:
            pin_hash = generate_password_hash(pin)
            conn.execute(
                "INSERT INTO users (firebase_uid, email, display_name, phone, pin_hash) VALUES (?, ?, ?, ?, ?)",
                (firebase_uid, email, display_name, phone, pin_hash),
            )
            conn.commit()
            user = conn.execute("SELECT * FROM users WHERE firebase_uid = ?", (firebase_uid,)).fetchone()
            return dict(user)
        except sqlite3.IntegrityError:
            return None
        finally:
            conn.close()

    def get_user_by_firebase_uid(self, firebase_uid):
        conn = self._get_db()
        user = conn.execute("SELECT * FROM users WHERE firebase_uid = ?", (firebase_uid,)).fetchone()
        conn.close()
        return dict(user) if user else None

    def get_user_by_id(self, user_id):
        conn = self._get_db()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        return dict(user) if user else None

    def verify_pin(self, firebase_uid, pin):
        conn = self._get_db()
        user = conn.execute("SELECT pin_hash FROM users WHERE firebase_uid = ?", (firebase_uid,)).fetchone()
        conn.close()
        if not user:
            return False
        return check_password_hash(user["pin_hash"], pin)

    def get_balance(self, firebase_uid):
        conn = self._get_db()
        user = conn.execute("SELECT balance FROM users WHERE firebase_uid = ?", (firebase_uid,)).fetchone()
        conn.close()
        return user["balance"] if user else None

    def get_user_by_phone_or_email(self, identifier):
        conn = self._get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE email = ? OR phone = ?",
            (identifier, identifier),
        ).fetchone()
        conn.close()
        return dict(user) if user else None

    def get_user_with_locked(self, firebase_uid):
        conn = self._get_db()
        user = conn.execute("SELECT * FROM users WHERE firebase_uid = ?", (firebase_uid,)).fetchone()
        conn.close()
        return dict(user) if user else None

    def update_kes_balance(self, user_uid, amount_delta):
        conn = self._get_db()
        conn.execute(
            "UPDATE users SET kes_balance = MAX(COALESCE(kes_balance, 0) + ?, 0), updated_at = datetime('now') WHERE firebase_uid = ?",
            (amount_delta, user_uid),
        )
        conn.commit()
        conn.close()

    def get_kes_balance(self, user_uid):
        conn = self._get_db()
        user = conn.execute("SELECT kes_balance FROM users WHERE firebase_uid = ?", (user_uid,)).fetchone()
        conn.close()
        return user["kes_balance"] if user else None

    # ── Transactions ──

    def create_transaction(self, sender_uid, recipient_uid, amount, note=None, offline_id=None):
        conn = self._get_db()
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
            if sender["balance"] < amount:
                return {"error": "Insufficient balance"}, 400
            fee = 0
            tx_ref = f"BRADPAY-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{sender['id']}-{recipient['id']}"
            conn.execute("BEGIN TRANSACTION")
            conn.execute(
                "UPDATE users SET balance = balance - ?, updated_at = datetime('now') WHERE id = ?",
                (amount, sender["id"]),
            )
            conn.execute(
                "UPDATE users SET balance = balance + ?, updated_at = datetime('now') WHERE id = ?",
                (amount, recipient["id"]),
            )
            conn.execute(
                "INSERT INTO transactions (tx_ref, sender_id, recipient_id, amount, fee, type, status, note, offline_id) VALUES (?, ?, ?, ?, ?, 'transfer', 'completed', ?, ?)",
                (tx_ref, sender["id"], recipient["id"], amount, fee, note, offline_id),
            )
            conn.commit()
            tx = conn.execute("SELECT * FROM transactions WHERE tx_ref = ?", (tx_ref,)).fetchone()
            return dict(tx)
        except Exception as e:
            conn.rollback()
            return {"error": str(e)}, 500
        finally:
            conn.close()

    def get_transactions(self, firebase_uid, limit=50):
        conn = self._get_db()
        user = conn.execute("SELECT id FROM users WHERE firebase_uid = ?", (firebase_uid,)).fetchone()
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
               ORDER BY t.created_at DESC LIMIT ?""",
            (user_id, user_id, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── Orders / Trades ──

    def create_order(self, user_uid, order_type, price, amount):
        conn = self._get_db()
        try:
            user = conn.execute(
                "SELECT id, balance, locked_balance FROM users WHERE firebase_uid = ?", (user_uid,)
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
                "INSERT INTO orders (user_uid, type, price, amount) VALUES (?, ?, ?, ?)",
                (user_uid, order_type, price, amount),
            )
            conn.commit()
            order = conn.execute("SELECT * FROM orders WHERE id = last_insert_rowid()").fetchone()
            return dict(order)
        except Exception as e:
            conn.rollback()
            return {"error": str(e)}, 500
        finally:
            conn.close()

    def cancel_order(self, user_uid, order_id):
        conn = self._get_db()
        try:
            order = conn.execute(
                "SELECT * FROM orders WHERE id = ? AND user_uid = ?", (order_id, user_uid),
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
            conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
            conn.commit()
            return {"message": "Order cancelled", "order_id": order_id}
        except Exception as e:
            conn.rollback()
            return {"error": str(e)}, 500
        finally:
            conn.close()

    def get_orders(self, user_uid, status_filter=None):
        conn = self._get_db()
        if status_filter:
            rows = conn.execute(
                "SELECT * FROM orders WHERE user_uid = ? AND status = ? ORDER BY created_at DESC",
                (user_uid, status_filter),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM orders WHERE user_uid = ? ORDER BY created_at DESC", (user_uid,),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_order_book(self, limit=15):
        conn = self._get_db()
        buys = conn.execute(
            "SELECT * FROM orders WHERE type='buy' AND status IN ('open','partial') ORDER BY price DESC, created_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        sells = conn.execute(
            "SELECT * FROM orders WHERE type='sell' AND status IN ('open','partial') ORDER BY price ASC, created_at ASC LIMIT ?",
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
        conn.close()
        return {
            "bids": sorted(buy_agg.values(), key=lambda x: -x["price"]),
            "asks": sorted(sell_agg.values(), key=lambda x: x["price"]),
        }

    def execute_trade(self, buy_order_id, sell_order_id, buyer_uid, seller_uid, amount, price):
        conn = self._get_db()
        try:
            buyer_fee = max(1, amount // 1000)
            seller_fee = max(1, amount // 1000)
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
                "INSERT INTO trades (buy_order_id, sell_order_id, buyer_uid, seller_uid, amount, price, buyer_fee, seller_fee) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (buy_order_id, sell_order_id, buyer_uid, seller_uid, amount, price, buyer_fee, seller_fee),
            )
            for oid in (buy_order_id, sell_order_id):
                conn.execute(
                    "UPDATE orders SET filled = filled + ?, status = CASE WHEN filled + ? >= amount THEN 'filled' ELSE 'partial' END WHERE id = ?",
                    (amount, amount, oid),
                )
            conn.commit()
            return {"success": True, "amount": amount, "price": price}
        except Exception as e:
            conn.rollback()
            return {"error": str(e), "success": False}
        finally:
            conn.close()

    def get_trades(self, user_uid=None, limit=50):
        conn = self._get_db()
        if user_uid:
            rows = conn.execute(
                "SELECT * FROM trades WHERE buyer_uid = ? OR seller_uid = ? ORDER BY created_at DESC LIMIT ?",
                (user_uid, user_uid, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── M-PESA ──

    def create_mpesa_transaction(self, user_uid, type_, phone, amount, checkout_id=None, conversation_id=None):
        conn = self._get_db()
        try:
            conn.execute(
                "INSERT INTO mpesa_transactions (user_uid, type, phone, amount, checkout_id, conversation_id) VALUES (?, ?, ?, ?, ?, ?)",
                (user_uid, type_, phone, amount, checkout_id, conversation_id),
            )
            conn.commit()
            tx = conn.execute("SELECT * FROM mpesa_transactions WHERE id = last_insert_rowid()").fetchone()
            return dict(tx)
        except Exception as e:
            conn.rollback()
            return {"error": str(e)}
        finally:
            conn.close()

    def get_mpesa_transactions(self, user_uid, limit=50):
        conn = self._get_db()
        rows = conn.execute(
            "SELECT * FROM mpesa_transactions WHERE user_uid = ? ORDER BY created_at DESC LIMIT ?",
            (user_uid, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_mpesa_transaction_by_checkout_id(self, checkout_id):
        conn = self._get_db()
        tx = conn.execute("SELECT * FROM mpesa_transactions WHERE checkout_id = ?", (checkout_id,)).fetchone()
        conn.close()
        return dict(tx) if tx else None

    def get_mpesa_transaction_by_conversation_id(self, conversation_id):
        conn = self._get_db()
        tx = conn.execute("SELECT * FROM mpesa_transactions WHERE conversation_id = ?", (conversation_id,)).fetchone()
        conn.close()
        return dict(tx) if tx else None

    def update_mpesa_transaction_status(self, identifier, result_code, result_desc):
        conn = self._get_db()
        status = "completed" if result_code == 0 else "failed"
        conn.execute(
            "UPDATE mpesa_transactions SET result_code = ?, result_desc = ?, status = ?, updated_at = datetime('now') WHERE checkout_id = ? OR conversation_id = ?",
            (result_code, result_desc, status, identifier, identifier),
        )
        conn.commit()
        conn.close()

    # ── Agents ──

    def create_agent(self, firebase_uid, business_name, contact_phone=None, email=None, id_number=None, kra_pin=None, location=None):
        conn = self._get_db()
        try:
            cur = conn.execute(
                "INSERT INTO agents (firebase_uid, business_name, contact_phone, email, id_number, kra_pin, location) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (firebase_uid, business_name, contact_phone, email, id_number, kra_pin, location),
            )
            conn.commit()
            agent = conn.execute("SELECT * FROM agents WHERE id = ?", (cur.lastrowid,)).fetchone()
            return dict(agent)
        except Exception as e:
            return {"error": str(e)}
        finally:
            conn.close()

    def get_agent(self, firebase_uid):
        conn = self._get_db()
        agent = conn.execute("SELECT * FROM agents WHERE firebase_uid = ?", (firebase_uid,)).fetchone()
        conn.close()
        return dict(agent) if agent else None

    def get_agent_by_id(self, agent_id):
        conn = self._get_db()
        agent = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        conn.close()
        return dict(agent) if agent else None

    def update_agent_status(self, firebase_uid, status):
        conn = self._get_db()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        verified = f", verified_at = '{now}'" if status == "active" else ""
        conn.execute(f"UPDATE agents SET status = ?{verified} WHERE firebase_uid = ?", (status, firebase_uid))
        conn.commit()
        conn.close()

    def update_agent_float(self, agent_uid, amount_delta):
        conn = self._get_db()
        conn.execute(
            "UPDATE agents SET float_balance = MAX(COALESCE(float_balance, 0) + ?, 0) WHERE firebase_uid = ?",
            (amount_delta, agent_uid),
        )
        conn.commit()
        conn.close()

    def get_all_agents(self, status=None):
        conn = self._get_db()
        if status:
            rows = conn.execute("SELECT * FROM agents WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM agents ORDER BY created_at DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def create_agent_transaction(self, agent_uid, type_, amount, user_uid=None, commission=0, reference=None):
        conn = self._get_db()
        cur = conn.execute(
            "INSERT INTO agent_transactions (agent_uid, type, amount, user_uid, commission, reference) VALUES (?, ?, ?, ?, ?, ?)",
            (agent_uid, type_, amount, user_uid, commission, reference),
        )
        conn.commit()
        tx = conn.execute("SELECT * FROM agent_transactions WHERE id = ?", (cur.lastrowid,)).fetchone()
        conn.close()
        return dict(tx)

    def get_agent_transactions(self, agent_uid, limit=50):
        conn = self._get_db()
        rows = conn.execute(
            "SELECT * FROM agent_transactions WHERE agent_uid = ? ORDER BY created_at DESC LIMIT ?",
            (agent_uid, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ── Tariffs ──

    def create_tariff(self, name, type_, percentage=None, flat_fee=None, min_amount=None, max_amount=None):
        conn = self._get_db()
        cur = conn.execute(
            "INSERT INTO tariffs (name, type, percentage, flat_fee, min_amount, max_amount) VALUES (?, ?, ?, ?, ?, ?)",
            (name, type_, percentage, flat_fee, min_amount, max_amount),
        )
        conn.commit()
        t = conn.execute("SELECT * FROM tariffs WHERE id = ?", (cur.lastrowid,)).fetchone()
        conn.close()
        return dict(t)

    def get_active_tariffs(self):
        conn = self._get_db()
        rows = conn.execute("SELECT * FROM tariffs WHERE is_active = 1 ORDER BY type, name").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_tariff_by_type(self, type_):
        conn = self._get_db()
        rows = conn.execute(
            "SELECT * FROM tariffs WHERE type = ? AND is_active = 1 ORDER BY min_amount ASC", (type_,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_tariff(self, tariff_id, **kwargs):
        conn = self._get_db()
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

    # ── BradSec: Events ──

    def log_event(self, event_type, severity="info", uid=None, details=None, ip_address=None, user_agent=None):
        if event_type not in BRADSEC_EVENT_TYPES:
            event_type = "suspicious_ip"
        if severity not in BRADSEC_SEVERITIES:
            severity = "info"
        conn = self._get_db()
        conn.execute(
            "INSERT INTO security_events (event_type, severity, uid, details, ip_address, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
            (event_type, severity, uid, json.dumps(details) if details else None, ip_address, user_agent),
        )
        conn.commit()
        conn.close()

    def get_events(self, limit=50, offset=0, event_type=None, severity=None, uid=None):
        conn = self._get_db()
        clauses = []
        params = []
        if uid:
            clauses.append("uid = ?")
            params.append(uid)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        where = " AND ".join(clauses) if clauses else "1"
        rows = conn.execute(
            f"SELECT * FROM security_events WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def count_events(self, event_type=None, severity=None, uid=None):
        conn = self._get_db()
        clauses = []
        params = []
        if uid:
            clauses.append("uid = ?")
            params.append(uid)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        where = " AND ".join(clauses) if clauses else "1"
        row = conn.execute(f"SELECT COUNT(*) as cnt FROM security_events WHERE {where}", params).fetchone()
        conn.close()
        return row["cnt"]

    # ── BradSec: Rate Limiting ──

    def _window_key(self, action):
        cfg = RATE_LIMITS.get(action, {"max": 10, "window": 3600})
        now = time.time()
        return now - (now % cfg["window"])

    def check_rate_limit(self, uid, action, max_count=None, window_seconds=None):
        cfg = RATE_LIMITS.get(action)
        if not cfg:
            return True
        w_start = self._window_key(action)
        conn = self._get_db()
        row = conn.execute(
            "SELECT count FROM rate_limit_counts WHERE uid = ? AND action = ? AND window_start = ?",
            (uid, action, w_start),
        ).fetchone()
        if row and row["count"] >= cfg["max"]:
            conn.close()
            return False
        if row:
            conn.execute(
                "UPDATE rate_limit_counts SET count = count + 1 WHERE uid = ? AND action = ? AND window_start = ?",
                (uid, action, w_start),
            )
        else:
            conn.execute(
                "INSERT INTO rate_limit_counts (uid, action, window_start, count) VALUES (?, ?, ?, 1)",
                (uid, action, w_start),
            )
        conn.commit()
        conn.close()
        return True

    def get_rate_limit_remaining(self, uid, action, max_count=None, window_seconds=None):
        cfg = RATE_LIMITS.get(action)
        if not cfg:
            return -1
        w_start = self._window_key(action)
        conn = self._get_db()
        row = conn.execute(
            "SELECT count FROM rate_limit_counts WHERE uid = ? AND action = ? AND window_start = ?",
            (uid, action, w_start),
        ).fetchone()
        conn.close()
        used = row["count"] if row else 0
        return max(0, cfg["max"] - used)

    def reset_rate_limit(self, uid, action):
        w_start = self._window_key(action)
        conn = self._get_db()
        conn.execute(
            "DELETE FROM rate_limit_counts WHERE uid = ? AND action = ? AND window_start = ?",
            (uid, action, w_start),
        )
        conn.commit()
        conn.close()

    # ── BradSec: Fraud Detection ──

    def _get_user_created_at(self, uid):
        conn = self._get_db()
        row = conn.execute("SELECT created_at FROM users WHERE firebase_uid = ?", (uid,)).fetchone()
        conn.close()
        return row["created_at"] if row else None

    def _count_sec_events(self, uid, event_type, seconds):
        since = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
        conn = self._get_db()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM security_events WHERE uid = ? AND event_type = ? AND created_at >= ?",
            (uid, event_type, since),
        ).fetchone()
        conn.close()
        return row["cnt"]

    def _count_recent_recipient(self, sender_uid, recipient_uid, seconds):
        conn = self._get_db()
        row = conn.execute(
            """SELECT COUNT(*) as cnt FROM transactions t
               JOIN users s ON t.sender_id = s.id
               JOIN users r ON t.recipient_id = r.id
               WHERE s.firebase_uid = ? AND r.firebase_uid = ?
               AND t.created_at >= datetime('now', ?)""",
            (sender_uid, recipient_uid, f"-{seconds} seconds"),
        ).fetchone()
        conn.close()
        return row["cnt"]

    def evaluate_transaction(self, sender_uid, recipient_uid, amount, tx_ref=None):
        triggered = []
        total_score = 0

        recent_sends = self._count_sec_events(sender_uid, "send", 300)
        if recent_sends >= 5:
            triggered.append(FRAUD_RULES["velocity"])
            total_score += FRAUD_RULES["velocity"]["score"]

        if amount > 10_000_000:
            triggered.append(FRAUD_RULES["amount_anomaly"])
            total_score += FRAUD_RULES["amount_anomaly"]["score"]

        created = self._get_user_created_at(sender_uid)
        if created and amount > 1_000_000:
            try:
                created_dt = datetime.fromisoformat(created)
                if datetime.now(timezone.utc) - created_dt < timedelta(hours=24):
                    triggered.append(FRAUD_RULES["new_account"])
                    total_score += FRAUD_RULES["new_account"]["score"]
            except (ValueError, TypeError):
                pass

        recent_recipient = self._count_recent_recipient(sender_uid, recipient_uid, 600)
        if recent_recipient >= 3:
            triggered.append(FRAUD_RULES["rapid_recipient"])
            total_score += FRAUD_RULES["rapid_recipient"]["score"]

        user = self.get_user_by_firebase_uid(sender_uid)
        if user:
            kes = user.get("kes_balance", 0)
            if kes > 0 and amount > kes * 0.9:
                triggered.append(FRAUD_RULES["balance_drain"])
                total_score += FRAUD_RULES["balance_drain"]["score"]

        hour = datetime.now(timezone.utc).hour
        if hour < 5 or hour >= 23:
            triggered.append(FRAUD_RULES["unusual_hours"])
            total_score += FRAUD_RULES["unusual_hours"]["score"]

        if amount % 100000 == 0 and amount >= 500000:
            triggered.append(FRAUD_RULES["round_numbers"])
            total_score += FRAUD_RULES["round_numbers"]["score"]

        total_score = min(total_score, 100)
        is_flagged = total_score >= FLAG_THRESHOLD

        if is_flagged:
            ref = tx_ref or f"FRAUD-{int(time.time())}-{sender_uid[:8]}"
            conn = self._get_db()
            conn.execute(
                "INSERT INTO flagged_transactions (tx_ref, sender_uid, recipient_uid, amount, score, rules_triggered) VALUES (?, ?, ?, ?, ?, ?)",
                (ref, sender_uid, recipient_uid, amount, total_score,
                 json.dumps([r["label"] for r in triggered])),
            )
            conn.commit()
            conn.close()

        return {
            "score": total_score,
            "flagged": is_flagged,
            "threshold": FLAG_THRESHOLD,
            "rules_triggered": [r["label"] for r in triggered],
        }

    def get_flagged_transactions(self, status=None, limit=50, offset=0):
        conn = self._get_db()
        if status:
            rows = conn.execute(
                "SELECT * FROM flagged_transactions WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM flagged_transactions ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def resolve_flag(self, flag_id, status, reviewer_uid, note=None):
        conn = self._get_db()
        flag = conn.execute("SELECT * FROM flagged_transactions WHERE id = ?", (flag_id,)).fetchone()
        if not flag:
            conn.close()
            return None
        conn.execute(
            "UPDATE flagged_transactions SET status = ?, reviewed_by = ?, reviewed_at = datetime('now'), resolution_note = ? WHERE id = ?",
            (status, reviewer_uid, note, flag_id),
        )
        conn.commit()
        conn.close()
        return dict(flag)

    def get_flag_stats(self):
        conn = self._get_db()
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM flagged_transactions GROUP BY status"
        ).fetchall()
        conn.close()
        stats = {r["status"]: r["cnt"] for r in rows}
        return {
            "open": stats.get("open", 0),
            "approved": stats.get("approved", 0),
            "blocked": stats.get("blocked", 0),
            "total": sum(stats.values()),
        }

    def get_security_summary(self):
        conn = self._get_db()
        high = conn.execute(
            "SELECT COUNT(*) as cnt FROM security_events WHERE severity IN ('high','critical') AND created_at >= datetime('now', '-24 hours')"
        ).fetchone()
        total_24h = conn.execute(
            "SELECT COUNT(*) as cnt FROM security_events WHERE created_at >= datetime('now', '-24 hours')"
        ).fetchone()
        recent = conn.execute(
            "SELECT * FROM security_events ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        conn.close()
        return {
            "high_severity_24h": high["cnt"],
            "total_events_24h": total_24h["cnt"],
            "open_flags": self.get_flag_stats()["open"],
            "recent_events": [dict(r) for r in recent],
        }

    def close(self):
        pass
