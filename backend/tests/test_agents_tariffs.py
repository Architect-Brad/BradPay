"""Tests for agent registration, float management, cash-in/cash-out, and tariffs."""


def test_list_tariffs(client):
    resp = client.get("/api/tariffs")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "tariffs" in data
    assert len(data["tariffs"]) >= 5


def test_get_tariffs_by_type(client):
    resp = client.get("/api/tariffs/withdrawal")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "tariffs" in data
    assert all(t["type"] == "withdrawal" for t in data["tariffs"])


def test_create_and_update_tariff(client, admin_headers):
    resp = client.post("/api/tariffs", json={
        "name": "Test Fee",
        "type": "transfer",
        "percentage": 50,
        "flat_fee": 1000,
    }, headers=admin_headers)
    assert resp.status_code == 201, resp.get_json()
    tariff = resp.get_json()["tariff"]
    tariff_id = tariff["id"]

    resp = client.patch(f"/api/tariffs/{tariff_id}", json={
        "percentage": 100,
        "flat_fee": 2000,
    }, headers=admin_headers)
    assert resp.status_code == 200
    updated = resp.get_json()["tariff"]
    assert updated["percentage"] == 100
    assert updated["flat_fee"] == 2000


def test_create_tariff_missing_name(client, admin_headers):
    resp = client.post("/api/tariffs", json={
        "type": "transfer",
    }, headers=admin_headers)
    assert resp.status_code == 400


def test_create_tariff_requires_admin(client, auth_headers):
    resp = client.post("/api/tariffs", json={
        "name": "Bad Fee",
        "type": "transfer",
    }, headers=auth_headers)
    assert resp.status_code == 401


