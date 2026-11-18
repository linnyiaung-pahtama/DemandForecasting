from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.export import build_export
from app.holding import plan_all
from app.main import create_app
from app.models import ParseWarning, RunRecord, StockFileSummary, StockResult
from app.parsing import parse_input
from app.sales import actual_cartons, parse_sales
from app.stock import apply_stock, parse_pdg, parse_pg
from tests.helpers import (holding_settings, make_pdg_workbook, make_pg_workbook, make_sales_workbook,
                           make_workbook, sit_from_data, with_city_forecast)

FIX = Path(__file__).parent / "fixtures"
DATA, SALES = (FIX / "sample_input.xlsx").read_bytes(), (FIX / "sales_export.xlsx").read_bytes()


def make_run(data: bytes, sales: bytes, holdings: dict[str, float], warnings=None,
             pg: bytes | None = None, pdg: bytes | None = None, lead: int | None = None, cycle: int = 4) -> RunRecord:
    """pg/pdg are the stock report workbooks; they default to the Data workbook itself (the fixture holds all three)."""
    parsed, _ = apply_stock(parse_input(data), parse_pg(pg or data), parse_pdg(pdg or data))
    actual = actual_cartons(parse_sales(sales), parsed)
    if warnings is not None:
        parsed.warnings = warnings[0]
        actual.warnings = warnings[1]
    result = plan_all(parsed, actual, holding_settings(holdings, lead=lead, cycle=cycle), date(2026, 10, 12))
    return RunRecord(id=1, created_at=datetime(2026, 10, 12), file_name="d.xlsx", sales_file_name="s.xlsx",
                     plan_date=result.plan_date, sku_count=len(result.skus),
                     parsed=parsed, actual=actual, result=result)


def load(content: bytes) -> openpyxl.Workbook:
    return openpyxl.load_workbook(BytesIO(content))


def test_export_v2_sheets_and_values(db):
    c = TestClient(create_app(**db))
    item = {"supplier": "CFC", "holding_days": 90, "moq": 0, "lead_time_days": 7, "order_cycle_weeks": 4}
    assert c.put("/api/settings", json=[item]).status_code == 200
    run = c.post("/api/runs", files={"data_file": ("d.xlsx", with_city_forecast(DATA)), "sales_file": ("s.xlsx", SALES),
                                     "pg_file": ("pg.xlsx", DATA), "pdg_file": ("pdg.xlsx", DATA),
                                     "sit_file": ("sit.xlsx", sit_from_data(DATA))}).json()
    r = c.get(f"/api/runs/{run['id']}/export")
    assert r.status_code == 200 and "order-plan-2026-10-12-run" in r.headers["content-disposition"]
    wb = load(r.content)
    assert wb.sheetnames == ["SKU Plan", "12-Month Plan", "Order Plan", "Order Dates", "Commits", "Principal Summary",
                             "Settings Used", "Warnings"]

    ws = wb["SKU Plan"]
    assert ws.max_row == len(run["result"]["skus"]) + 1 > 213   # a row per SKU per city
    header = [cell.value for cell in ws[1]]
    assert header == [
        "Principal", "SAP Code", "Region", "Description", "Status", "Zero Forecast", "Sellable", "PG Sellable", "PDG Sellable",
        "SIT", "Commit", "Available", "PG Non-Sellable", "PDG Non-Sellable",
        "Jul 2026 Actual", "Aug 2026 Actual", "Sep 2026 Actual",
        "Oct 2026 Sales Forecast", "Nov 2026 Sales Forecast", "Dec 2026 Sales Forecast",
        "Valid Values", "Avg Sales", "Holding (days)", "Buffer", "Target", "Required", "MOQ", "MOQ Applied",
        "Order Qty", "Stock Cover (months)", "Lead Time (days)", "Order Cycle (weeks)", "Next Calculation Date"]
    assert ws["A1"].font.bold and ws.freeze_panes == "A2"
    row = next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[1] == "3102111001" and r[2] == "Yangon")
    got = dict(zip(header, row))
    assert got["Order Qty"] == 110 and got["Status"] == "TO_ORDER" and got["Principal"] == "CFC"
    assert got["Holding (days)"] == 90 and got["Zero Forecast"] == "No" and got["MOQ Applied"] in ("Yes", "No")
    assert got["Jul 2026 Actual"] == pytest.approx(52.9) and got["Valid Values"] == 6   # Yangon branches only
    assert got["Next Calculation Date"] == datetime(2026, 10, 19)
    blocked = next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] != "CFC")
    assert dict(zip(header, blocked))["Status"] == "HOLDING_NOT_SET"
    assert dict(zip(header, blocked))["Order Qty"] is None

    summary = wb["Principal Summary"]
    assert [cell.value for cell in summary[1]] == SUMMARY_HEADERS
    assert summary.max_row == 18 and summary["A2"].value == "CFC"
    settings = wb["Settings Used"]
    assert [cell.value for cell in settings[1]] == SETTINGS_USED_HEADERS
    cfc = next(r for r in settings.iter_rows(min_row=2, values_only=True) if r[0] == "CFC")
    assert cfc == ("CFC", 90, 0, 7, 4)
    assert settings.max_row == 18
    warnings = wb["Warnings"]
    assert [cell.value for cell in warnings[1]] == ["Source", "SAP Code", "Column", "Message"]
    # the real Data file carries 2 warnings (the ignored stock columns, the ignored MOQ/Lead Time columns);
    # the sales export none; the stock reports hold codes that are not in the Data sheet (one warning each)
    sources = [r[0] for r in warnings.iter_rows(min_row=2, values_only=True)]
    assert sources == ["Sales Forecast file"] * 2 + ["Stock files"] * 2


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


