from io import BytesIO

import openpyxl
from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_parsing import SAMPLE


def test_export_has_expected_sheets_and_rows(tmp_path):
    c = TestClient(create_app(tmp_path / "t.db"))
    run = c.post("/api/runs", files={"file": ("s.xlsx", SAMPLE.read_bytes())}).json()
    r = c.get(f"/api/runs/{run['id']}/export")
    assert r.status_code == 200 and "order-plan-2026-10-12" in r.headers["content-disposition"]
    wb = openpyxl.load_workbook(BytesIO(r.content))
    assert wb.sheetnames == ["SKU Plan", "Orders", "Supplier Summary", "Settings Used", "Warnings"]
    assert wb["SKU Plan"].max_row == 213
    assert wb["SKU Plan"]["A1"].value == "Supplier"
    n_orders = sum(len(s["orders"]) for s in run["result"]["skus"])
    assert wb["Orders"].max_row == n_orders + 1
