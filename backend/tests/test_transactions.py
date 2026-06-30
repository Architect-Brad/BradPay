"""Tests for transaction endpoints."""


def test_send_kes_success(client, auth_headers, registered_user, second_user, second_headers):
    resp = client.post("/api/transactions/send", json={
        "recipientUid": second_user["uid"],
        "amount": 10000,
        "pin": "1234",
        "note": "test payment",
    }, headers=auth_headers)
    assert resp.status_code == 201, resp.get_json()
    data = resp.get_json()
    assert "transaction" in data


def test_send_kes_insufficient_balance(client, auth_headers, registered_user, second_user):
    resp = client.post("/api/transactions/send", json={
        "recipientUid": second_user["uid"],
        "amount": 999999999,
        "pin": "1234",
    }, headers=auth_headers)
    assert resp.status_code == 400
    assert "insufficient" in resp.get_json().get("error", "").lower()


def test_send_kes_nonexistent_recipient(client, auth_headers, registered_user):
    resp = client.post("/api/transactions/send", json={
        "recipientUid": "nobody_firebase_uid",
        "amount": 100,
        "pin": "1234",
    }, headers=auth_headers)
    assert resp.status_code == 404


def test_send_kes_self(client, auth_headers, registered_user):
    # App allows sending to self (no explicit block)
    resp = client.post("/api/transactions/send", json={
        "recipientUid": registered_user["uid"],
        "amount": 100,
        "pin": "1234",
    }, headers=auth_headers)
    assert resp.status_code == 201


def test_get_transactions(client, auth_headers, registered_user):
    resp = client.get("/api/transactions/history", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "transactions" in data


def test_get_balance(client, auth_headers, registered_user):
    resp = client.get("/api/transactions/balance", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "balance" in data
