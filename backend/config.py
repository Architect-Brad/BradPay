import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "bradpay-web")
    FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY")
    FIREBASE_AUTH_DOMAIN = os.getenv("FIREBASE_AUTH_DOMAIN")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bradpay.db")
    FIREBASE_JWKS_URL = (
        f"https://www.googleapis.com/robot/v1/metadata/x509/"
        f"securetoken@system.gserviceaccount.com"
    )
    FIREBASE_ISSUER = f"https://securetoken.google.com/{FIREBASE_PROJECT_ID}"
