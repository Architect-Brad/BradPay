import os
import requests
import jwt
from datetime import datetime, timezone
from config import Config

# Cache for Firebase public keys
_cached_keys = None
_cached_keys_expiry = 0


def _get_firebase_public_keys():
    global _cached_keys, _cached_keys_expiry
    now = datetime.now(timezone.utc).timestamp()
    if _cached_keys and now < _cached_keys_expiry:
        return _cached_keys

    resp = requests.get(Config.FIREBASE_JWKS_URL, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    # The response includes Cache-Control headers; use them
    cache_control = resp.headers.get("Cache-Control", "")
    max_age = 3600
    if "max-age=" in cache_control:
        try:
            max_age = int(cache_control.split("max-age=")[1].split(",")[0])
        except (ValueError, IndexError):
            pass

    _cached_keys = data
    _cached_keys_expiry = now + max_age
    return _cached_keys


def verify_firebase_token(id_token):
    if os.environ.get("TEST_MODE"):
        return {"valid": True, "uid": id_token, "email": f"{id_token}@test.com", "name": "Test User"}

    try:
        keys = _get_firebase_public_keys()

        header = jwt.get_unverified_header(id_token)
        kid = header.get("kid")
        if not kid or kid not in keys:
            return {"valid": False, "error": "Invalid key ID"}

        public_key = keys[kid]

        payload = jwt.decode(
            id_token,
            key=public_key,
            algorithms=["RS256"],
            audience=Config.FIREBASE_PROJECT_ID,
            issuer=Config.FIREBASE_ISSUER,
            options={"verify_exp": True},
        )

        return {
            "valid": True,
            "uid": payload["sub"],
            "email": payload.get("email"),
            "phone": payload.get("phone_number"),
            "name": payload.get("name"),
            "payload": payload,
        }
    except jwt.ExpiredSignatureError:
        return {"valid": False, "error": "Token expired"}
    except jwt.InvalidTokenError as e:
        return {"valid": False, "error": str(e)}
    except requests.RequestException as e:
        return {"valid": False, "error": f"Failed to fetch keys: {e}"}
    except Exception as e:
        return {"valid": False, "error": str(e)}
