import json
from datetime import date
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.commits import apply_commits, remove_commits
from app.main import create_app
from app.models import CityInput, Commit, ParsedInput, SitArrival, SkuInput
from tests.helpers import sit_from_data, with_city_forecast

FIX = Path(__file__).parent / "fixtures"
DATA = (FIX / "sample_input.xlsx").read_bytes()
SALES = (FIX / "sales_export.xlsx").read_bytes()
CITY_DATA = with_city_forecast(DATA)
SIT = sit_from_data(DATA)
PD = date(2026, 10, 12)


def _sku(code: str) -> SkuInput:
    return SkuInput(sap_code=code, supplier="P", description=f"item {code}", packing_size=1, moq=0,
                    shelf_life_months=None, lead_time_days=None, sellable=0, non_sellable=0, sit=5, mtd_sales=0,
                    forecast={}, sit_arrivals=[SitArrival(date=date(2026, 10, 19), cartons=5)],
                    cities={"YGN": CityInput(sit=5, sit_arrivals=[SitArrival(date=date(2026, 10, 19), cartons=5)]),
                            "MDY": CityInput()})


def _parsed(*codes: str) -> ParsedInput:
    return ParsedInput(skus=[_sku(c) for c in codes], forecast_months=["2026-10"], mtd_month="2026-10",
                       mtd_label="x", mtd_end=date(2026, 10, 11), default_plan_date=PD, warnings=[])


def test_commit_lands_in_its_region_like_sit():
    commits = [Commit(sap_code="A", cartons=40, arrival_week=date(2026, 11, 2), region="MDY"),
               Commit(sap_code="A", cartons=10, arrival_week=date(2026, 10, 19), region="YGN")]
    out = apply_commits(_parsed("A", "B"), commits, PD)
    a, b = out.skus
    assert a.sit == 55 and a.cities["MDY"].sit == 40 and a.cities["YGN"].sit == 15
    assert [(x.date, x.cartons, x.source) for x in a.cities["MDY"].sit_arrivals] == [(date(2026, 11, 2), 40, "commit")]
    assert [(x.date, x.cartons, x.source) for x in a.cities["YGN"].sit_arrivals] == [
        (date(2026, 10, 19), 5, "sit"), (date(2026, 10, 19), 10, "commit")]
    assert [(x.date, x.source) for x in a.sit_arrivals] == [
        (date(2026, 10, 19), "sit"), (date(2026, 10, 19), "commit"), (date(2026, 11, 2), "commit")]
    assert b == _sku("B") and out.commits == commits


def test_no_commits_changes_nothing():
    parsed = _parsed("A")
    assert apply_commits(parsed, [], PD) == parsed


@pytest.mark.parametrize("commit, message", [
    (Commit(sap_code="ZZ", cartons=5, arrival_week=date(2026, 10, 19), region="YGN"),
     "Commit 1: SAP code 'ZZ' is not in the Sales Forecast file."),
    (Commit(sap_code="A", cartons=0, arrival_week=date(2026, 10, 19), region="YGN"),
     "Commit 1: cartons must be a number above 0."),
    (Commit(sap_code="A", cartons=5, arrival_week=date(2026, 10, 19), region="NPT"),
     "Commit 1: region must be Yangon or Mandalay."),
    (Commit(sap_code="A", cartons=5, arrival_week=date(2026, 10, 20), region="YGN"),
     "Commit 1: the arrival week must be given by its Monday."),
    (Commit(sap_code="A", cartons=5, arrival_week=date(2026, 10, 5), region="YGN"),
     "Commit 1: the arrival week is before the plan week (12 Oct 2026)."),
])
def test_invalid_commits_are_rejected(commit, message):
    with pytest.raises(ValueError) as e:
        apply_commits(_parsed("A"), [commit], PD)
    assert str(e.value) == message


def test_plan_week_itself_is_allowed_when_the_plan_date_is_mid_week():
    out = apply_commits(_parsed("A"), [Commit(sap_code="A", cartons=5, arrival_week=date(2026, 10, 12), region="YGN")],
                        date(2026, 10, 14))
    assert out.skus[0].cities["YGN"].sit == 10


