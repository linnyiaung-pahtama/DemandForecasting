"""Point the app at a throwaway database before any `app` module is imported, so the test suite can
never open or modify the planner's real database (backend/data/orderplan.db)."""
import os
import tempfile
from pathlib import Path

_TEST_DB_DIR = tempfile.mkdtemp(prefix="orderplan-tests-")
os.environ["ORDERPLAN_DB"] = str(Path(_TEST_DB_DIR) / "orderplan-test.db")
