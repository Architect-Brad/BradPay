"""Tests for BradSec security module — fraud detection, rate limiting, event logging."""


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