# ---- through the API -----------------------------------------------------------------------------

def files(data=CITY_DATA):
    return {"data_file": ("data.xlsx", data), "sales_file": ("sales.xlsx", SALES), "pg_file": ("pg.xlsx", DATA),
            "pdg_file": ("pdg.xlsx", DATA), "sit_file": ("sit.xlsx", SIT)}


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "t.db"))


CODE = "3102111001"


def _row(run, region):
    return next(s for s in run["result"]["skus"] if s["sap_code"] == CODE and s["city"] == region)


def test_inspect_lists_the_skus_for_the_commit_picker(client):
    r = client.post("/api/inspect", files=files()).json()
    assert len(r["skus"]) == 212
    assert {"sap_code": CODE, "description": r["skus"][[s["sap_code"] for s in r["skus"]].index(CODE)]["description"],
            "supplier": "CFC"} in r["skus"]


def test_run_with_commits_counts_them_and_keeps_them_on_recalculate(client):
    client.put("/api/settings", json=[{"supplier": "CFC", "holding_days": 90, "moq": 0, "lead_time_days": 7,
                                       "order_cycle_weeks": 4}])
    plain = client.post("/api/runs", files=files(), data={"plan_date": "2026-10-12"}).json()
    commits = [{"sap_code": CODE, "cartons": 50, "arrival_week": "2026-10-26", "region": "YGN"}]
    run = client.post("/api/runs", files=files(), data={"plan_date": "2026-10-12",
                                                        "commits": json.dumps(commits)}).json()
    before, after = _row(plain, "YGN"), _row(run, "YGN")
    assert after["sit"] == before["sit"] + 50 and after["available"] == before["available"] + 50
    assert after["plan_order_qty"] == max(before["plan_order_qty"] - 50, 0)   # not ordered again
    assert {"date": "2026-10-26", "cartons": 50, "source": "commit"} in after["sit_arrivals"]
    assert run["parsed"]["commits"] == commits
    rec = client.post(f"/api/runs/{run['id']}/recalculate").json()
    assert _row(rec, "YGN")["sit"] == after["sit"] and rec["parsed"]["commits"] == commits


def test_invalid_commits_give_422(client):
    bad = [{"sap_code": "NOPE", "cartons": 5, "arrival_week": "2026-10-19", "region": "YGN"}]
    r = client.post("/api/runs", files=files(), data={"commits": json.dumps(bad)})
    assert r.status_code == 422 and r.json()["detail"] == "Commit 1: SAP code 'NOPE' is not in the Sales Forecast file."
    r = client.post("/api/runs", files=files(), data={"commits": "not json"})
    assert r.status_code == 422 and r.json()["detail"].startswith("Commits could not be read")


def test_export_has_a_commits_sheet(client):
    commits = [{"sap_code": CODE, "cartons": 50, "arrival_week": "2026-10-26", "region": "MDY"}]
    run = client.post("/api/runs", files=files(), data={"commits": json.dumps(commits)}).json()
    wb = openpyxl.load_workbook(BytesIO(client.get(f"/api/runs/{run['id']}/export").content))
    ws = wb["Commits"]
    assert [c.value for c in ws[1]] == ["Principal", "SAP Code", "Description", "Region", "Cartons", "Arrival Week"]
    row = [c.value for c in ws[2]]
    assert row[:2] == ["CFC", CODE] and row[3:5] == ["Mandalay", 50] and row[5].date() == date(2026, 10, 26)
    plain = client.post("/api/runs", files=files()).json()
    ws = openpyxl.load_workbook(BytesIO(client.get(f"/api/runs/{plain['id']}/export").content))["Commits"]
    assert ws.max_row == 1   # headers only


