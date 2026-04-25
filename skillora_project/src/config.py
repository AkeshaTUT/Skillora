import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # skillora_project/
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Load .env from project root if present
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Database  (PostgreSQL when Docker is up, SQLite otherwise)
# ---------------------------------------------------------------------------
DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "skillora_db")
DB_PORT = os.getenv("DB_PORT", "5432")

POSTGRES_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
SQLITE_URL = f"sqlite:///{DATA_DIR / 'skillora.db'}"

# Use SKILLORA_DATABASE_URL env var if set, else try Postgres, fallback to SQLite
DATABASE_URL = os.getenv("SKILLORA_DATABASE_URL", "")
if not DATABASE_URL:
    try:
        import socket
        s = socket.create_connection((DB_HOST, int(DB_PORT)), timeout=1)
        s.close()
        DATABASE_URL = POSTGRES_URL
    except OSError:
        DATABASE_URL = SQLITE_URL

# ---------------------------------------------------------------------------
# Collector settings
# ---------------------------------------------------------------------------
SCHEDULER_INTERVAL_HOURS = int(os.getenv("SCHEDULER_INTERVAL_HOURS", "6"))


# ---------------------------------------------------------------------------
# API / Security
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))

# Service account for admin endpoints
API_ADMIN_USERNAME = os.getenv("API_ADMIN_USERNAME", "admin")
API_ADMIN_PASSWORD = os.getenv("API_ADMIN_PASSWORD", "admin123")
API_ADMIN_PASSWORD_HASH = os.getenv("API_ADMIN_PASSWORD_HASH", "")


# ---------------------------------------------------------------------------
# API / CORS
# ---------------------------------------------------------------------------
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]


# ---------------------------------------------------------------------------
# Optional Redis cache
# ---------------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "")
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "false").lower() in {"1", "true", "yes"}
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))
