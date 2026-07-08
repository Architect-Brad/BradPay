"""Tests for BradSec security module — fraud detection, rate limiting, event logging."""
import os
from models import get_db


def _fund_user(uid, coin_balance=20000000, kes_balance=20000000):
    conn = get_db()
    conn.execute("UPDATE users SET balance = ?, kes_balance = ? WHERE firebase_uid = ?",
                 (coin_balance, kes_balance, uid))
    conn.commit()
    conn.close()


def test_security_events_empty(client, auth_headers):
    resp = client.get("/api/security/events", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "events" in data
    # login_success events may exist from auth flow
    assert "total" in data


def test_security_events_count(client, auth_headers):
    resp = client.get("/api/security/events/count", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()["count"] >= 0


def test_security_rate_limit_status(client, auth_headers):
    resp = client.get("/api/security/rate-limit", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "limits" in data
    assert "send" in data["limits"]


def test_security_rate_limit_action(client, auth_headers):
    resp = client.get("/api/security/rate-limit?action=send", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["action"] == "send"
    assert data["remaining"] >= 0


def test_evaluate_transaction_low_risk(client, auth_headers, registered_user):
    resp = client.post("/api/security/evaluate", json={
        "recipient_uid": "other-user",
        "amount": 10000,
    }, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "score" in data
    assert data["score"] >= 0
    assert "flagged" in data
    assert "rules_triggered" in data


def test_evaluate_missing_params(client, auth_headers):
    resp = client.post("/api/security/evaluate", json={}, headers=auth_headers)
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_evaluate_requires_auth(client):
    resp = client.post("/api/security/evaluate", json={
        "recipient_uid": "x", "amount": 100,
    })
    assert resp.status_code == 401


def test_admin_flags_requires_admin(client, auth_headers):
    resp = client.get("/api/security/flags", headers=auth_headers)
    assert resp.status_code == 401


def test_admin_flags_with_admin(client, admin_headers):
    resp = client.get("/api/security/flags", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "flags" in data
    assert "stats" in data


def test_admin_dashboard_requires_admin(client, auth_headers):
    resp = client.get("/api/security/dashboard", headers=auth_headers)
    assert resp.status_code == 401


def test_admin_dashboard_with_admin(client, admin_headers):
    resp = client.get("/api/security/dashboard", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "summary" in data
    assert "recent_events" in data
    assert "open_flags" in data


# ── Auto-block tests ──

def test_auto_block_settings_requires_admin(client, auth_headers):
    resp = client.get("/api/security/settings", headers=auth_headers)
    assert resp.status_code == 401

    resp = client.post("/api/security/settings", json={}, headers=auth_headers)
    assert resp.status_code == 401


def test_auto_block_settings_get(client, admin_headers):
    resp = client.get("/api/security/settings", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "auto_block_enabled" in data
    assert "auto_block_threshold" in data
    assert "flag_threshold" in data


def test_auto_block_settings_update(client, admin_headers):
    resp = client.post("/api/security/settings", json={
        "auto_block_enabled": True,
        "auto_block_threshold": 50,
    }, headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["settings"]["auto_block_enabled"] is True
    assert data["settings"]["auto_block_threshold"] == 50

    # Reset for other tests
    client.post("/api/security/settings", json={
        "auto_block_enabled": False,
        "auto_block_threshold": 60,
    }, headers=admin_headers)


def test_auto_block_rejects_high_risk(client, auth_headers, admin_headers):
    client.post("/api/security/settings", json={
        "auto_block_enabled": True,
        "auto_block_threshold": 50,
    }, headers=admin_headers)

    resp = client.post("/api/transactions/send", json={
        "recipientUid": "nonexistent",
        "amount": 10000001,
        "pin": "8146",
    }, headers=auth_headers)
    assert resp.status_code == 403
    data = resp.get_json()
    assert "blocked" in data["error"].lower()
    assert "fraud" in data

    # Reset
    client.post("/api/security/settings", json={
        "auto_block_enabled": False,
        "auto_block_threshold": 60,
    }, headers=admin_headers)


def test_auto_block_disabled_still_processes(client, auth_headers, admin_headers, second_user):
    client.post("/api/security/settings", json={
        "auto_block_enabled": False,
    }, headers=admin_headers)

    _fund_user(auth_headers["Authorization"].replace("Bearer ", ""))

    resp = client.post("/api/transactions/send", json={
        "recipientUid": second_user["uid"],
        "amount": 10000001,
        "pin": "8146",
    }, headers=auth_headers)
    assert resp.status_code == 201, f"Expected 201 got {resp.status_code}: {resp.get_json()}"


def test_auto_block_threshold_custom(client, auth_headers, admin_headers, second_user):
    client.post("/api/security/settings", json={
        "auto_block_enabled": True,
        "auto_block_threshold": 80,
    }, headers=admin_headers)

    _fund_user(auth_headers["Authorization"].replace("Bearer ", ""))

    resp = client.post("/api/transactions/send", json={
        "recipientUid": second_user["uid"],
        "amount": 10000001,
        "pin": "8146",
    }, headers=auth_headers)
    # score 60 < threshold 80, should process
    assert resp.status_code == 201, f"Expected 201 got {resp.status_code}: {resp.get_json()}"

    # Reset
    client.post("/api/security/settings", json={
        "auto_block_enabled": False,
        "auto_block_threshold": 60,
    }, headers=admin_headers)
