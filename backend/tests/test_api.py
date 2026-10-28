import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from app.main import create_app

FIX = Path(__file__).parent / "fixtures"
DATA, SALES = (FIX / "sample_input.xlsx").read_bytes(), (FIX / "sales_export.xlsx").read_bytes()


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "t.db"))


def files(data=DATA, sales=SALES):
    return {"data_file": ("data.xlsx", data), "sales_file": ("sales.xlsx", sales)}


def test_inspect_reports_months_and_coverage(client):
    r = client.post("/api/inspect", files=files()).json()
    assert r["actual_months"] == ["2026-07", "2026-08", "2026-09"]
    assert r["forecast_window"] == ["2026-10", "2026-11", "2026-12"]
    assert r["sku_count"] == 212 and r["skus_with_sales"] == 141 and r["sales_file_name"] == "sales.xlsx"


def test_new_run_blocks_all_suppliers_until_holding_set(client):
    run = client.post("/api/runs", files=files()).json()
    assert run["result"]["counts"]["HOLDING_NOT_SET"] == 212
    assert len(run["result"]["blocked_suppliers"]) == 17
    s = client.get("/api/settings").json()
    assert len(s) == 17 and all(x["holding_months"] is None for x in s)


def test_set_holding_recalculates_real_sku(client):
    run = client.post("/api/runs", files=files()).json()
    assert client.put("/api/settings", json=[{"supplier": "CFC", "holding_months": 3}]).status_code == 200
    rec = client.post(f"/api/runs/{run['id']}/recalculate").json()
    sku = next(x for x in rec["result"]["skus"] if x["sap_code"] == "3102111001")
    # actuals 2113/40, 1451/40, 1647/40; forecast 55, 55, 55 -> buffer 49.2125
    assert sku["buffer"] == pytest.approx(49.2125)
    assert sku["target"] == pytest.approx(147.6375) and sku["available"] == pytest.approx(38.15)
    assert sku["order_qty"] == 110 and sku["status"] == "TO_ORDER"
    assert sku["next_calc_date"] == "2026-10-19"
    log = client.get("/api/settings/log").json()
    assert log[0]["supplier"] == "CFC" and log[0]["old_value"] is None and log[0]["new_value"] == 3


def test_holding_validation(client):
    for bad in (0, 25, "abc"):
        assert client.put("/api/settings", json=[{"supplier": "A", "holding_months": bad}]).status_code == 422
    assert client.put("/api/settings", json=[{"supplier": "A", "holding_months": None}]).status_code == 200


def test_swapped_files_return_400(client):
    r = client.post("/api/inspect", files=files(data=SALES, sales=DATA))
    assert r.status_code == 400 and r.json()["detail"].startswith("Data file:")
    r = client.post("/api/runs", files=files(sales=DATA))
    assert r.status_code == 400 and r.json()["detail"].startswith("Sales export:")


def test_plan_date_range_and_404s(client):
    assert client.post("/api/runs", files=files(), data={"plan_date": "2026-11-02"}).status_code == 422
    assert client.get("/api/runs/999").status_code == 404
    assert client.post("/api/runs/999/recalculate").status_code == 404
