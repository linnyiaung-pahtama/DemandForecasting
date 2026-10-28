import os
from pathlib import Path

DB_PATH = Path(
    os.environ.get("ORDERPLAN_DB")
    or Path(__file__).resolve().parent.parent / "data" / "orderplan.db"
)
