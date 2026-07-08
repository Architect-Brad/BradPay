"""Tests for the BradUSSD engine."""


def test_ussd_new_session(client, registered_user):
    phone = registered_user["phone"]
    resp = client.post("/api/ussd/callback", json={
        "sessionId": "sess-001", "phoneNumber": phone, "text": "",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert "response" in data
    assert data["response"].startswith("CON")
    assert "BradPay" in data["response"]


def test_ussd_menu_option_balance(client, registered_user):
    phone = registered_user["phone"]
    resp = client.post("/api/ussd/callback", json={
        "sessionId": "sess-002", "phoneNumber": phone, "text": "",
    })
    assert resp.status_code == 200
    resp = client.post("/api/ussd/callback", json={
        "sessionId": "sess-002", "phoneNumber": phone, "text": "1",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert "KES" in data["response"]
    assert data["response"].startswith("END")


def test_ussd_send_flow_asks_for_phone(client, registered_user):
    phone = registered_user["phone"]
    sid = "sess-send-ask"
    client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "",
    })
    resp = client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "2",
    })
    assert resp.status_code == 200
    assert "Enter recipient" in resp.get_json()["response"]


def test_ussd_unregistered_user(client):
    resp = client.post("/api/ussd/callback", json={
        "sessionId": "sess-003", "phoneNumber": "+254999999999", "text": "",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert "not registered" in data["response"].lower()
    assert data["response"].startswith("END")


def test_ussd_account_menu(client, registered_user):
    phone = registered_user["phone"]
    sid = "sess-acct"
    client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "",
    })
    resp = client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "5",
    })
    assert resp.status_code == 200
    assert "My UID" in resp.get_json()["response"]
    resp = client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "1",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert "UID" in data["response"]
    assert data["response"].startswith("END")


def test_ussd_session_expired(client):
    resp = client.post("/api/ussd/callback", json={
        "sessionId": "nonexistent", "phoneNumber": "+254712345678", "text": "1",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert "Session expired" in data["response"]


def test_ussd_deposit_option(client, registered_user):
    phone = registered_user["phone"]
    sid = "sess-dep"
    client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "",
    })
    resp = client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "3",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert "M-PESA" in data["response"]
    assert data["response"].startswith("END")


def test_ussd_withdraw_option(client, registered_user):
    phone = registered_user["phone"]
    sid = "sess-wd"
    client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "",
    })
    resp = client.post("/api/ussd/callback", json={
        "sessionId": sid, "phoneNumber": phone, "text": "4",
    })
    assert resp.status_code == 200
    assert "withdraw" in resp.get_json()["response"].lower()
