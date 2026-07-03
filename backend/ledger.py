import hashlib
import json
import os
import threading
from datetime import datetime, timezone

LEDGER_FILE = os.environ.get("BRADPAY_LEDGER_PATH", "")

_lock = threading.Lock()


def _backup(data):
    try:
        from blob_backup import backup_ledger
        backup_ledger(data)
    except Exception:
        pass


def _restore():
    try:
        from blob_backup import restore_ledger
        return restore_ledger()
    except Exception:
        return None


class BradLedger:
    def __init__(self):
        self.chain = []
        self.pending_transactions = []
        self.difficulty = 4
        self._read_only = False
        self._create_genesis()
        if LEDGER_FILE:
            try:
                if os.path.exists(LEDGER_FILE):
                    with open(LEDGER_FILE) as f:
                        data = json.load(f)
                        if data.get("chain"):
                            self.chain = data["chain"]
                            self.pending_transactions = data.get("pending", [])
                            if not self._validate():
                                self.chain = []
                                self.pending_transactions = []
                                self._create_genesis()
            except Exception:
                self.chain = []
                self.pending_transactions = []
                self._create_genesis()

    def _save(self):
        data = {"chain": self.chain, "pending": self.pending_transactions}
        if LEDGER_FILE:
            try:
                with open(LEDGER_FILE, "w") as f:
                    json.dump(data, f, indent=2)
            except OSError:
                pass
        _backup(data)

    def _create_genesis(self):
        genesis = {
            "index": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "transactions": [],
            "previous_hash": "0" * 64,
            "nonce": 0,
            "hash": "",
        }
        genesis["hash"] = self._compute_hash(genesis)
        self.chain.append(genesis)
        self._save()

    def _compute_hash(self, block):
        block_data = {
            "index": block["index"],
            "timestamp": block["timestamp"],
            "transactions": block["transactions"],
            "previous_hash": block["previous_hash"],
            "nonce": block["nonce"],
        }
        raw = json.dumps(block_data, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()

    def _proof_of_work(self, block):
        block["nonce"] = 0
        prefix = "0" * self.difficulty
        while True:
            block["hash"] = self._compute_hash(block)
            if block["hash"].startswith(prefix):
                break
            block["nonce"] += 1

    def add_transaction(self, tx_data):
        with _lock:
            entry = {
                "tx_ref": tx_data.get("tx_ref"),
                "sender_uid": tx_data.get("sender_uid"),
                "recipient_uid": tx_data.get("recipient_uid"),
                "sender_name": tx_data.get("sender_name", ""),
                "recipient_name": tx_data.get("recipient_name", ""),
                "amount": tx_data.get("amount"),
                "fee": tx_data.get("fee", 0),
                "type": tx_data.get("type", "transfer"),
                "note": tx_data.get("note", ""),
                "timestamp": tx_data.get("created_at", datetime.now(timezone.utc).isoformat()),
            }
            self.pending_transactions.append(entry)
            if len(self.pending_transactions) >= 5:
                self._mine_block()
            else:
                self._save()

    def _mine_block(self):
        if not self.pending_transactions:
            return None
        last_block = self.chain[-1]
        block = {
            "index": last_block["index"] + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "transactions": list(self.pending_transactions),
            "previous_hash": last_block["hash"],
            "nonce": 0,
            "hash": "",
        }
        self._proof_of_work(block)
        self.chain.append(block)
        self.pending_transactions = []
        self._save()
        return block

    def force_mine(self):
        with _lock:
            return self._mine_block()

    def get_chain(self, start=0, end=None):
        if end is None:
            end = len(self.chain)
        return {
            "chain": self.chain[start:end],
            "length": len(self.chain),
            "pending": len(self.pending_transactions),
            "difficulty": self.difficulty,
        }

    def get_block(self, index):
        if 0 <= index < len(self.chain):
            return self.chain[index]
        return None

    def get_transaction_proof(self, tx_ref):
        for block in self.chain:
            for tx in block["transactions"]:
                if tx["tx_ref"] == tx_ref:
                    return {
                        "transaction": tx,
                        "block_index": block["index"],
                        "block_hash": block["hash"],
                        "previous_hash": block["previous_hash"],
                        "confirmations": len(self.chain) - block["index"],
                    }
        # Check pending
        for tx in self.pending_transactions:
            if tx["tx_ref"] == tx_ref:
                return {
                    "transaction": tx,
                    "block_index": None,
                    "block_hash": None,
                    "confirmations": 0,
                    "status": "pending",
                }
        return None

    def _validate(self):
        for i in range(1, len(self.chain)):
            block = self.chain[i]
            prev = self.chain[i - 1]
            if block["previous_hash"] != prev["hash"]:
                return False
            expected_hash = self._compute_hash(block)
            if block["hash"] != expected_hash:
                return False
            prefix = "0" * self.difficulty
            if not block["hash"].startswith(prefix):
                return False
        return True

    def validate(self):
        return self._validate()


# Singleton
_ledger = None


def get_ledger():
    global _ledger
    if _ledger is None:
        _ledger = BradLedger()
    return _ledger


def init_ledger():
    get_ledger()
