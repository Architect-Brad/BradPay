"""Tests for BradLedger blockchain."""


def test_ledger_status(client):
    resp = client.get("/api/ledger/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "blocks" in data
    assert data["blocks"] >= 1


def test_ledger_chain(client):
    resp = client.get("/api/ledger/chain")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "chain" in data
    assert len(data["chain"]) >= 1
    assert data["valid"] is True


def test_ledger_chain_pagination(client):
    resp = client.get("/api/ledger/chain?page=1&per_page=5")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "chain" in data


def test_ledger_block(client):
    resp = client.get("/api/ledger/block/0")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["block"]["index"] == 0


def test_ledger_block_not_found(client):
    resp = client.get("/api/ledger/block/9999")
    assert resp.status_code == 404


def test_ledger_blocks_after_transaction(client, auth_headers, registered_user, second_user):
    initial = client.get("/api/ledger/status").get_json()
    initial_count = initial["blocks"]

    client.post("/api/transactions/send", json={
        "recipientUid": second_user["uid"],
        "amount": 5000,
        "pin": "8146",
    }, headers=auth_headers)

    client.post("/api/ledger/mine", headers=auth_headers)

    after = client.get("/api/ledger/status").get_json()
    assert after["blocks"] > initial_count


def test_ledger_persists_across_cold_start(client, app, auth_headers, registered_user, second_user):
    """Simulates a serverless cold start: a fresh process must rebuild the
    ledger from the database, not lose it because a local /tmp file was
    wiped. Previously the chain lived only in an in-memory singleton backed
    by an ephemeral file, so a new instance would silently start over from
    genesis."""
    import ledger as ledger_module

    client.post("/api/transactions/send", json={
        "recipientUid": second_user["uid"],
        "amount": 1234,
        "pin": "8146",
    }, headers=auth_headers)
    client.post("/api/ledger/mine", headers=auth_headers)

    before = client.get("/api/ledger/status").get_json()
    assert before["blocks"] >= 2

    # Simulate a new process/instance: drop the singleton and reload.
    ledger_module._ledger = None
    with app.app_context():
        reloaded = ledger_module.get_ledger()
    assert reloaded.get_chain()["length"] == before["blocks"]
    assert reloaded.validate() is True
