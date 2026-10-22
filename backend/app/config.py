import os
from pathlib import Path

DEFAULT_REORDER_DAYS = 20
DEFAULT_TARGET_DAYS = 30
EXCESS_FACTOR = 1.5

DB_PATH = Path(
    os.environ.get("ORDERPLAN_DB")
    or Path(__file__).resolve().parent.parent / "data" / "orderplan.db"
)
