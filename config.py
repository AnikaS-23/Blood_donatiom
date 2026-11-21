import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production-9x2k")

    # ── Database ──────────────────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(BASE_DIR, "blood_portal.db"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── SocketIO ──────────────────────────────────────────────────────────────
    SOCKETIO_ASYNC_MODE = "threading"

    # ── Low-stock alert defaults (units) ─────────────────────────────────────
    DEFAULT_LOW_STOCK_THRESHOLD = 5
    EXPIRY_WARNING_DAYS = 7

    # ── Geo matching ─────────────────────────────────────────────────────────
    NEARBY_RADIUS_KM = 50          # max km radius to search blood banks


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = False        # set True to see SQL queries


class ProductionConfig(Config):
    DEBUG = False


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
