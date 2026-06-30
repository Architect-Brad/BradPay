import os, sys, pytest, tempfile, time, json, hashlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_db_path = tempfile.mktemp(suffix=".db")
_ledger_path = tempfile.mktemp(suffix=".json")
os.environ["BRADPAY_DB_PATH"] = _db_path
os.environ["BRADPAY_LEDGER_PATH"] = _ledger_path
os.environ["FIREBASE_SERVICE_ACCOUNT"] = ""
os.environ["TEST_MODE"] = "1"
os.environ["MPESA_CONSUMER_KEY"] = "test_key"
os.environ["MPESA_CONSUMER_SECRET"] = "test_secret"
os.environ["MPESA_PASSKEY"] = "test_passkey"
os.environ["MPESA_SHORTCODE"] = "174379"

from app import create_app
from models import get_db


def _headers(uid):
    return {"Authorization": f"Bearer {uid}", "Content-Type": "application/json"}


def _fund_user(uid, coin_balance=1000000, kes_balance=1000000):
    conn = get_db()
    conn.execute("UPDATE users SET balance = ?, kes_balance = ? WHERE firebase_uid = ?",
                 (coin_balance, kes_balance, uid))
    conn.commit()
    conn.close()


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    yield app


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture
def registered_user(client):
    uid = "test_firebase_uid_" + str(time.time_ns())
    resp = client.post("/api/auth/register", json={
        "firebase_uid": uid,
        "pin": "1234",
        "email": f"test_{time.time_ns()}@example.com",
        "display_name": "Test User",
        "phone": "+254700000001",
    }, headers=_headers(uid))
    data = resp.get_json()
    assert resp.status_code == 201, data
    _fund_user(uid)
    return {"uid": uid, **data["user"]}


@pytest.fixture
def auth_headers(registered_user):
    return _headers(registered_user["uid"])


@pytest.fixture
def second_user(client):
    uid = "second_firebase_uid_" + str(time.time_ns())
    resp = client.post("/api/auth/register", json={
        "firebase_uid": uid,
        "pin": "5678",
        "email": f"second_{time.time_ns()}@example.com",
        "display_name": "Second User",
        "phone": "+254700000002",
    }, headers=_headers(uid))
    data = resp.get_json()
    assert resp.status_code == 201
    _fund_user(uid)
    return {"uid": uid, **data["user"]}


@pytest.fixture
def second_headers(second_user):
    return _headers(second_user["uid"])


def pytest_unconfigure(config):
    for p in [_db_path, _ledger_path]:
        if os.path.exists(p):
            os.unlink(p)
