"""Tests for M-PESA Daraja integration — mocked HTTP to avoid real API calls."""

from unittest.mock import patch


class MockResponse:
    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP Error")


def test_stkpush_success(client, auth_headers, registered_user):
    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        mock_get.return_value = MockResponse({"access_token": "test_token"})
        mock_post.return_value = MockResponse({
            "ResponseCode": "0",
            "ResponseDescription": "Success",
            "CheckoutRequestID": "ws_CO_12345",
            "MerchantRequestID": "29115-34620561-1",
        })
        resp = client.post("/api/daraja/stkpush", json={
            "phone": "254708374149",
            "amount": 10000,
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "checkout_id" in data


def test_stkpush_missing_fields(client, auth_headers):
    resp = client.post("/api/daraja/stkpush", json={
        "phone": "254708374149",
    }, headers=auth_headers)
    assert resp.status_code == 400


def test_b2c_missing_fields(client, auth_headers):
    resp = client.post("/api/daraja/b2c", json={
        "phone": "254708374149",
    }, headers=auth_headers)
    assert resp.status_code == 400


def test_daraja_transactions(client, auth_headers, registered_user):
    resp = client.get("/api/daraja/transactions", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "transactions" in data


def test_daraja_balance(client, auth_headers, registered_user):
    resp = client.get("/api/daraja/balance", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "kes_balance" in data
