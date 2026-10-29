from datetime import datetime
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


SALES_HEADERS = ["Company", "BranchName", "Principal", "Brand", "itemCode", "Itemname", "Year", "Month", "Qty", "Amount"]


def make_sales_workbook(rows: list[list], headers: list[str] | None = None, sheet: str = "Sheet1") -> bytes:
    """Build a sales-export xlsx in memory: headers on row 1, data from row 2."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for c, h in enumerate(headers if headers is not None else SALES_HEADERS, start=1):
        ws.cell(row=1, column=c, value=h)
    for r, row in enumerate(rows, start=2):
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=v)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


PG_HEADERS = ["Item Code", "Whs Code", "Location", "SOH", "UOM", "Ctn", "expired Date", "Day Left"]
PDG_HEADERS = ["StockCode", "Description", "Location", "Sell or Non", "U_Ratio", "Bin_Qty", "cs"]


def make_pg_workbook(rows: list[list], headers: list[str] = PG_HEADERS, hidden_rows: tuple[int, ...] = ()) -> bytes:
    """Build a PG Expiry Check xlsx: row 1 totals, row 2 headers, data from row 3; hidden_rows are sheet row numbers."""
    wb = Workbook()
    ws = wb.active
    ws.title = "PG Expiry Check"
    if "Ctn" in headers:
        ws.cell(row=1, column=headers.index("Ctn") + 1, value=999)
    for c, h in enumerate(headers, start=1):
        ws.cell(row=2, column=c, value=h)
    for r, row in enumerate(rows, start=3):
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=v)
    for r in hidden_rows:
        ws.row_dimensions[r].hidden = True
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_pdg_workbook(rows: list[list], headers: list[str] = PDG_HEADERS,
                      printed: datetime | None = datetime(2026, 10, 12, 6, 45)) -> bytes:
    """Build a PDG Stock List xlsx: Printed_Date block on rows 1-2, headers on row 4, data from row 5."""
    wb = Workbook()
    ws = wb.active
    ws.title = "PDG Stock List"
    ws.cell(row=1, column=1, value="Printed_Date")
    ws.cell(row=1, column=2, value="Item_Code")
    ws.cell(row=2, column=1, value=printed)
    ws.cell(row=2, column=2, value="ALL To ALL")
    for c, h in enumerate(headers, start=1):
        ws.cell(row=4, column=c, value=h)
    for r, row in enumerate(rows, start=5):
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=v)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def holding_settings(holdings: dict, moq: float = 0, lead: int | None = None, cycle: int = 1) -> dict:
    """Supplier settings for tests that only care about holding: {supplier: months} -> SupplierSettings."""
    from app.models import SupplierSettings
    return {s: SupplierSettings(supplier=s, holding_months=h, moq=moq, lead_time_days=lead, order_cycle_months=cycle)
            for s, h in holdings.items()}
