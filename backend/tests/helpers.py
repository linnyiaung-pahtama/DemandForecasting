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


def make_workbook(rows: list[list], headers: list[str] | None = None, sheet: str = "Data",
                  labels: dict[int, str] | None = None) -> bytes:
    """Build an xlsx in memory: row 1 empty (or group labels: 1-based column -> text), row 2 totals (blank),
    row 3 headers, data from row 4."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for c, text in (labels or {}).items():
        ws.cell(row=1, column=c, value=text)
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


SIT_HEADERS = ["SAP Code", "By Principal", "Description", "Oct W3 Arrival", "Oct W4 Arrival", "Oct W5 Arrival",
               "Nov W1 Arrival", "Nov W2 Arrival"]


def make_sit_workbook(rows: list[list], headers: list[str] = SIT_HEADERS, sheet: str = "SIT by weekly",
                      above: list[list] | None = None, hidden_cols: tuple[str, ...] = ()) -> bytes:
    """Build a Stock in Transit xlsx: the `above` rows first, then the header row, then the data rows."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    above = above or []
    for r, row in enumerate(above, start=1):
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=v)
    header_row = len(above) + 1
    for c, h in enumerate(headers, start=1):
        ws.cell(row=header_row, column=c, value=h)
    for r, row in enumerate(rows, start=header_row + 1):
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=v)
    for col in hidden_cols:
        ws.column_dimensions[col].hidden = True
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def sit_from_data(data: bytes, label: str = "Oct W3 Arrival") -> bytes:
    """A Stock in Transit workbook holding every SKU of a Data workbook with its old Data-sheet SIT value, all in one
    arrival column (Oct W3 = 12 Oct 2026, the fixture's plan date, so plans match those made from the Data sheet)."""
    from openpyxl import load_workbook
    ws = load_workbook(BytesIO(data), read_only=True, data_only=True)["Data"]
    rows = list(ws.iter_rows(values_only=True))
    norm = lambda v: " ".join(str(v).split()).casefold() if v is not None else ""
    h = next(i for i, r in enumerate(rows[:10]) if any(norm(c) == "sap code" for c in r))
    cols = {norm(c): i for i, c in enumerate(rows[h])}
    c_sap, c_sit = cols["sap code"], cols.get("sit ctns (pending order)")
    out = []
    for r in rows[h + 1:]:
        if r[c_sap] is None or str(r[c_sap]).strip() == "":
            continue
        sit = r[c_sit] if c_sit is not None and c_sit < len(r) else None
        out.append([r[c_sap], None, None, sit if isinstance(sit, (int, float)) and sit > 0 else None])
    return make_sit_workbook(out, headers=["SAP Code", "By Principal", "Description", label])


CITY_MONTHS = ["Oct'26", "Nov'26", "Dec'26"]


def city_headers(base: list[str] | None = None) -> tuple[list[str], dict[int, str]]:
    """Data headers with Yangon and Mandalay forecast groups (Oct-Dec 2026) appended, plus the label row for them."""
    headers = list(base if base is not None else DEFAULT_HEADERS)
    labels = {len(headers) + 1: "YGN IMS", len(headers) + 1 + len(CITY_MONTHS): "MDY IMS"}
    return headers + CITY_MONTHS + CITY_MONTHS, labels


def with_city_forecast(data: bytes, mdy_share: float = 0.0) -> bytes:
    """A copy of a Sales Forecast workbook whose Data sheet also has YGN IMS / MDY IMS groups for every forecast
    month: Mandalay gets `mdy_share` of each SKU's combined forecast and Yangon the rest."""
    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(data), data_only=True)   # cached values: the fixture's SAP Code header is a formula
    ws = wb["Data"]
    norm = lambda v: " ".join(str(v).split()).casefold() if v is not None else ""
    header_row = next(r for r in range(1, 11) if any(norm(c.value) == "sap code" for c in ws[r]))
    fc = [(c.column, str(c.value).split()) for c in ws[header_row] if norm(c.value).endswith(" ims")]
    start = ws.max_column + 1
    for g, (label, share) in enumerate((("YGN IMS", 1 - mdy_share), ("MDY IMS", mdy_share))):
        first = start + g * len(fc)
        ws.cell(row=1, column=first, value=label)
        for k, (col, (year, mon, _)) in enumerate(fc):
            ws.cell(row=header_row, column=first + k, value=f"{mon[:3]}'{year[2:]}")
            for r in range(header_row + 1, ws.max_row + 1):
                v = ws.cell(row=r, column=col).value
                ws.cell(row=r, column=first + k, value=v * share if isinstance(v, (int, float)) else v)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def holding_settings(holdings: dict, moq: float = 0, lead: int | None = None, cycle: int = 4) -> dict:
    """Supplier settings for tests that only care about holding: {supplier: months} -> SupplierSettings, with the
    holding stored in days (months x 30, so the numbers match the months-based examples)."""
    from app.models import SupplierSettings
    return {s: SupplierSettings(supplier=s, holding_days=None if h is None else h * 30, moq=moq, lead_time_days=lead,
                                order_cycle_weeks=cycle)
            for s, h in holdings.items()}
