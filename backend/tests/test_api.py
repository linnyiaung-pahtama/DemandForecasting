import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from tests.test_parsing import SAMPLE

@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "t.db"))

def upload(client, path="/api/runs", **form):
    return client.post(path, files={"file": ("sample.xlsx", SAMPLE.read_bytes())}, data=form)

def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}

def test_inspect_reports_counts_and_dates(client):
    r = upload(client, "/api/inspect").json()
    assert r["sku_count"] == 212 and r["supplier_count"] == 17
    assert r["default_plan_date"] == "2026-10-12" and r["min_plan_date"] == "2026-10-12"
    assert r["max_plan_date"] == "2027-09-30"

def test_create_run_then_fetch_and_list(client):
    run = upload(client).json()
    assert len(run["result"]["skus"]) == 212 and len(run["result"]["new_suppliers"]) == 17
    assert client.get(f"/api/runs/{run['id']}").json()["id"] == run["id"]
    assert client.get("/api/runs").json()[0]["id"] == run["id"]
    assert client.get("/api/runs/999").status_code == 404

def test_settings_change_and_recalculate(client):
    run = upload(client).json()
    s = client.get("/api/settings").json()
    assert len(s) == 17 and all(x["is_default"] for x in s)
    honesty = next(x for x in s if x["supplier"] == "Honesty")
    assert honesty["max_lead_time_days"] is not None
    r = client.put("/api/settings", json=[{"supplier": "Honesty", "reorder_days": 45, "target_days": 60}])
    assert r.status_code == 200
    rec = client.post(f"/api/runs/{run['id']}/recalculate").json()
    used = next(x for x in rec["result"]["settings_used"] if x["supplier"] == "Honesty")
    assert used["reorder_days"] == 45 and not used["is_default"]

def test_settings_validation(client):
    r = client.put("/api/settings", json=[{"supplier": "A", "reorder_days": 30, "target_days": 30}])
    assert r.status_code == 422 and "A" in r.text

def test_settings_validation_range(client):
    r = client.put("/api/settings", json=[{"supplier": "B", "reorder_days": 0, "target_days": 30}])
    assert r.status_code == 422 and "B" in r.text
    r = client.put("/api/settings", json=[{"supplier": "C", "reorder_days": 30, "target_days": 366}])
    assert r.status_code == 422 and "C" in r.text

def test_supplier_summary_window(client):
    run = upload(client).json()
    s = client.get(f"/api/runs/{run['id']}/suppliers?window_weeks=4").json()
    assert len(s) == 17
    assert client.get(f"/api/runs/{run['id']}/suppliers?window_weeks=0").status_code == 422
    assert client.get("/api/runs/999/suppliers").status_code == 404

def test_recalculate_unknown_run_returns_404(client):
    assert client.post("/api/runs/999/recalculate").status_code == 404

def test_recalculate_keeps_plan_date(client):
    run = upload(client, plan_date="2026-11-02").json()
    rec = client.post(f"/api/runs/{run['id']}/recalculate").json()
    assert rec["plan_date"] == "2026-11-02" and rec["result"]["plan_date"] == "2026-11-02"
    assert client.get("/api/runs").json()[0]["plan_date"] == "2026-11-02"

def test_upload_wrong_file_returns_400(client):
    r = client.post("/api/runs", files={"file": ("old.xlsb", b"not a workbook")})
    assert r.status_code == 400 and "xlsx" in r.json()["detail"]
    r = client.post("/api/inspect", files={"file": ("old.xlsb", b"not a workbook")})
    assert r.status_code == 400

def test_plan_date_outside_allowed_range_returns_422(client):
    assert upload(client, plan_date="2026-10-05").status_code == 422
    assert upload(client, plan_date="2027-10-01").status_code == 422
    assert upload(client, plan_date="2026-11-02").status_code == 200

def test_invalid_plan_date_text_returns_422(client):
    assert upload(client, plan_date="not-a-date").status_code == 422

def test_cors_allows_dev_origin(client):
    r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
