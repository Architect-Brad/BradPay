"""Tests for the BradTrade engine — order matching and execution."""


def test_place_buy_order(client, auth_headers, registered_user):
    resp = client.post("/api/trade/orders", json={
        "type": "buy", "price": 50, "amount": 10000,
    }, headers=auth_headers)
    assert resp.status_code == 201, resp.get_json()
    data = resp.get_json()
    assert data["order"]["type"] == "buy"
    assert data["order"]["status"] == "open"


def test_place_sell_order(client, auth_headers, registered_user):
    resp = client.post("/api/trade/orders", json={
        "type": "sell", "price": 60, "amount": 5000,
    }, headers=auth_headers)
    assert resp.status_code == 201, resp.get_json()
    data = resp.get_json()
    assert data["order"]["type"] == "sell"
    assert data["order"]["status"] == "open"


def test_place_order_invalid_type(client, auth_headers):
    resp = client.post("/api/trade/orders", json={
        "type": "invalid", "price": 50, "amount": 1000,
    }, headers=auth_headers)
    assert resp.status_code == 400


def test_get_orderbook_empty(client, auth_headers):
    resp = client.get("/api/trade/orderbook", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "bids" in data
    assert "asks" in data


def test_get_orderbook_with_orders(client, auth_headers, registered_user):
    client.post("/api/trade/orders", json={
        "type": "buy", "price": 50, "amount": 10000,
    }, headers=auth_headers)
    client.post("/api/trade/orders", json={
        "type": "sell", "price": 60, "amount": 5000,
    }, headers=auth_headers)
    resp = client.get("/api/trade/orderbook", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["bids"]) > 0
    assert len(data["asks"]) > 0


def test_get_my_orders(client, auth_headers, registered_user):
    client.post("/api/trade/orders", json={
        "type": "buy", "price": 50, "amount": 10000,
    }, headers=auth_headers)
    resp = client.get("/api/trade/orders", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "orders" in data
    assert len(data["orders"]) >= 1


def test_cancel_order(client, auth_headers, registered_user):
    resp = client.post("/api/trade/orders", json={
        "type": "buy", "price": 50, "amount": 10000,
    }, headers=auth_headers)
    order_id = resp.get_json()["order"]["id"]
    resp = client.delete(f"/api/trade/orders/{order_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()["message"] == "Order cancelled"


def test_cancel_nonexistent_order(client, auth_headers):
    resp = client.delete("/api/trade/orders/999999", headers=auth_headers)
    assert resp.status_code == 404


def test_trade_balance(client, auth_headers, registered_user):
    resp = client.get("/api/trade/balance", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "available" in data
    assert "locked" in data


def test_trade_history(client, auth_headers, registered_user):
    resp = client.get("/api/trade/trades", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "trades" in data


def test_trade_recent(client, auth_headers):
    resp = client.get("/api/trade/recent", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "trades" in data


def test_order_matching(client, auth_headers, second_headers, registered_user, second_user):
    client.post("/api/trade/orders", json={
        "type": "sell", "price": 50, "amount": 10000,
    }, headers=auth_headers)
    resp = client.post("/api/trade/orders", json={
        "type": "buy", "price": 60, "amount": 5000,
    }, headers=second_headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert "trades" in data


def test_place_order_requires_auth(client):
    resp = client.post("/api/trade/orders", json={
        "type": "buy", "price": 50, "amount": 1000,
    })
    assert resp.status_code == 401


def test_cancel_order_wrong_user(client, auth_headers, second_headers, registered_user, second_user):
    resp = client.post("/api/trade/orders", json={
        "type": "buy", "price": 50, "amount": 10000,
    }, headers=auth_headers)
    order_id = resp.get_json()["order"]["id"]
    resp = client.delete(f"/api/trade/orders/{order_id}", headers=second_headers)
    assert resp.status_code == 404
