"""Tests for auth endpoints."""

import time


def _headers(uid):
    return {"Authorization": f"Bearer {uid}", "Content-Type": "application/json"}


def test_register_success(client):
    uid = "register_test_" + str(time.time_ns())
    resp = client.post("/api/auth/register", json={
        "firebase_uid": uid,
        "pin": "8146",
        "email": f"new_{time.time_ns()}@example.com",
        "display_name": "New User",
    }, headers=_headers(uid))
    data = resp.get_json()
    assert resp.status_code == 201
    assert "id" in data["user"]


def test_register_duplicate_firebase_uid(client, registered_user):
    resp = client.post("/api/auth/register", json={
        "firebase_uid": registered_user["uid"],
        "pin": "8146",
    }, headers=_headers(registered_user["uid"]))
    assert resp.status_code == 409


def test_register_missing_firebase_uid(client):
    # firebase_uid in the body is ignored anyway (the authenticated uid from
    # the token is what's used), so this should still succeed as long as a
    # valid PIN is supplied.
    uid = "no_uid_" + str(time.time_ns())
    resp = client.post("/api/auth/register", json={
        "pin": "8146",
    }, headers=_headers(uid))
    assert resp.status_code == 201


def test_register_missing_pin(client):
    # A missing PIN must be rejected, not silently defaulted to something
    # guessable like "1234" - that was the original vulnerability.
    uid = "no_pin_" + str(time.time_ns())
    resp = client.post("/api/auth/register", json={
        "firebase_uid": uid,
    }, headers=_headers(uid))
    assert resp.status_code == 400


def test_register_weak_pin_rejected(client):
    uid = "weak_pin_" + str(time.time_ns())
    resp = client.post("/api/auth/register", json={
        "firebase_uid": uid,
        "pin": "1234",
    }, headers=_headers(uid))
    assert resp.status_code == 400


def test_register_non_numeric_pin_rejected(client):
    uid = "alpha_pin_" + str(time.time_ns())
    resp = client.post("/api/auth/register", json={
        "firebase_uid": uid,
        "pin": "abcd",
    }, headers=_headers(uid))
    assert resp.status_code == 400


def test_get_me(client, auth_headers, registered_user):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()["user"]["firebase_uid"] == registered_user["uid"]