def test_warnings_sheet_has_sit_and_run_out():
    run = make_run(DATA, SALES, {"CFC": 3})
    summary = StockFileSummary(source="PG", as_of=None, skus_with_stock=1, sellable_cartons=0,
                               non_sellable_cartons=0)
    run.stock = StockResult(pg=summary, pdg=summary.model_copy(update={"source": "PDG"}), skus_with_stock=1,
                            warnings=[], sit_warnings=[ParseWarning(sap_code=None, column=None, message="sit warning")])
    sku = run.result.skus[0]
    sku.runs_out_on, sku.runs_out_arrival = date(2026, 10, 17), date(2026, 10, 19)
    rows = [[c.value for c in r] for r in load(build_export(run))["Warnings"].iter_rows(min_row=2)]
    assert ["Stock in Transit file", None, None, "sit warning"] in rows
    assert ["Stock in Transit file", sku.sap_code, None,
            "runs out about 17 Oct, before its stock in transit arrives on 19 Oct"] in rows
    assert rows[-1][3].startswith("runs out about")   # the flags come after the file warnings


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
    assert ws["A2"].value == "'=Evil" and ws["D2"].value == "'=SUM(A1)"
    assert ws["G2"].data_type == "n" and ws["G2"].value == 100  # numbers stay numbers
    assert wb["Principal Summary"]["A2"].value == "'=Evil"
    assert wb["Settings Used"]["A2"].value == "'=Evil"
    warn = [c.value for c in wb["Warnings"][2]]
    # only a leading "=" is neutralised; "-", "+" and "@" are ordinary text to Excel
    assert warn == ["Sales Forecast file", None, "-col", "'=oops @x"]


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
                 "Oct 2026 Sales Forecast", "Nov 2026 Sales Forecast", "Dec 2026 Sales Forecast", "Avg Sales", "Buffer", "Target"):
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
    assert wb["SKU Plan"]["D2"].value == "BadName"
    rows = [[c.value for c in r] for r in wb["Warnings"].iter_rows(min_row=2)]
    assert rows == [["Sales Forecast file", "F1", "MOQ", "from data"], ["Actual Sales file", None, None, "from sales"]]
    assert wb["Settings Used"]["B2"].value is None  # holding not set -> blank


def test_settings_used_sheet_is_blank_for_old_runs():
    run = make_run(DATA, SALES, {"CFC": 3})
    run.result.settings_used = [s.model_copy(update={"moq": None, "lead_time_days": None, "order_cycle_weeks": None})
                                for s in run.result.settings_used]   # as a run saved before supplier MOQ/lead time
    ws = load(build_export(run))["Settings Used"]
    assert [c.value for c in ws[1]] == SETTINGS_USED_HEADERS
    assert next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] == "CFC") == ("CFC", 90, None, None, None)


MONTH_HEADERS = ["Oct 2026", "Nov 2026", "Dec 2026", "Jan 2027", "Feb 2027", "Mar 2027",
                 "Apr 2027", "May 2027", "Jun 2027", "Jul 2027", "Aug 2027", "Sep 2027"]


