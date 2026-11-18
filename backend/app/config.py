import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")  # backend/.env, if present; variables already set (e.g. by the tests) win

# PostgreSQL. DATABASE_USER / DATABASE_PASSWORD are used when the URL has no user of its own, so the password
# needs no URL-encoding.
DATABASE_URL = os.environ.get("DATABASE_URL") or "postgresql://127.0.0.1:5432/demandforecasting"
DATABASE_USER = os.environ.get("DATABASE_USER", "")
DATABASE_PASSWORD = os.environ.get("DATABASE_PASSWORD", "")
