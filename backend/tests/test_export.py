from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import openpyxl
from fastapi.testclient import TestClient

from app.export import build_export
from app.holding import plan_all
from app.main import create_app
from app.models import ParseWarning, RunRecord, StockFileSummary, StockResult
from app.parsing import parse_input
from app.sales import actual_cartons, parse_sales
from app.stock import apply_stock, parse_pdg, parse_pg
from tests.helpers import (holding_settings, make_pdg_workbook, make_pg_workbook, make_sales_workbook,
                           make_workbook)

FIX = Path(__file__).parent / "fixtures"
DATA, SALES = (FIX / "sample_input.xlsx").read_bytes(), (FIX / "sales_export.xlsx").read_bytes()


def make_run(data: bytes, sales: bytes, holdings: dict[str, float], warnings=None,
             pg: bytes | None = None, pdg: bytes | None = None, lead: int | None = None) -> RunRecord:
    """pg/pdg are the stock report workbooks; they default to the Data workbook itself (the fixture holds all three)."""
    parsed, _ = apply_stock(parse_input(data), parse_pg(pg or data), parse_pdg(pdg or data))
    actual = actual_cartons(parse_sales(sales), parsed)
    if warnings is not None:
        parsed.warnings = warnings[0]
        actual.warnings = warnings[1]
    result = plan_all(parsed, actual, holding_settings(holdings, lead=lead), date(2026, 10, 12))
    return RunRecord(id=1, created_at=datetime(2026, 10, 12), file_name="d.xlsx", sales_file_name="s.xlsx",
                     plan_date=result.plan_date, sku_count=len(result.skus),
                     parsed=parsed, actual=actual, result=result)


def load(content: bytes) -> openpyxl.Workbook:
    return openpyxl.load_workbook(BytesIO(content))


def test_export_v2_sheets_and_values(tmp_path):
    c = TestClient(create_app(tmp_path / "t.db"))
    item = {"supplier": "CFC", "holding_months": 3, "moq": 0, "lead_time_days": 7, "order_cycle_months": 1}
    assert c.put("/api/settings", json=[item]).status_code == 200
    run = c.post("/api/runs", files={"data_file": ("d.xlsx", DATA), "sales_file": ("s.xlsx", SALES),
                                     "pg_file": ("pg.xlsx", DATA), "pdg_file": ("pdg.xlsx", DATA)}).json()
    r = c.get(f"/api/runs/{run['id']}/export")
    assert r.status_code == 200 and "order-plan-2026-10-12-run" in r.headers["content-disposition"]
    wb = load(r.content)
    assert wb.sheetnames == ["SKU Plan", "12-Month Plan", "Principal Summary", "Settings Used", "Warnings"]

    ws = wb["SKU Plan"]
    assert ws.max_row == 213
    header = [cell.value for cell in ws[1]]
    assert header == [
        "Principal", "SAP Code", "Description", "Status", "Zero Forecast", "Sellable", "PG Sellable", "PDG Sellable",
        "SIT", "Available", "PG Non-Sellable", "PDG Non-Sellable",
        "Jul 2026 Actual", "Aug 2026 Actual", "Sep 2026 Actual",
        "Oct 2026 Sales Forecast", "Nov 2026 Sales Forecast", "Dec 2026 Sales Forecast",
        "Valid Values", "Buffer", "Holding (months)", "Target", "Required", "MOQ", "MOQ Applied",
        "Order Qty", "Stock Cover (months)", "Lead Time (days)", "Next Calculation Date"]
    assert ws["A1"].font.bold and ws.freeze_panes == "A2"
    row = next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[1] == "3102111001")
    got = dict(zip(header, row))
    assert got["Order Qty"] == 110 and got["Status"] == "TO_ORDER" and got["Principal"] == "CFC"
    assert got["Holding (months)"] == 3 and got["Zero Forecast"] == "No" and got["MOQ Applied"] in ("Yes", "No")
    assert abs(got["Jul 2026 Actual"] - 2113 / 40) < 1e-9 and got["Valid Values"] == 6
    assert got["Next Calculation Date"] == datetime(2026, 10, 19)
    blocked = next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] != "CFC")
    assert dict(zip(header, blocked))["Status"] == "HOLDING_NOT_SET"
    assert dict(zip(header, blocked))["Order Qty"] is None

    summary = wb["Principal Summary"]
    assert [cell.value for cell in summary[1]] == [
        "Principal", "Holding (months)", "SKUs", "SKUs to Order", "Total Order Qty", "Blocked SKUs",
        "No Demand SKUs", "Zero Forecast SKUs", *MONTH_HEADERS, "12-Month Total"]
    assert summary.max_row == 18 and summary["A2"].value == "CFC"
    settings = wb["Settings Used"]
    assert [cell.value for cell in settings[1]] == ["Principal", "Holding (months)", "MOQ", "Lead Time (days)"]
    cfc = next(r for r in settings.iter_rows(min_row=2, values_only=True) if r[0] == "CFC")
    assert cfc == ("CFC", 3, 0, 7)
    assert settings.max_row == 18
    warnings = wb["Warnings"]
    assert [cell.value for cell in warnings[1]] == ["Source", "SAP Code", "Column", "Message"]
    # the real Data file carries 15 warnings (the ignored stock columns, the ignored MOQ/Lead Time columns,
    # 10 negative MTD, 3 zero shelf life); the sales export none; the stock reports hold codes that are not
    # in the Data sheet (one warning each)
    sources = [r[0] for r in warnings.iter_rows(min_row=2, values_only=True)]
    assert sources == ["Data file"] * 15 + ["Stock files"] * 2


