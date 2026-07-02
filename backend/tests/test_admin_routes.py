"""Tests for admin routes — credit, debit, faucet."""


def test_admin_credit_success(client, admin_headers, registered_user):
    uid = registered_user["uid"]
    resp = client.post("/api/admin/credit", json={
        "uid": uid,
        "amount": 50000,
        "note": "Test credit",
    }, headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "Credited" in data["message"]
    assert data["amount"] == 50000


def test_admin_credit_missing_params(client, admin_headers):
    resp = client.post("/api/admin/credit", json={"uid": "x"}, headers=admin_headers)
    assert resp.status_code == 400


def test_admin_credit_invalid_amount(client, admin_headers, registered_user):
    resp = client.post("/api/admin/credit", json={
        "uid": registered_user["uid"],
        "amount": -100,
    }, headers=admin_headers)
    assert resp.status_code == 400


def test_admin_credit_unknown_user(client, admin_headers):
    resp = client.post("/api/admin/credit", json={
        "uid": "nonexistent-uid",
        "amount": 100,
    }, headers=admin_headers)
    assert resp.status_code == 404


def test_admin_debit_success(client, admin_headers, registered_user):
    uid = registered_user["uid"]
    resp = client.post("/api/admin/debit", json={
        "uid": uid,
        "amount": 50000,
        "note": "Test debit",
    }, headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "Debited" in data["message"]
    assert data["amount"] == 50000


def test_admin_debit_insufficient(client, admin_headers, registered_user):
    uid = registered_user["uid"]
    resp = client.post("/api/admin/debit", json={
        "uid": uid,
        "amount": 999999999,
    }, headers=admin_headers)
    assert resp.status_code == 400
    assert "Insufficient" in resp.get_json()["error"]


def test_admin_credit_requires_admin(client, auth_headers):
    resp = client.post("/api/admin/credit", json={
        "uid": "x", "amount": 100,
    }, headers=auth_headers)
    assert resp.status_code == 401


def test_admin_debit_requires_admin(client, auth_headers):
    resp = client.post("/api/admin/debit", json={
        "uid": "x", "amount": 100,
    }, headers=auth_headers)
    assert resp.status_code == 401


def test_admin_wrong_key(client, registered_user):
    resp = client.post("/api/admin/credit", json={
        "uid": registered_user["uid"], "amount": 100,
    }, headers={"Authorization": "Bearer wrong-key"})
    assert resp.status_code == 401


def test_admin_faucet_requires_auth(client):
    resp = client.post("/api/admin/faucet")
    assert resp.status_code == 401