SALES_HEADERS = ["Jul 2026 Actual", "Aug 2026 Actual", "Sep 2026 Actual",
                 "Oct 2026 Sales Forecast", "Nov 2026 Sales Forecast", "Dec 2026 Sales Forecast"]
PLAN_SETTINGS_HEADERS = ["Principal", "SAP Code", "Region", "Description", "MOQ", "Holding (days)", "Lead Time (days)",
                         "Order Cycle (weeks)"]
STOCK_HEADERS = ["Avg Sales", "Buffer", "Available", "Target"]
PLAN_STOCK_HEADERS = ["Avg Sales", "Buffer", "Available", "Order-Up-To"]   # the order plan tops up to the order-up-to level
SETTINGS_USED_HEADERS = ["Principal", "Holding (days)", "MOQ", "Lead Time (days)", "Order Cycle (weeks)"]
SUMMARY_HEADERS = [
    "Principal", "Holding (days)", "Order Cycle (weeks)", "SKUs", "SKUs to Order", "Total Order Qty",
    "Order Plan SKUs to Order", "Order Plan Total Order Qty", "Blocked SKUs", "No Demand SKUs", "Zero Forecast SKUs",
    *[f"{m} Order Demand Forecast" for m in MONTH_HEADERS], "12-Month Total",
    *[f"{m} Order Plan" for m in MONTH_HEADERS], "12-Month Order Plan Total"]


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
    assert list(row[:8]) == [sku.supplier, sku.sap_code, None, sku.description, sku.moq, 90, 7, 4]
    assert list(row[8:14]) == [d.value for d in sku.demand_values]
    assert list(row[14:18]) == pytest.approx([sku.avg_sales, sku.buffer, sku.available, sku.target])
    assert list(row[18:30]) == [p.order for p in sku.monthly] and row[30] == sum(p.order for p in sku.monthly)
    assert row[31] == sku.status.value
    assert ws.cell(row=2, column=9).number_format == "0.00"   # sales and stock columns show 2 decimals
    blocked = next(s for s in run.result.skus if s.supplier != "CFC")
    brow = rows[blocked.sap_code]
    assert brow[5] is None and brow[15] is None and brow[17] is None and all(v is None for v in brow[18:31])
    summary = wb["Principal Summary"]
    sheader = [c.value for c in summary[1]]
    assert sheader == SUMMARY_HEADERS
    srows = {r[0]: dict(zip(sheader, r)) for r in summary.iter_rows(min_row=2, values_only=True)}
    blocked_row = srows[blocked.supplier]   # blocked supplier: blank, not 0
    assert all(blocked_row[f"{m} Order Demand Forecast"] is None for m in MONTH_HEADERS)
    assert all(blocked_row[f"{m} Order Plan"] is None for m in MONTH_HEADERS)
    assert blocked_row["12-Month Total"] is None and blocked_row["12-Month Order Plan Total"] is None


def test_order_plan_sheet():
    run = make_run(DATA, SALES, {"CFC": 3}, lead=7, cycle=26)   # orders on 12 Oct and 12 Apr
    wb = load(build_export(run))
    ws = wb["Order Plan"]
    header = [c.value for c in ws[1]]
    assert header == [*PLAN_SETTINGS_HEADERS, *SALES_HEADERS, *PLAN_STOCK_HEADERS,
                      *[f"{m} Order Plan" for m in MONTH_HEADERS], "12-Month Total", "Status"]
    rows = {r[1]: r for r in ws.iter_rows(min_row=2, values_only=True)}
    sku = next(s for s in run.result.skus if s.sap_code == "3102111001")
    row = rows["3102111001"]
    assert sku.plan_order_up_to == pytest.approx(sku.avg_sales * (3 - 1 + 26 * 12 / 52))
    assert row[7] == 26 and list(row[14:18]) == pytest.approx(
        [sku.avg_sales, sku.buffer, sku.available, sku.plan_order_up_to])   # Excel may drop the last binary digit
    assert ws.cell(row=2, column=18).number_format == "0.00"
    assert list(row[18:30]) == [p.order if p.order_month else None for p in sku.order_plan]
    assert [v is not None for v in row[18:30]] == [True] + [False] * 5 + [True] + [False] * 5
    assert row[30] == sum(p.order for p in sku.order_plan) and row[31] == sku.plan_status.value
    blocked = next(s for s in run.result.skus if s.supplier != "CFC")
    assert all(v is None for v in rows[blocked.sap_code][18:31])
    srow = dict(zip([c.value for c in wb["Principal Summary"][1]],
                    next(r for r in wb["Principal Summary"].iter_rows(min_row=2, values_only=True) if r[0] == "CFC")))
    cfc_skus = [s for s in run.result.skus if s.supplier == "CFC"]
    assert srow["Order Cycle (weeks)"] == 26
    assert srow["Order Plan Total Order Qty"] == sum(s.plan_order_qty for s in cfc_skus)
    assert srow["Oct 2026 Order Plan"] == srow["Order Plan Total Order Qty"] and srow["Nov 2026 Order Plan"] is None
    assert srow["12-Month Order Plan Total"] == sum(row[30] for code, row in rows.items()
                                                    if code in {s.sap_code for s in cfc_skus})


