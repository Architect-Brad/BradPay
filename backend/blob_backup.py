"""Vercel Blob backup for the BradPay ledger.
Saves ledger JSON snapshots to persistent blob storage so data
survives cold starts on Vercel's ephemeral filesystem.
"""

import os
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

BLOB_API = "https://api.vercel.com/v1/blob"
BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")


def _put(path, data):
    if not BLOB_TOKEN:
        return None
    url = f"{BLOB_API}/put/{path.lstrip('/')}"
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"))
    req.add_header("Authorization", f"Bearer {BLOB_TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        logger.warning("Blob backup failed (HTTP %s): %s", e.code, e.read().decode())
        return None
    except Exception as e:
        logger.warning("Blob backup failed: %s", e)
        return None


def _get(path):
    if not BLOB_TOKEN:
        return None
    url = f"{BLOB_API}/get/{path.lstrip('/')}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {BLOB_TOKEN}")
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        logger.warning("Blob restore failed (HTTP %s): %s", e.code, e.read().decode())
        return None
    except Exception as e:
        logger.warning("Blob restore failed: %s", e)
        return None


def backup_ledger(chain_data):
    return _put("bradpay/ledger.json", chain_data)


def restore_ledger():
    return _get("bradpay/ledger.json")