def test_export_stock_columns_and_warnings():
    run = make_run(DATA, SALES, {"CFC": 3})
    sku = run.result.skus[0]
    sku.pg_sellable, sku.pdg_sellable, sku.pg_non_sellable, sku.pdg_non_sellable = 12.5, 3, 1, None
    summary = StockFileSummary(source="PG", as_of=None, skus_with_stock=1, sellable_cartons=0,
                               non_sellable_cartons=0)
    run.stock = StockResult(pg=summary, pdg=summary.model_copy(update={"source": "PDG"}), skus_with_stock=1,
                            warnings=[ParseWarning(sap_code="X1", column=None, message="stock warning")])
    wb = load(build_export(run))
    ws = wb["SKU Plan"]
    header = [c.value for c in ws[1]]
    cells = dict(zip(header, ws[2]))
    assert cells["PG Sellable"].value == 12.5 and cells["PG Sellable"].number_format == "0.00"
    assert cells["PDG Sellable"].value == 3 and cells["PG Non-Sellable"].value == 1
    assert cells["PDG Non-Sellable"].value is None and cells["PDG Non-Sellable"].number_format == "0.00"
    rows = [[c.value for c in r] for r in wb["Warnings"].iter_rows(min_row=2)]
    assert rows[-1] == ["Stock files", "X1", None, "stock warning"]

    plain = make_run(DATA, SALES, {"CFC": 3})
    for s in plain.result.skus:
        s.pg_sellable = s.pdg_sellable = s.pg_non_sellable = s.pdg_non_sellable = None
    plain.stock = None
    wb2 = load(build_export(plain))
    row = dict(zip(header, wb2["SKU Plan"][2]))
    assert all(row[h].value is None for h in ("PG Sellable", "PDG Sellable", "PG Non-Sellable", "PDG Non-Sellable"))
    assert "Stock files" not in [r[0] for r in wb2["Warnings"].iter_rows(min_row=2, values_only=True)]


def test_export_neutralises_formula_text():
    # make_workbook would store these strings as real formulas, so plant them on the run itself
    data = make_workbook([["F1", "Sup", "Noodles", 10, 0, 6, 7, 100, 0, 0, 5] + [50] * 12])
    sales = make_sales_workbook(
        [["PG", "Yangon", "P", "B", "F1", "x", 2026, m, 40, 0] for m in ("Jul", "Aug", "Sep")])
    run = make_run(data, sales, {"Sup": 3},
                   warnings=([ParseWarning(sap_code=None, column="-col", message="=oops @x")], []),
                   pg=make_pg_workbook([["F1", "W", "Sellable", 100, 1, 100, None, None]]),
                   pdg=make_pdg_workbook([["Z", "x", "L", None, 1, 1, None]]))
    run.result.skus[0].description = "=SUM(A1)"
    run.result.skus[0].supplier = "=Evil"
    run.result.settings_used[0].supplier = "=Evil"
    wb = load(build_export(run))
    ws = wb["SKU Plan"]
    assert ws["A2"].value == "'=Evil" and ws["C2"].value == "'=SUM(A1)"
    assert ws["F2"].data_type == "n" and ws["F2"].value == 100  # numbers stay numbers
    assert wb["Principal Summary"]["A2"].value == "'=Evil"
    assert wb["Settings Used"]["A2"].value == "'=Evil"
    warn = [c.value for c in wb["Warnings"][2]]
    # only a leading "=" is neutralised; "-", "+" and "@" are ordinary text to Excel
    assert warn == ["Data file", None, "-col", "'=oops @x"]


def test_export_leaves_plus_minus_at_text_alone():
    from app.export import _safe
    assert [_safe(v) for v in ("-5 pcs", "+Tea", "@home", "=1+1", "a=b", None, 3)] == [
        "-5 pcs", "+Tea", "@home", "'=1+1", "a=b", None, 3]


def test_export_number_formats():
    run = make_run(DATA, SALES, {"CFC": 3}, lead=7)   # CFC's lead time, so the date column is filled
    ws = load(build_export(run))["SKU Plan"]
    header = [c.value for c in ws[1]]
    row = next(r for r in ws.iter_rows(min_row=2) if r[1].value == "3102111001")
    fmt = {h: c.number_format for h, c in zip(header, row)}
    for name in ("Sellable", "SIT", "Available", "Jul 2026 Actual", "Aug 2026 Actual", "Sep 2026 Actual",
                 "Oct 2026 Sales Forecast", "Nov 2026 Sales Forecast", "Dec 2026 Sales Forecast", "Buffer", "Target"):
        assert fmt[name] == "0.00", name
    assert fmt["Stock Cover (months)"] == "0.0"
    assert fmt["Next Calculation Date"] == "yyyy-mm-dd"
    assert fmt["Order Qty"] == "General" and fmt["Valid Values"] == "General"


