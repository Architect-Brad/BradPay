from flask import Flask, send_from_directory
from flask_cors import CORS
import os
from config import Config
from data import init_db
from routes.auth_routes import auth_bp
from routes.transaction_routes import tx_bp
from routes.ledger_routes import ledger_bp
from ledger import init_ledger


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    if not os.environ.get("BRADPAY_LEDGER_PATH"):
        os.environ["BRADPAY_LEDGER_PATH"] = "/tmp/bradledger.json"

    app.register_blueprint(auth_bp)
    app.register_blueprint(tx_bp)
    app.register_blueprint(ledger_bp)

    frontend_path = os.path.dirname(os.path.dirname(__file__))

    @app.route("/")
    def index():
        return send_from_directory(frontend_path, "index.html")

    @app.route("/<path:path>")
    def static_files(path):
        return send_from_directory(frontend_path, path)

    with app.app_context():
        init_db()
        init_ledger()

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
