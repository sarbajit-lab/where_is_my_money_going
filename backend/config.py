"""WIMMG settings. Override any of these with environment variables if needed."""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HOST = os.environ.get("WIMMG_HOST", "127.0.0.1")          # localhost only: not reachable from other devices
PORT = int(os.environ.get("WIMMG_PORT", "5000"))

DATA_DIR = os.environ.get("WIMMG_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.environ.get("WIMMG_DB_PATH", os.path.join(DATA_DIR, "wimmg.db"))
BACKUP_DIR = os.environ.get("WIMMG_BACKUP_DIR", os.path.join(BASE_DIR, "backups"))
EXPORT_DIR = os.path.join(BASE_DIR, "exports")

VERSION_FILE = os.path.join(BASE_DIR, "VERSION")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
MIGRATIONS_DIR = os.path.join(BASE_DIR, "backend", "migrations")



def app_version():
    try:
        with open(VERSION_FILE, encoding="utf-8") as fh:
            return fh.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"
