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
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

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
    """)
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


def verify_pin(user_id, pin):
    conn = get_db()
    user = conn.execute(
        "SELECT pin_hash FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    if not user:
        return False
    return check_password_hash(user["pin_hash"], pin)


def get_balance(user_id):
    conn = get_db()
    user = conn.execute(
        "SELECT balance FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return user["balance"] if user else None


def create_transaction(sender_id, recipient_uid, amount, note=None, offline_id=None):
    conn = get_db()
    try:
        recipient = conn.execute(
            "SELECT id, balance FROM users WHERE firebase_uid = ?", (recipient_uid,)
        ).fetchone()
        if not recipient:
            return {"error": "Recipient not found"}, 404

        sender = conn.execute(
            "SELECT balance FROM users WHERE id = ?", (sender_id,)
        ).fetchone()
        if not sender:
            return {"error": "Sender not found"}, 404

        total_amount = amount
        if sender["balance"] < total_amount:
            return {"error": "Insufficient balance"}, 400

        fee = 0
        tx_ref = f"BRADPAY-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{sender_id}-{recipient['id']}"

        conn.execute("BEGIN TRANSACTION")
        conn.execute(
            "UPDATE users SET balance = balance - ?, updated_at = datetime('now') WHERE id = ?",
            (total_amount, sender_id),
        )
        conn.execute(
            "UPDATE users SET balance = balance + ?, updated_at = datetime('now') WHERE id = ?",
            (amount, recipient["id"]),
        )
        conn.execute(
            """INSERT INTO transactions (tx_ref, sender_id, recipient_id, amount, fee, type, status, note, offline_id)
               VALUES (?, ?, ?, ?, ?, 'transfer', 'completed', ?, ?)""",
            (tx_ref, sender_id, recipient["id"], amount, fee, note, offline_id),
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


def get_transactions(user_id, limit=50):
    conn = get_db()
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
