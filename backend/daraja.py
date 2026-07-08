import os
import base64
import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

ENV = os.environ.get("MPESA_ENV", "sandbox")
BASE_URL = (
    "https://sandbox.safaricom.co.ke"
    if ENV == "sandbox"
    else "https://api.safaricom.co.ke"
)

CONSUMER_KEY = os.environ.get("MPESA_CONSUMER_KEY", "")
CONSUMER_SECRET = os.environ.get("MPESA_CONSUMER_SECRET", "")
PASSKEY = os.environ.get("MPESA_PASSKEY", "")
SHORTCODE = os.environ.get("MPESA_SHORTCODE", "174379")
B2C_SHORTCODE = os.environ.get("MPESA_B2C_SHORTCODE", SHORTCODE)
INITIATOR_NAME = os.environ.get("MPESA_INITIATOR_NAME", "testapi")
SECURITY_CREDENTIAL = os.environ.get("MPESA_SECURITY_CREDENTIAL", "")

_access_token = None
_token_expiry = 0


def _get_timestamp():
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _generate_password():
    timestamp = _get_timestamp()
    raw = f"{SHORTCODE}{PASSKEY}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


def _get_access_token():
    global _access_token, _token_expiry
    if _access_token and datetime.now().timestamp() < _token_expiry:
        return _access_token

    url = f"{BASE_URL}/oauth/v1/generate?grant_type=client_credentials"
    auth = base64.b64encode(f"{CONSUMER_KEY}:{CONSUMER_SECRET}".encode()).decode()

    try:
        resp = requests.get(
            url, headers={"Authorization": f"Basic {auth}"}, timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        _access_token = data.get("access_token")
        expires_in = int(data.get("expires_in", 3600))
        _token_expiry = datetime.now().timestamp() + expires_in - 60
        return _access_token
    except Exception as e:
        logger.error(f"Failed to get Daraja access token: {e}")
        return None


def stk_push(phone, amount, account_ref="BradPay", callback_url=None):
    token = _get_access_token()
    if not token:
        return {"error": "Failed to authenticate with Daraja"}

    timestamp = _get_timestamp()
    password = _generate_password()

    payload = {
        "BusinessShortCode": SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": str(amount),
        "PartyA": phone,
        "PartyB": SHORTCODE,
        "PhoneNumber": phone,
        "CallBackURL": callback_url or "",
        "AccountReference": account_ref[:12],
        "TransactionDesc": "Deposit to BradPay",
    }

    url = f"{BASE_URL}/mpesa/stkpush/v1/processrequest"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"STK Push failed: {e}")
        return {"error": str(e)}


def b2c(phone, amount, remarks="Withdrawal from BradPay", callback_url=None, timeout_url=None):
    token = _get_access_token()
    if not token:
        return {"error": "Failed to authenticate with Daraja"}

    payload = {
        "InitiatorName": INITIATOR_NAME,
        "SecurityCredential": SECURITY_CREDENTIAL,
        "CommandID": "BusinessPayment",
        "Amount": str(amount),
        "PartyA": B2C_SHORTCODE,
        "PartyB": phone,
        "Remarks": remarks,
        "QueueTimeOutURL": timeout_url or "",
        "ResultURL": callback_url or "",
        "Occasion": "",
    }

    url = f"{BASE_URL}/mpesa/b2c/v1/paymentrequest"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"B2C failed: {e}")
        return {"error": str(e)}


def query_status(checkout_id):
    token = _get_access_token()
    if not token:
        return {"error": "Failed to authenticate with Daraja"}

    timestamp = _get_timestamp()
    password = _generate_password()

    payload = {
        "BusinessShortCode": SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_id,
    }

    url = f"{BASE_URL}/mpesa/stkpushquery/v1/query"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Query status failed: {e}")
        return {"error": str(e)}