def test_export_strips_illegal_characters_and_labels_warning_sources():
    data = make_workbook([["F1", "Sup", "Name", 10, 0, 6, 7, 100, 0, 0, 5] + [50] * 12])
    sales = make_sales_workbook(
        [["PG", "Yangon", "P", "B", "F1", "x", 2026, m, 40, 0] for m in ("Jul", "Aug", "Sep")])
    run = make_run(data, sales, {}, warnings=(
        [ParseWarning(sap_code="F1", column="MOQ", message="from data")],
        [ParseWarning(sap_code=None, column=None, message="from sales")]),
        pg=make_pg_workbook([["F1", "W", "Sellable", 100, 1, 100, None, None]]),
        pdg=make_pdg_workbook([["F1", "x", "L", None, 1, 1, None]]))
    run.result.skus[0].description = "Bad\x07Name"  # openpyxl cannot write control characters
    wb = load(build_export(run))
    assert wb["SKU Plan"]["C2"].value == "BadName"
    rows = [[c.value for c in r] for r in wb["Warnings"].iter_rows(min_row=2)]
    assert rows == [["Data file", "F1", "MOQ", "from data"], ["Sales export", None, None, "from sales"]]
    assert wb["Settings Used"]["B2"].value is None  # holding not set -> blank


def test_settings_used_sheet_is_blank_for_old_runs():
    run = make_run(DATA, SALES, {"CFC": 3})
    run.result.settings_used = [s.model_copy(update={"moq": None, "lead_time_days": None})
                                for s in run.result.settings_used]   # as a run saved before supplier MOQ/lead time
    ws = load(build_export(run))["Settings Used"]
    assert [c.value for c in ws[1]] == ["Principal", "Holding (months)", "MOQ", "Lead Time (days)"]
    assert next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] == "CFC") == ("CFC", 3, None, None)


MONTH_HEADERS = ["Oct 2026", "Nov 2026", "Dec 2026", "Jan 2027", "Feb 2027", "Mar 2027",
                 "Apr 2027", "May 2027", "Jun 2027", "Jul 2027", "Aug 2027", "Sep 2027"]


SALES_HEADERS = ["Jul 2026 Actual", "Aug 2026 Actual", "Sep 2026 Actual",
                 "Oct 2026 Sales Forecast", "Nov 2026 Sales Forecast", "Dec 2026 Sales Forecast"]
PLAN_SETTINGS_HEADERS = ["Principal", "SAP Code", "Description", "MOQ", "Holding (months)", "Lead Time (days)"]
STOCK_HEADERS = ["Buffer", "Available", "Target"]


def test_twelve_month_sheet():
    run = make_run(DATA, SALES, {"CFC": 3}, lead=7)
    wb = load(build_export(run))
    ws = wb["12-Month Plan"]
    header = [c.value for c in ws[1]]
    assert header == [*PLAN_SETTINGS_HEADERS, *SALES_HEADERS, *STOCK_HEADERS,
                      *[f"{m} Order Demand Forecast" for m in MONTH_HEADERS], "12-Month Total", "Status"]
    rows = {r[1]: r for r in ws.iter_rows(min_row=2, values_only=True)}
    sku = next(s for s in run.result.skus if s.sap_code == "3102111001")
    row = rows["3102111001"]
    assert list(row[:6]) == [sku.supplier, sku.sap_code, sku.description, sku.moq, 3, 7]
    assert list(row[6:12]) == [d.value for d in sku.demand_values]
    assert list(row[12:15]) == [sku.buffer, sku.available, sku.target]
    assert list(row[15:27]) == [p.order for p in sku.monthly] and row[27] == sum(p.order for p in sku.monthly)
    assert row[28] == sku.status.value
    assert ws.cell(row=2, column=7).number_format == "0.00"   # sales and stock columns show 2 decimals
    blocked = next(s for s in run.result.skus if s.supplier != "CFC")
    brow = rows[blocked.sap_code]
    assert brow[4] is None and brow[14] is None and all(v is None for v in brow[15:28])
    summary = wb["Principal Summary"]
    sheader = [c.value for c in summary[1]]
    assert sheader[-13:] == [*MONTH_HEADERS, "12-Month Total"]
    srows = {r[0]: r for r in summary.iter_rows(min_row=2, values_only=True)}
    assert all(v is None for v in srows[blocked.supplier][-13:])   # blocked supplier: blank, not 0


def test_twelve_month_sheet_for_old_runs():
    run = make_run(DATA, SALES, {"CFC": 3})
    for s in run.result.skus:
        s.monthly = None
    run.result.plan_months = []
    wb = load(build_export(run))
    assert [c.value for c in wb["12-Month Plan"][1]] == [*PLAN_SETTINGS_HEADERS, *SALES_HEADERS, *STOCK_HEADERS,
                                                          "12-Month Total", "Status"]
    assert [c.value for c in wb["Principal Summary"][1]][-1] == "12-Month Total"