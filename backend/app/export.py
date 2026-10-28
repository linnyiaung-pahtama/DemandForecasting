"""Excel export of a run's order plan. Temporary stub: rewritten in Task 5."""
from app.models import RunRecord

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_export(run: RunRecord) -> bytes:
    raise NotImplementedError("Export is rewritten in Task 5.")
