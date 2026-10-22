from io import BytesIO

from openpyxl import Workbook

MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"]

DEFAULT_HEADERS = [
    "SAP Code", "By Principal", "Description", "Packing Size", "MOQ",
    "Shelf Life month", "Lead Time", "Total Sellable (Ctns)",
    "Total Non-Sellable (Ctns)", "SIT Ctns (pending order) ",
    "Oct'26  MTD Sale (1-11 Oct)",
] + [f"{2026 if m in ('Oct', 'Nov', 'Dec') else 2027} {m} IMS" for m in MONTHS]


def make_workbook(rows: list[list], headers: list[str] | None = None, sheet: str = "Data") -> bytes:
    """Build an xlsx in memory: row 1 empty, row 2 totals (blank), row 3 headers, data from row 4."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for c, h in enumerate(headers if headers is not None else DEFAULT_HEADERS, start=1):
        ws.cell(row=3, column=c, value=h)
    for r, row in enumerate(rows, start=4):
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=v)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
