import os
import ipaddress
import logging
from functools import wraps
from flask import request, jsonify, current_app

logger = logging.getLogger(__name__)


def _ip_in_cidr(ip_str, cidr_str):
    try:
        addr = ipaddress.ip_address(ip_str)
        network = ipaddress.ip_network(cidr_str, strict=False)
        return addr in network
    except ValueError:
        return False


def _client_ip():
    """Prefer first X-Forwarded-For hop (Vercel/proxy), then remote_addr."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        # Left-most is the original client when proxies append.
        return xff.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    return request.remote_addr or ""


def require_safaricom_ip(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Local/test bypass
        if current_app.config.get("TESTING") or os.environ.get("TEST_MODE") == "1":
            return f(*args, **kwargs)

        ip = _client_ip()
        if not ip:
            return jsonify({"ResultCode": 1, "ResultDesc": "Unknown origin"}), 403

        raw = current_app.config.get("SAFARICOM_IPS", "")
        cidrs = [c.strip() for c in raw.split(",") if c.strip()]

        if not cidrs:
            logger.warning("No Safaricom IPs configured — allowing all callback IPs")
            return f(*args, **kwargs)

        for cidr in cidrs:
            if _ip_in_cidr(ip, cidr):
                return f(*args, **kwargs)

        logger.warning("Rejected callback from non-Safaricom IP: %s", ip)
        return jsonify({"ResultCode": 1, "ResultDesc": "Forbidden"}), 403

    return decorated
