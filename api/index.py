import sys
import os

root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, root)
sys.path.insert(0, os.path.join(root, "backend"))

# Use /tmp for SQLite and ledger on Vercel (read-only filesystem elsewhere)
os.environ.setdefault("BRADPAY_DB_PATH", "/tmp/bradpay.db")
os.environ.setdefault("BRADPAY_LEDGER_PATH", "/tmp/bradledger.json")

# Skip .env loading on Vercel (use env vars from project settings)
if not os.environ.get("FIREBASE_API_KEY"):
    from dotenv import load_dotenv
    load_dotenv(os.path.join(root, "backend", ".env"))

from backend.app import create_app

app = create_app()