def test_agent_register_success(client, auth_headers, registered_user):
    resp = client.post("/api/agents/register", json={
        "business_name": "Test Shop",
        "contact_phone": "+254712345678",
        "location": "Nairobi",
        "id_number": "ID12345",
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["agent"]["status"] == "pending"


def test_agent_register_duplicate(client, auth_headers, registered_user):
    client.post("/api/agents/register", json={
        "business_name": "Test Shop",
        "contact_phone": "+254712345678",
        "location": "Nairobi",
        "id_number": "ID12345",
    }, headers=auth_headers)
    resp = client.post("/api/agents/register", json={
        "business_name": "Test Shop",
        "contact_phone": "+254712345678",
        "location": "Nairobi",
        "id_number": "ID12345",
    }, headers=auth_headers)
    assert resp.status_code == 409


def test_agent_profile(client, auth_headers, registered_user):
    client.post("/api/agents/register", json={
        "business_name": "Test Shop", "contact_phone": "+254712345678",
        "location": "Nairobi", "id_number": "ID12345",
    }, headers=auth_headers)
    resp = client.get("/api/agents/profile", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "agent" in data


def test_agent_verify(client, auth_headers, admin_headers, registered_user):
    client.post("/api/agents/register", json={
        "business_name": "Test Shop", "contact_phone": "+254712345678",
        "location": "Nairobi", "id_number": "ID12345",
    }, headers=auth_headers)
    # Non-admin must not be able to verify
    denied = client.post("/api/agents/verify", json={
        "agent_uid": registered_user["uid"],
        "status": "active",
    }, headers=auth_headers)
    assert denied.status_code == 401
    resp = client.post("/api/agents/verify", json={
        "agent_uid": registered_user["uid"],
        "status": "active",
    }, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()["agent_uid"] == registered_user["uid"]


def test_agent_float_topup(client, auth_headers, admin_headers, registered_user):
    client.post("/api/agents/register", json={
        "business_name": "Test Shop", "contact_phone": "+254712345678",
        "location": "Nairobi", "id_number": "ID12345",
    }, headers=auth_headers)
    client.post("/api/agents/verify", json={
        "agent_uid": registered_user["uid"], "status": "active",
    }, headers=admin_headers)
    resp = client.post("/api/agents/float-topup", json={
        "amount": 500000,
    }, headers=auth_headers)
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert "amount" in data


def test_agent_cash_in(client, auth_headers, admin_headers, registered_user, second_user, second_headers):
    client.post("/api/agents/register", json={
        "business_name": "Test Shop", "contact_phone": "+254712345678",
        "location": "Nairobi", "id_number": "ID12345",
    }, headers=auth_headers)
    client.post("/api/agents/verify", json={
        "agent_uid": registered_user["uid"], "status": "active",
    }, headers=admin_headers)
    client.post("/api/agents/float-topup", json={
        "amount": 500000,
    }, headers=auth_headers)
    resp = client.post("/api/agents/cash-in", json={
        "phone": "+254700000002",
        "amount": 10000,
    }, headers=auth_headers)
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["message"] == "Cash-in successful"


def test_agent_cash_out(client, auth_headers, admin_headers, registered_user, second_user, second_headers):
    client.post("/api/agents/register", json={
        "business_name": "Test Shop", "contact_phone": "+254712345678",
        "location": "Nairobi", "id_number": "ID12345",
    }, headers=auth_headers)
    client.post("/api/agents/verify", json={
        "agent_uid": registered_user["uid"], "status": "active",
    }, headers=admin_headers)
    client.post("/api/agents/float-topup", json={
        "amount": 500000,
    }, headers=auth_headers)
    client.post("/api/agents/cash-in", json={
        "phone": "+254700000002",
        "amount": 50000,
    }, headers=auth_headers)
    resp = client.post("/api/agents/cash-out", json={
        "phone": "+254700000002",
        "amount": 10000,
    }, headers=auth_headers)
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["message"] == "Cash-out successful"


def test_agent_list_all(client, auth_headers, admin_headers, registered_user):
    client.post("/api/agents/register", json={
        "business_name": "Test Shop", "contact_phone": "+254712345678",
        "location": "Nairobi", "id_number": "ID12345",
    }, headers=auth_headers)
    denied = client.get("/api/agents/all", headers=auth_headers)
    assert denied.status_code == 401
    resp = client.get("/api/agents/all", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "agents" in data


def test_agent_float_transfer_success(client, auth_headers, second_headers, admin_headers, registered_user, second_user):
    client.post("/api/agents/register", json={
        "business_name": "Agent A", "contact_phone": "+254712345678",
        "location": "Nairobi", "id_number": "ID001",
    }, headers=auth_headers)
    client.post("/api/agents/register", json={
        "business_name": "Agent B", "contact_phone": "+254798765432",
        "location": "Mombasa", "id_number": "ID002",
    }, headers=second_headers)
    client.post("/api/agents/verify", json={
        "agent_uid": registered_user["uid"], "status": "active",
    }, headers=admin_headers)
    client.post("/api/agents/verify", json={
        "agent_uid": second_user["uid"], "status": "active",
    }, headers=admin_headers)
    client.post("/api/agents/float-topup", json={
        "amount": 200000,
    }, headers=auth_headers)

    resp = client.post("/api/agents/float/transfer", json={
        "to_agent_uid": second_user["uid"],
        "amount": 50000,
    }, headers=auth_headers)
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert "Float transfer" in data["message"]
    assert data["amount"] == 50000


def test_agent_float_transfer_insufficient(client, auth_headers, second_headers, admin_headers, second_user, registered_user):
    client.post("/api/agents/register", json={
        "business_name": "Agent A", "contact_phone": "+254712345678",
        "location": "Nairobi", "id_number": "ID001",
    }, headers=auth_headers)
    client.post("/api/agents/verify", json={
        "agent_uid": registered_user["uid"], "status": "active",
    }, headers=admin_headers)
    client.post("/api/agents/register", json={
        "business_name": "Agent B", "contact_phone": "+254798765432",
        "location": "Mombasa", "id_number": "ID002",
    }, headers=second_headers)
    client.post("/api/agents/verify", json={
        "agent_uid": second_user["uid"], "status": "active",
    }, headers=admin_headers)

    resp = client.post("/api/agents/float/transfer", json={
        "to_agent_uid": second_user["uid"],
        "amount": 999999999,
    }, headers=auth_headers)
    assert resp.status_code == 400
    assert "Insufficient" in resp.get_json()["error"]


def test_agent_float_transfer_missing_params(client, auth_headers):
    resp = client.post("/api/agents/float/transfer", json={}, headers=auth_headers)
    assert resp.status_code == 400


def test_agent_float_transfer_not_agent(client, auth_headers):
    resp = client.post("/api/agents/float/transfer", json={
        "to_agent_uid": "someone", "amount": 1000,
    }, headers=auth_headers)
    assert resp.status_code == 404

