import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # skillora_project/
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

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