def test_sku_plan_keeps_sit_and_commits_apart(client):
    commits = [{"sap_code": CODE, "cartons": 50, "arrival_week": "2026-10-26", "region": "YGN"}]
    run = client.post("/api/runs", files=files(), data={"commits": json.dumps(commits)}).json()
    ws = openpyxl.load_workbook(BytesIO(client.get(f"/api/runs/{run['id']}/export").content))["SKU Plan"]
    header = [c.value for c in ws[1]]
    assert header[header.index("SIT") + 1] == "Commit"
    row = dict(zip(header, next(r for r in ws.iter_rows(min_row=2, values_only=True)
                                if r[1] == CODE and r[2] == "Yangon")))
    sku = _row(run, "YGN")
    assert row["Commit"] == 50 and row["SIT"] == pytest.approx(sku["sit"] - 50)
    assert row["Available"] == pytest.approx(sku["available"])   # still sellable + SIT + commits

# ---- changing a saved plan's commits ------------------------------------------------------------

def test_remove_commits_gives_back_the_input_without_them():
    parsed = _parsed("A", "B")
    commits = [Commit(sap_code="A", cartons=40, arrival_week=date(2026, 11, 2), region="MDY"),
               Commit(sap_code="A", cartons=10, arrival_week=date(2026, 10, 19), region="YGN")]
    assert remove_commits(apply_commits(parsed, commits, PD)) == parsed
    assert remove_commits(parsed) == parsed


def test_commits_on_an_older_run_keep_its_sit_on_the_plan_date():
    old = _sku("A").model_copy(update={"sit_arrivals": None, "cities": None, "sit": 7})
    parsed = _parsed("A").model_copy(update={"skus": [old]})
    out = apply_commits(parsed, [Commit(sap_code="A", cartons=3, arrival_week=date(2026, 10, 19), region="YGN")], PD)
    sku = out.skus[0]
    assert sku.sit == 10
    assert [(a.date, a.cartons, a.source) for a in sku.sit_arrivals] == [(PD, 7, "sit"), (date(2026, 10, 19), 3, "commit")]


def test_put_commits_replaces_them_in_place_and_recalculates(client):
    client.put("/api/settings", json=[{"supplier": "CFC", "holding_days": 90, "moq": 0, "lead_time_days": 7,
                                       "order_cycle_weeks": 4}])
    first = [{"sap_code": CODE, "cartons": 50, "arrival_week": "2026-10-26", "region": "YGN"}]
    run = client.post("/api/runs", files=files(), data={"commits": json.dumps(first)}).json()
    plain = client.post("/api/runs", files=files()).json()
    runs_before = len(client.get("/api/runs").json())

    edited = [{"sap_code": CODE, "cartons": 80, "arrival_week": "2026-11-02", "region": "MDY"}]
    r = client.put(f"/api/runs/{run['id']}/commits", json=edited)
    assert r.status_code == 200
    out = r.json()
    assert out["id"] == run["id"] and len(client.get("/api/runs").json()) == runs_before   # same plan, no new one
    assert out["parsed"]["commits"] == edited
    ygn, mdy = _row(out, "YGN"), _row(out, "MDY")
    assert ygn["sit"] == _row(plain, "YGN")["sit"]                # the old Yangon commit is gone
    assert mdy["sit"] == _row(plain, "MDY")["sit"] + 80
    assert {"date": "2026-11-02", "cartons": 80, "source": "commit"} in mdy["sit_arrivals"]
    assert client.get(f"/api/runs/{run['id']}").json()["parsed"]["commits"] == edited   # saved

    cleared = client.put(f"/api/runs/{run['id']}/commits", json=[]).json()
    assert cleared["parsed"]["commits"] == [] and _row(cleared, "MDY")["sit"] == _row(plain, "MDY")["sit"]


def test_put_commits_checks_them(client):
    run = client.post("/api/runs", files=files()).json()
    bad = [{"sap_code": CODE, "cartons": 5, "arrival_week": "2026-10-05", "region": "YGN"}]
    r = client.put(f"/api/runs/{run['id']}/commits", json=bad)
    assert r.status_code == 422 and r.json()["detail"] == "Commit 1: the arrival week is before the plan week (12 Oct 2026)."
    assert client.put("/api/runs/9999/commits", json=[]).status_code == 404
    assert client.put(f"/api/runs/{run['id']}/commits", json=[{"sap_code": CODE}]).status_code == 422