import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "bradpay-web")
    FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY")
    FIREBASE_AUTH_DOMAIN = os.getenv("FIREBASE_AUTH_DOMAIN")
    SECRET_KEY = os.getenv("SECRET_KEY")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bradpay.db")
    ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
    TEST_MODE = os.getenv("TEST_MODE", "0") == "1"
    FAUCET_AMOUNT = int(os.getenv("FAUCET_AMOUNT", "10000000"))
    FIREBASE_JWKS_URL = (
        f"https://www.googleapis.com/robot/v1/metadata/x509/"
        f"securetoken@system.gserviceaccount.com"
    )
    FIREBASE_ISSUER = f"https://securetoken.google.com/{FIREBASE_PROJECT_ID}"
