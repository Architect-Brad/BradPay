"""Regression tests for the security/correctness bugfix batch."""

from unittest.mock import patch

from models import (
    get_db,
    create_mpesa_transaction,
    claim_mpesa_callback,
    update_kes_balance,
    get_kes_balance,
    get_balance,
)
from daraja import cents_to_kes, kes_to_cents, _generate_password


class MockResponse:
    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP Error")


def test_cents_kes_conversion():
    assert cents_to_kes(10000) == 100
    assert cents_to_kes(99) == 0
    assert kes_to_cents(100) == 10000
    assert kes_to_cents(1.5) == 150


def test_stk_password_uses_same_timestamp():
    password, ts = _generate_password()
    password2, ts2 = _generate_password(ts)
    assert password == password2
    assert ts == ts2


def test_stkpush_sends_whole_kes_not_cents(client, auth_headers, registered_user):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return MockResponse({
            "ResponseCode": "0",
            "CheckoutRequestID": "ws_CO_amt_test",
            "MerchantRequestID": "m-1",
        })

    with patch("requests.get") as mock_get, patch("requests.post", side_effect=fake_post):
        mock_get.return_value = MockResponse({"access_token": "t", "expires_in": 3600})
        resp = client.post("/api/daraja/stkpush", json={
            "phone": "254708374149",
            "amount": 10000,  # cents = KES 100
        }, headers=auth_headers)
    assert resp.status_code == 200, resp.get_json()
    assert captured["payload"]["Amount"] == "100"


def test_b2c_uses_type_underscore(client, auth_headers, registered_user):
    """Previously type= caused TypeError after debiting the user."""
    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        mock_get.return_value = MockResponse({"access_token": "t", "expires_in": 3600})
        mock_post.return_value = MockResponse({
            "ConversationID": "conv-b2c-1",
            "OriginatorConversationID": "orig-1",
            "ResponseCode": "0",
        })
        resp = client.post("/api/daraja/b2c", json={
            "phone": "254708374149",
            "amount": 10000,
        }, headers=auth_headers)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["conversation_id"] == "conv-b2c-1"
    conn = get_db()
    row = conn.execute(
        "SELECT type, status FROM mpesa_transactions WHERE conversation_id = ?",
        ("conv-b2c-1",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["type"] == "withdrawal"
    assert row["status"] == "pending"


def test_stk_callback_idempotent(client, registered_user):
    uid = registered_user["uid"]
    create_mpesa_transaction(uid, "deposit", "254700", 50000, checkout_id="co-idem-1")
    before = get_balance(uid)

    body = {
        "Body": {
            "stkCallback": {
                "CheckoutRequestID": "co-idem-1",
                "ResultCode": 0,
                "ResultDesc": "Success",
                "CallbackMetadata": {
                    "Item": [{"Name": "Amount", "Value": 500}]
                },
            }
        }
    }
    r1 = client.post("/api/daraja/callback", json=body)
    assert r1.status_code == 200
    mid = get_balance(uid)
    r2 = client.post("/api/daraja/callback", json=body)
    assert r2.status_code == 200
    after = get_balance(uid)
    assert mid == before + 50000  # 500 KES → 50000 cents
    assert after == mid  # no double credit


def test_b2c_failed_callback_refunds_once(client, registered_user):
    uid = registered_user["uid"]
    create_mpesa_transaction(uid, "withdrawal", "254700", 20000, conversation_id="conv-fail-1")
    # Simulate already-debited wallet
    update_kes_balance(uid, -20000)
    before = get_balance(uid)

    body = {
        "Result": {
            "ConversationID": "conv-fail-1",
            "ResultCode": 1,
            "ResultDesc": "Failed",
        }
    }
    client.post("/api/daraja/b2c_callback", json=body)
    mid = get_balance(uid)
    client.post("/api/daraja/b2c_callback", json=body)
    after = get_balance(uid)
    assert mid == before + 20000
    assert after == mid


def test_deposit_credits_main_balance(client, registered_user):
    """M-PESA deposit must fund the same balance used by P2P."""
    uid = registered_user["uid"]
    create_mpesa_transaction(uid, "deposit", "254700", 10000, checkout_id="co-unify-1")
    before = get_balance(uid)
    client.post("/api/daraja/callback", json={
        "Body": {
            "stkCallback": {
                "CheckoutRequestID": "co-unify-1",
                "ResultCode": 0,
                "ResultDesc": "ok",
                "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": 100}]},
            }
        }
    })
    assert get_balance(uid) == before + 10000
    assert get_kes_balance(uid) == get_balance(uid)


def test_claim_mpesa_only_once():
    from models import create_user
    import time
    uid = "claim_uid_" + str(time.time_ns())
    create_user(uid, pin="5678", phone="+254711111111")
    create_mpesa_transaction(uid, "deposit", "254711", 1000, checkout_id="co-claim-1")
    tx1, c1 = claim_mpesa_callback("co-claim-1", 0, "ok")
    tx2, c2 = claim_mpesa_callback("co-claim-1", 0, "ok")
    assert c1 is True
    assert c2 is False
    assert tx1["status"] == "completed"


def test_ussd_cumulative_send_flow(client, registered_user, second_user):
    """Africa's Talking sends cumulative text: 2*phone*amount*pin."""
    phone = registered_user["phone"]
    sid = "sess-at-cumulative"
    client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "",
    })
    r2 = client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "2",
    })
    assert "recipient" in r2.get_json()["response"].lower()
    r3 = client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "2*254700000002",
    })
    assert "amount" in r3.get_json()["response"].lower()
    r4 = client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "2*254700000002*50",
    })
    assert "PIN" in r4.get_json()["response"]
    assert "50" in r4.get_json()["response"]
    assert "254700000002" in r4.get_json()["response"]
    r5 = client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "2*254700000002*50*8146",
    })
    body = r5.get_json()["response"]
    assert body.startswith("END")
    assert "Sent" in body or "Failed" in body
    # Should not treat first menu digit as phone/amount
    assert "Send KES 2 to 2" not in body


def test_buy_order_requires_lock(client, auth_headers, registered_user):
    # Drain available balance by locking almost everything via a large sell... 
    # Instead: fund small balance and try large buy
    from models import get_db
    conn = get_db()
    conn.execute(
        "UPDATE users SET balance = 1000, locked_balance = 0 WHERE firebase_uid = ?",
        (registered_user["uid"],),
    )
    conn.commit()
    conn.close()
    resp = client.post("/api/trade/orders", json={
        "type": "buy", "price": 100, "amount": 5000,
    }, headers=auth_headers)
    assert resp.status_code == 400
    assert "Insufficient" in resp.get_json().get("error", "")
