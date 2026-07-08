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


def require_safaricom_ip(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr or ""
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
