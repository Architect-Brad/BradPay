"""Tests for transaction endpoints."""


def test_send_kes_success(client, auth_headers, registered_user, second_user, second_headers):
    resp = client.post("/api/transactions/send", json={
        "recipientUid": second_user["uid"],
        "amount": 10000,
        "pin": "8146",
        "note": "test payment",
    }, headers=auth_headers)
    assert resp.status_code == 201, resp.get_json()
    data = resp.get_json()
    assert "transaction" in data


def test_send_kes_insufficient_balance(client, auth_headers, registered_user, second_user):
    resp = client.post("/api/transactions/send", json={
        "recipientUid": second_user["uid"],
        "amount": 999999999,
        "pin": "8146",
    }, headers=auth_headers)
    assert resp.status_code == 400
    assert "insufficient" in resp.get_json().get("error", "").lower()


def test_send_kes_nonexistent_recipient(client, auth_headers, registered_user):
    resp = client.post("/api/transactions/send", json={
        "recipientUid": "nobody_firebase_uid",
        "amount": 100,
        "pin": "8146",
    }, headers=auth_headers)
    assert resp.status_code == 404


def test_send_kes_self(client, auth_headers, registered_user):
    resp = client.post("/api/transactions/send", json={
        "recipientUid": registered_user["uid"],
        "amount": 100,
        "pin": "8146",
    }, headers=auth_headers)
    assert resp.status_code == 400
    assert "yourself" in resp.get_json().get("error", "").lower()


def test_offline_id_idempotent(client, auth_headers, registered_user, second_user):
    body = {
        "recipientUid": second_user["uid"],
        "amount": 500,
        "pin": "8146",
        "offlineId": "offline-unique-abc-123",
    }
    r1 = client.post("/api/transactions/send", json=body, headers=auth_headers)
    assert r1.status_code == 201, r1.get_json()
    bal1 = client.get("/api/transactions/balance", headers=auth_headers).get_json()["balance"]
    r2 = client.post("/api/transactions/send", json=body, headers=auth_headers)
    assert r2.status_code == 201
    bal2 = client.get("/api/transactions/balance", headers=auth_headers).get_json()["balance"]
    assert bal1 == bal2
    assert r2.get_json()["transaction"].get("idempotent_replay") is True


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


def test_transfer_fee_is_applied(client, auth_headers, registered_user, second_user):
    """A configured transfer tariff must actually be deducted - previously
    fees were computed nowhere and every transfer was fee-free regardless
    of the tariffs table."""
    from data import create_tariff, update_tariff, get_tariff_by_type

    existing = get_tariff_by_type("transfer")
    for t in existing:
        update_tariff(t["id"], is_active=0)

    new_tariff = create_tariff("Test P2P fee", "transfer", percentage=500, flat_fee=10)  # 5% + 10 cents

    try:
        resp = client.post("/api/transactions/send", json={
            "recipientUid": second_user["uid"],
            "amount": 10000,
            "pin": "8146",
        }, headers=auth_headers)
        assert resp.status_code == 201, resp.get_json()
        tx = resp.get_json()["transaction"]
        assert tx["fee"] == 10 + (10000 * 500) // 10000  # flat_fee + percentage cut
    finally:
        # Restore original tariff config so later tests see fee-free transfers.
        update_tariff(new_tariff["id"], is_active=0)
        for t in existing:
            update_tariff(t["id"], is_active=1)


def test_concurrent_transfers_cannot_overdraw(client, app):
    """Two concurrent sends that would each individually be affordable, but
    not both together, must not both succeed - this is the TOCTOU race that
    was previously possible because the balance check and the balance
    update were separate, unguarded statements."""
    import threading
    import time as _time
    from models import get_db

    conn = get_db()
    sender_uid = "race_sender_" + str(_time.time_ns())
    recipient_uid = "race_recipient_" + str(_time.time_ns())
    for uid in (sender_uid, recipient_uid):
        conn.execute(
            "INSERT INTO users (firebase_uid, display_name, pin_hash, balance) VALUES (?, ?, 'x', 0)",
            (uid, uid),
        )
    conn.execute("UPDATE users SET balance = 100 WHERE firebase_uid = ?", (sender_uid,))
    conn.commit()
    conn.close()

    from data import create_transaction

    results = []

    def _attempt():
        with app.app_context():
            results.append(create_transaction(sender_uid, recipient_uid, 100))

    threads = [threading.Thread(target=_attempt) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [r for r in results if isinstance(r, dict) and "error" not in r]
    assert len(successes) == 1, f"expected exactly 1 success out of 5 concurrent attempts, got {len(successes)}: {results}"

    conn = get_db()
    final_balance = conn.execute(
        "SELECT balance FROM users WHERE firebase_uid = ?", (sender_uid,)
    ).fetchone()["balance"]
    conn.close()
    assert final_balance == 0