def test_export_old_run_has_blank_order_plan():
    run = make_run(DATA, SALES, {"CFC": 3}, cycle=3)
    for s in run.result.skus:   # as a run saved before the order cycle setting
        s.order_plan = s.plan_order_qty = s.plan_status = s.order_cycle_weeks = s.plan_order_up_to = None
    run.result.settings_used = [s.model_copy(update={"order_cycle_weeks": None}) for s in run.result.settings_used]
    wb = load(build_export(run))
    ws = wb["Order Plan"]
    row = next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[1] == "3102111001")
    assert row[7] is None and all(v is None for v in row[17:32])
    srow = dict(zip([c.value for c in wb["Principal Summary"][1]],
                    next(r for r in wb["Principal Summary"].iter_rows(min_row=2, values_only=True) if r[0] == "CFC")))
    assert srow["Order Plan Total Order Qty"] is None and srow["12-Month Order Plan Total"] is None
    assert srow["12-Month Total"] is not None


ORDER_DATES_HEADERS = ["Principal", "SAP Code", "Region", "Description", "Order Date", "Order Qty", "MOQ Applied"]


def test_order_dates_sheet():
    run = make_run(DATA, SALES, {"CFC": 3}, lead=7, cycle=26)   # orders on 12 Oct 2026 and 12 Apr 2027
    wb = load(build_export(run))
    names = wb.sheetnames
    assert names.index("Order Dates") == names.index("Order Plan") + 1
    ws = wb["Order Dates"]
    assert [c.value for c in ws[1]] == ORDER_DATES_HEADERS
    rows = [list(r) for r in ws.iter_rows(min_row=2, values_only=True)]
    cfc = sorted((s for s in run.result.skus if s.supplier == "CFC"), key=lambda s: (s.description, s.sap_code))
    expected = []
    for when, month in ((datetime(2026, 10, 12), 0), (datetime(2027, 4, 12), 6)):
        expected += [["CFC", s.sap_code, None, s.description, when, s.order_plan[month].order,
                      "Yes" if s.order_plan[month].moq_applied else "No"]
                     for s in cfc if s.order_plan[month].order > 0]
    assert rows == expected and len(rows) > 0      # the blocked principal has no orders, so no rows
    assert ws.cell(row=2, column=5).number_format == "yyyy-mm-dd"


def test_order_dates_sheet_empty_for_old_run():
    run = make_run(DATA, SALES, {"CFC": 3})
    for s in run.result.skus:   # as a run saved before the weekly order cycle
        s.order_plan = None
    ws = load(build_export(run))["Order Dates"]
    assert [c.value for c in ws[1]] == ORDER_DATES_HEADERS and ws.max_row == 1


def test_twelve_month_sheet_for_old_runs():
    run = make_run(DATA, SALES, {"CFC": 3})
    for s in run.result.skus:
        s.monthly = None
    run.result.plan_months = []
    wb = load(build_export(run))
    for sheet, stock in (("12-Month Plan", STOCK_HEADERS), ("Order Plan", PLAN_STOCK_HEADERS)):
        assert [c.value for c in wb[sheet][1]] == [*PLAN_SETTINGS_HEADERS, *SALES_HEADERS, *stock,
                                                   "12-Month Total", "Status"]
    assert [c.value for c in wb["Principal Summary"][1]][-2:] == ["12-Month Total", "12-Month Order Plan Total"]