from flask import Flask, send_from_directory
from flask_cors import CORS
import os
from config import Config
from data import init_db, get_active_tariffs, create_tariff
from routes.auth_routes import auth_bp
from routes.transaction_routes import tx_bp
from routes.ledger_routes import ledger_bp
from routes.trade_routes import trade_bp
from routes.daraja_routes import daraja_bp
from routes.ussd_routes import ussd_bp
from routes.agent_routes import agent_bp
from routes.tariff_routes import tariff_bp
from routes.admin_routes import admin_bp
from routes.security_routes import security_bp
from bradsec import init_bradsec
from ledger import init_ledger

PLACEHOLDER_SECRETS = {
    "change-this-in-production-to-a-random-secret",
    "replace-with-a-random-64-char-string",
}


def _check_production_secrets():
    """Refuse to boot with a placeholder SECRET_KEY once we're not in local
    dev/test - a guessable Flask secret key lets an attacker forge session
    cookies and tokens signed with it."""
    if Config.TEST_MODE:
        return
    is_production = os.environ.get("FLASK_ENV") == "production" or os.environ.get("VERCEL")
    if not is_production:
        return
    if not Config.SECRET_KEY or Config.SECRET_KEY in PLACEHOLDER_SECRETS:
        raise RuntimeError(
            "SECRET_KEY is missing or is a placeholder value. Set a real random "
            "secret (e.g. `python -c \"import secrets; print(secrets.token_hex(32))\"`) "
            "in your environment before deploying."
        )
    # Note: ADMIN_API_KEY is intentionally not required here - admin_routes
    # already returns 500 on every admin call if it's unset, which is a safe
    # default (admin endpoints simply stay disabled rather than open).


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    _check_production_secrets()

    allowed_origins = [
        o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
    ]
    if not allowed_origins:
        # Safe default for local development only. Production deployments
        # must set ALLOWED_ORIGINS explicitly - a "*" CORS policy on
        # endpoints that use cookie/bearer auth allows any website to read
        # authenticated responses via the victim's browser.
        allowed_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)

    if not os.environ.get("BRADPAY_LEDGER_PATH"):
        os.environ["BRADPAY_LEDGER_PATH"] = "/tmp/bradledger.json"

    app.register_blueprint(auth_bp)
    app.register_blueprint(tx_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(trade_bp)
    app.register_blueprint(daraja_bp)
    app.register_blueprint(ussd_bp)
    app.register_blueprint(agent_bp)
    app.register_blueprint(tariff_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(security_bp)

    frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

    @app.route("/")
    def index():
        return send_from_directory(frontend_path, "landing.html")

    @app.route("/app")
    def app_spa():
        return send_from_directory(frontend_path, "index.html")

    @app.route("/dev")
    def dev_console():
        return send_from_directory(frontend_path, "dev.html")

    @app.route("/<path:path>")
    def static_files(path):
        return send_from_directory(frontend_path, path)

    with app.app_context():
        init_db()
        init_ledger()
        init_bradsec()
        if not get_active_tariffs():
            create_tariff("P2P Transfer", "transfer", percentage=0, flat_fee=0)
            create_tariff("Agent Commission", "agent_commission", percentage=100)
            create_tariff("M-PESA Deposit", "deposit", percentage=0, flat_fee=0)
            create_tariff("M-PESA Withdrawal (< 1000 KES)", "withdrawal", percentage=0, flat_fee=3000)
            create_tariff("M-PESA Withdrawal (>= 1000 KES)", "withdrawal", percentage=100, min_amount=100000)

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
