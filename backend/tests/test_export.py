from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import openpyxl
from fastapi.testclient import TestClient

from app.export import build_export
from app.holding import plan_all
from app.main import create_app
from app.models import ParseWarning, RunRecord
from app.parsing import parse_input
from app.sales import actual_cartons, parse_sales
from tests.helpers import make_sales_workbook, make_workbook

FIX = Path(__file__).parent / "fixtures"
DATA, SALES = (FIX / "sample_input.xlsx").read_bytes(), (FIX / "sales_export.xlsx").read_bytes()


def make_run(data: bytes, sales: bytes, holdings: dict[str, float], warnings=None) -> RunRecord:
    parsed = parse_input(data)
    actual = actual_cartons(parse_sales(sales), parsed)
    if warnings is not None:
        parsed.warnings = warnings[0]
        actual.warnings = warnings[1]
    result = plan_all(parsed, actual, holdings, date(2026, 10, 12))
    return RunRecord(id=1, created_at=datetime(2026, 10, 12), file_name="d.xlsx", sales_file_name="s.xlsx",
                     plan_date=result.plan_date, sku_count=len(result.skus),
                     parsed=parsed, actual=actual, result=result)


def load(content: bytes) -> openpyxl.Workbook:
    return openpyxl.load_workbook(BytesIO(content))


def test_export_v2_sheets_and_values(tmp_path):
    c = TestClient(create_app(tmp_path / "t.db"))
    assert c.put("/api/settings", json=[{"supplier": "CFC", "holding_months": 3}]).status_code == 200
    run = c.post("/api/runs", files={"data_file": ("d.xlsx", DATA), "sales_file": ("s.xlsx", SALES)}).json()
    r = c.get(f"/api/runs/{run['id']}/export")
    assert r.status_code == 200 and "order-plan-2026-10-12-run" in r.headers["content-disposition"]
    wb = load(r.content)
    assert wb.sheetnames == ["SKU Plan", "Supplier Summary", "Settings Used", "Warnings"]

    ws = wb["SKU Plan"]
    assert ws.max_row == 213
    header = [cell.value for cell in ws[1]]
    assert header == [
        "Supplier", "SAP Code", "Description", "Status", "Zero Forecast", "Sellable", "SIT", "Available",
        "Jul 2026 Actual", "Aug 2026 Actual", "Sep 2026 Actual",
        "Oct 2026 Forecast", "Nov 2026 Forecast", "Dec 2026 Forecast",
        "Valid Values", "Buffer", "Holding (months)", "Target", "Required", "MOQ", "MOQ Applied",
        "Order Qty", "Stock Cover (months)", "Lead Time (days)", "Next Calculation Date"]
    assert ws["A1"].font.bold and ws.freeze_panes == "A2"
    row = next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[1] == "3102111001")
    got = dict(zip(header, row))
    assert got["Order Qty"] == 110 and got["Status"] == "TO_ORDER" and got["Supplier"] == "CFC"
    assert got["Holding (months)"] == 3 and got["Zero Forecast"] == "No" and got["MOQ Applied"] in ("Yes", "No")
    assert abs(got["Jul 2026 Actual"] - 2113 / 40) < 1e-9 and got["Valid Values"] == 6
    assert got["Next Calculation Date"] == datetime(2026, 10, 19)
    blocked = next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[0] != "CFC")
    assert dict(zip(header, blocked))["Status"] == "HOLDING_NOT_SET"
    assert dict(zip(header, blocked))["Order Qty"] is None

    summary = wb["Supplier Summary"]
    assert [cell.value for cell in summary[1]] == [
        "Supplier", "Holding (months)", "SKUs", "SKUs to Order", "Total Order Qty", "Blocked SKUs",
        "No Demand SKUs", "Zero Forecast SKUs"]
    assert summary.max_row == 18 and summary["A2"].value == "CFC"
    settings = wb["Settings Used"]
    assert [cell.value for cell in settings[1]] == ["Supplier", "Holding (months)"]
    assert settings.max_row == 18
    warnings = wb["Warnings"]
    assert [cell.value for cell in warnings[1]] == ["Source", "SAP Code", "Column", "Message"]
    # the real Data file carries 13 parse warnings (10 negative MTD, 3 zero shelf life); the sales export none
    sources = [r[0] for r in warnings.iter_rows(min_row=2, values_only=True)]
    assert sources == ["Data file"] * 13


def test_export_neutralises_formula_text():
    # make_workbook would store these strings as real formulas, so plant them on the run itself
    data = make_workbook([["F1", "Sup", "Noodles", 10, 0, 6, 7, 100, 0, 0, 5] + [50] * 12])
    sales = make_sales_workbook(
        [["PG", "Yangon", "P", "B", "F1", "x", 2026, m, 40, 0] for m in ("Jul", "Aug", "Sep")])
    run = make_run(data, sales, {"Sup": 3},
                   warnings=([ParseWarning(sap_code=None, column="-col", message="+oops @x")], []))
    run.result.skus[0].description = "=SUM(A1)"
    run.result.skus[0].supplier = "=Evil"
    run.result.settings_used[0].supplier = "=Evil"
    wb = load(build_export(run))
    ws = wb["SKU Plan"]
    assert ws["A2"].value == "'=Evil" and ws["C2"].value == "'=SUM(A1)"
    assert ws["F2"].data_type == "n" and ws["F2"].value == 100  # numbers stay numbers
    assert wb["Supplier Summary"]["A2"].value == "'=Evil"
    assert wb["Settings Used"]["A2"].value == "'=Evil"
    warn = [c.value for c in wb["Warnings"][2]]
    assert warn == ["Data file", None, "'-col", "'+oops @x"]


def test_export_strips_illegal_characters_and_labels_warning_sources():
    data = make_workbook([["F1", "Sup", "Name", 10, 0, 6, 7, 100, 0, 0, 5] + [50] * 12])
    sales = make_sales_workbook(
        [["PG", "Yangon", "P", "B", "F1", "x", 2026, m, 40, 0] for m in ("Jul", "Aug", "Sep")])
    run = make_run(data, sales, {}, warnings=(
        [ParseWarning(sap_code="F1", column="MOQ", message="from data")],
        [ParseWarning(sap_code=None, column=None, message="from sales")]))
    run.result.skus[0].description = "Bad\x07Name"  # openpyxl cannot write control characters
    wb = load(build_export(run))
    assert wb["SKU Plan"]["C2"].value == "BadName"
    rows = [[c.value for c in r] for r in wb["Warnings"].iter_rows(min_row=2)]
    assert rows == [["Data file", "F1", "MOQ", "from data"], ["Sales export", None, None, "from sales"]]
    assert wb["Settings Used"]["B2"].value is None  # holding not set -> blank
