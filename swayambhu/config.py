import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "local-development-key-change-before-deployment")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql+psycopg://", 1
        )
    elif SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgresql://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    REMEMBER_COOKIE_HTTPONLY = True
    WTF_CSRF_TIME_LIMIT = None
    AUTO_INIT_DB = os.getenv(
        "AUTO_INIT_DB", "false" if os.getenv("APP_ENV", "development").lower() == "production" else "true"
    ).lower() == "true"

    @staticmethod
    def validate_runtime():
        if os.getenv("APP_ENV", "development").lower() == "production":
            if not os.getenv("SECRET_KEY") or len(os.environ["SECRET_KEY"]) < 32:
                raise RuntimeError("Set a random SECRET_KEY of at least 32 characters in production.")
            if os.getenv("COOKIE_SECURE", "false").lower() != "true":
                raise RuntimeError("Set COOKIE_SECURE=true when deployed behind HTTPS.")
            if not os.getenv("DATABASE_URL", "").startswith(
                ("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")
            ):
                raise RuntimeError("Production must use PostgreSQL via DATABASE_URL.")
