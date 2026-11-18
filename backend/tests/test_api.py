import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from app.main import create_app
from tests.helpers import make_sit_workbook, sit_from_data, with_city_forecast

FIX = Path(__file__).parent / "fixtures"
DATA, SALES = (FIX / "sample_input.xlsx").read_bytes(), (FIX / "sales_export.xlsx").read_bytes()
SIT = sit_from_data(DATA)
CITY_DATA = with_city_forecast(DATA)   # the fixture plus YGN IMS / MDY IMS groups (Mandalay forecast 0)


@pytest.fixture
def client(db):
    return TestClient(create_app(**db))


def row(supplier, holding, moq=0, lead=None, cycle=4):
    """One PUT /api/settings item; every key is required."""
    return {"supplier": supplier, "holding_days": holding, "moq": moq, "lead_time_days": lead,
            "order_cycle_weeks": cycle}


def files(data=CITY_DATA, sales=SALES, pg=DATA, pdg=DATA, sit=SIT):
    """The fixture workbook carries the Data sheet and both stock sheets, so it serves as PG and PDG too. The SIT
    file holds the fixture's old Data-sheet SIT, landing on its plan date."""
    return {"data_file": ("data.xlsx", data), "sales_file": ("sales.xlsx", sales),
            "pg_file": ("pg.xlsx", pg), "pdg_file": ("pdg.xlsx", pdg), "sit_file": ("sit.xlsx", sit)}


def test_inspect_reports_months_and_coverage(client):
    r = client.post("/api/inspect", files=files()).json()
    assert r["actual_months"] == ["2026-07", "2026-08", "2026-09"]
    assert r["forecast_window"] == ["2026-10", "2026-11", "2026-12"]
    assert r["sku_count"] == 212 and r["skus_with_sales"] == 141 and r["sales_file_name"] == "sales.xlsx"


def test_new_run_blocks_all_suppliers_until_holding_set(client):
    run = client.post("/api/runs", files=files()).json()
    # every plan row is blocked: a row per SKU per city with something in it (more rows than the 212 SKUs)
    assert run["result"]["counts"]["HOLDING_NOT_SET"] == len(run["result"]["skus"]) > 212
    assert len(run["result"]["blocked_suppliers"]) == 17
    s = client.get("/api/settings").json()
    assert len(s) == 17 and all(x["holding_days"] is None for x in s)


def test_set_holding_recalculates_real_sku(client):
    run = client.post("/api/runs", files=files()).json()
    assert client.put("/api/settings", json=[row("CFC", 90, lead=7)]).status_code == 200
    rec = client.post(f"/api/runs/{run['id']}/recalculate").json()
    sku = next(x for x in rec["result"]["skus"] if x["sap_code"] == "3102111001" and x["city"] == "YGN")
    # Yangon actuals 52.9, 36.375, 41.25 (Yangon branches only); Yangon forecast 55, 55, 55 -> average 49.254 a month;
    # buffer = 49.254 / 30 x 90 days = 147.7625
    assert sku["avg_sales"] == pytest.approx(49.2541667) and sku["buffer"] == pytest.approx(147.7625)
    assert sku["target"] == pytest.approx(147.7625) and sku["available"] == pytest.approx(38.15)
    assert sku["order_qty"] == 110 and sku["status"] == "TO_ORDER"
    assert sku["next_calc_date"] == "2026-10-19"
    log = client.get("/api/settings/log").json()
    holding = next(e for e in log if e["field"] == "holding_days")
    assert holding["supplier"] == "CFC" and holding["old_value"] is None and holding["new_value"] == 90


def test_holding_validation(client):
    for bad in (0, 14, 721, 45.5, "abc"):
        assert client.put("/api/settings", json=[row("A", bad)]).status_code == 422
    assert client.put("/api/settings", json=[row("A", None)]).status_code == 200


def test_swapped_files_return_400(client):
    r = client.post("/api/inspect", files=files(data=SALES, sales=DATA))
    assert r.status_code == 400 and r.json()["detail"].startswith("Sales Forecast file:")
    r = client.post("/api/runs", files=files(sales=DATA))
    assert r.status_code == 400 and r.json()["detail"].startswith("Actual Sales file:")


def test_plan_date_range_and_404s(client):
    assert client.post("/api/runs", files=files(), data={"plan_date": "2026-11-02"}).status_code == 422
    assert client.get("/api/runs/999").status_code == 404
    assert client.post("/api/runs/999/recalculate").status_code == 404


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_recalculate_keeps_non_default_plan_date(client):
    run = client.post("/api/runs", files=files(), data={"plan_date": "2026-10-20"}).json()
    assert run["plan_date"] == "2026-10-20"
    rec = client.post(f"/api/runs/{run['id']}/recalculate").json()
    assert rec["plan_date"] == "2026-10-20" and rec["result"]["plan_date"] == "2026-10-20"
    assert client.get(f"/api/runs/{run['id']}").json()["plan_date"] == "2026-10-20"


def test_plan_date_parsing_and_upper_bound(client):
    assert client.post("/api/runs", files=files(), data={"plan_date": "not-a-date"}).status_code == 422
    assert client.post("/api/runs", files=files(), data={"plan_date": "2026-10-31"}).status_code == 200


def test_suppliers_route(client):
    run = client.post("/api/runs", files=files()).json()
    r = client.get(f"/api/runs/{run['id']}/suppliers")
    assert r.status_code == 200 and len(r.json()) == 17
    assert client.get("/api/runs/999/suppliers").status_code == 404


def test_export_route(client):
    run = client.post("/api/runs", files=files()).json()
    r = client.get(f"/api/runs/{run['id']}/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert r.headers["content-disposition"] == f'attachment; filename="order-plan-2026-10-12-run{run["id"]}.xlsx"'
    assert client.get("/api/runs/999/export").status_code == 404


def test_holding_bounds_accepted(client):
    for ok in (15, 720, 45):
        assert client.put("/api/settings", json=[row("A", ok)]).status_code == 200


def test_holding_error_names_supplier_and_rejects_non_numbers(client):
    for bad in (0, 14, 721, 45.5, "abc", True, [3]):
        r = client.put("/api/settings", json=[row("Acme", bad)])
        assert r.status_code == 422
        assert r.json()["detail"] == "Principal 'Acme': holding must be a whole number of days from 15 to 720, or blank."


def test_failed_batch_saves_nothing(client):
    client.post("/api/runs", files=files())
    before = client.get("/api/settings").json()
    r = client.put("/api/settings", json=[row("CFC", 90),
                                          row("Bad", 999)])
    assert r.status_code == 422
    assert client.get("/api/settings").json() == before
    assert client.get("/api/settings/log").json() == []


def test_malformed_settings_body_returns_422(client):
    assert client.put("/api/settings", json=[{"holding_days": 90}]).status_code == 422
    assert client.put("/api/settings", json=["x"]).status_code == 422


def test_negative_year_in_sales_export_is_not_a_server_error(client):
    from tests.helpers import make_sales_workbook
    row = ["PG", "Yangon", "P", "B", "3102111001", "x", -2026, "Jul", 40, 0]
    bad = make_sales_workbook([row] + [["PG", "Yangon", "P", "B", "3102111001", "x", 2026, m, 40, 0]
                                       for m in ("Jul", "Aug", "Sep")])
    r = client.post("/api/inspect", files=files(sales=bad))
    assert r.status_code == 200
    assert any("year/month" in w["message"] for w in r.json()["warnings"])
    only_bad = make_sales_workbook([row])
    assert client.post("/api/inspect", files=files(sales=only_bad)).status_code == 400


def test_window_coverage_warnings_reach_inspect_and_the_stored_run(client):
    from tests.helpers import DEFAULT_HEADERS, make_sales_workbook, make_workbook
    headers = DEFAULT_HEADERS[:12]            # the Oct forecast column only
    data = with_city_forecast(make_workbook([["F1", "Sup", "Noodles", 10, 0, 6, 7, 100, 0, 0, 5, 50]], headers=headers))
    sales = make_sales_workbook([["PG", "Yangon", "P", "B", "F1", "x", 2026, m, 40, 0] for m in ("Jul", "Aug", "Sep")])
    # the combined forecast, then each city's (Oct only), are each missing Nov and Dec
    expected = [f"No {who}forecast column for {m} 2026 — counted as missing"
                for who in ("", "Yangon ", "Mandalay ") for m in ("Nov", "Dec")]
    # the Data headers hold the Total Sellable/Non-Sellable stock columns, which the parser now reports as ignored
    ignored = ("Stock and SIT columns in the Data sheet are ignored; stock comes from the PDG Stock List and PG Expiry "
               "Check files, and stock in transit from the Stock in Transit file.")
    # ...and the MOQ / Lead Time columns, which now come from supplier settings
    settings_ignored = "MOQ and Lead Time columns in the Data sheet are ignored; they come from Principal settings."
    parsed_messages = [ignored, settings_ignored, *expected]
    inspected = client.post("/api/inspect", files=files(data, sales, sit=sit_from_data(data))).json()
    # inspect = Data warnings, then the stock reports' merge warnings (the fixture's stock sheets have none of F1's codes)
    stock_messages = [
        "PG Expiry Check: 108 stock codes are not in the Data sheet; ignored",
        "PG Expiry Check has no stock for any SKU in the Data sheet — check that it is the right report",
        "PDG Stock List: 68 stock codes are not in the Data sheet; ignored",
        "PDG Stock List has no stock for any SKU in the Data sheet — check that it is the right report"]
    assert [w["message"] for w in inspected["warnings"] if w["sap_code"] is None] == parsed_messages + stock_messages
    run = client.post("/api/runs", files=files(data, sales, sit=sit_from_data(data))).json()
    assert [w["message"] for w in run["parsed"]["warnings"] if w["sap_code"] is None] == parsed_messages


def test_saved_run_hides_shelf_life_and_mtd_warnings_stored_earlier(client, db_conn):
    import json
    run = client.post("/api/runs", files=files()).json()
    parsed = json.loads(db_conn.execute("SELECT parsed_json FROM runs WHERE id = %s", (run["id"],)).fetchone()["parsed_json"])
    parsed["warnings"] += [
        {"sap_code": "3401111002", "column": parsed["mtd_label"],
         "message": "negative MTD sales (not used in the order calculation)"},
        {"sap_code": "120902330001", "column": "Shelf Life month",
         "message": "shelf life 0 (not used in the order calculation)"}]
    db_conn.execute("UPDATE runs SET parsed_json = %s WHERE id = %s", (json.dumps(parsed), run["id"]))
    db_conn.commit()
    shown = client.get(f"/api/runs/{run['id']}").json()["parsed"]["warnings"]
    assert shown == run["parsed"]["warnings"]
    assert not [w for w in shown if w["column"] in ("Shelf Life month", parsed["mtd_label"])]


def test_inspect_reports_stock(client):
    r = client.post("/api/inspect", files=files()).json()
    assert r["pg_file_name"] == "pg.xlsx" and r["pdg_file_name"] == "pdg.xlsx"
    assert r["stock"]["skus_with_stock"] == 136
    assert r["stock"]["pg"]["as_of"] == "2026-10-12" and r["stock"]["pdg"]["as_of"] == "2026-10-12"
    assert any(w["message"].startswith("Stock and SIT columns in the Data sheet are ignored") for w in r["warnings"])


def test_inspect_reports_sit_summary(client):
    r = client.post("/api/inspect", files=files()).json()
    assert r["sit_file_name"] == "sit.xlsx"
    parsed = client.post("/api/runs", files=files()).json()["parsed"]
    with_sit = [s["sit"] for s in parsed["skus"] if s["sit"] > 0]
    assert r["stock"]["sit"]["skus_with_sit"] == len(with_sit) > 0
    assert r["stock"]["sit"]["cartons"] == pytest.approx(sum(with_sit))
    assert r["stock"]["sit"]["first_arrival"] == r["stock"]["sit"]["last_arrival"] == "2026-10-12"


def test_sit_file_error_named(client):
    bad = make_sit_workbook([["A1", "P", "d", 5]], headers=["SAP Code", "By Principal", "Description", "Qty"])
    for url in ("/api/inspect", "/api/runs"):
        r = client.post(url, files=files(sit=bad))
        assert r.status_code == 400
        assert r.json()["detail"].startswith("Stock in Transit file: No sheet has a SAP Code column")


def test_sit_file_required(client):
    without = {k: v for k, v in files().items() if k != "sit_file"}
    assert client.post("/api/inspect", files=without).status_code == 422
    assert client.post("/api/runs", files=without).status_code == 422


def test_run_stores_sit_file_name_and_arrivals(client):
    run = client.post("/api/runs", files=files()).json()
    assert run["sit_file_name"] == "sit.xlsx" and isinstance(run["stock"]["sit_warnings"], list)
    assert client.get("/api/runs").json()[0]["sit_file_name"] == "sit.xlsx"
    sku = next(s for s in run["result"]["skus"] if s["sit"] > 0)
    assert sku["sit_arrivals"] == [{"date": "2026-10-12", "cartons": sku["sit"], "source": "sit"}]
    assert run["result"]["skus"][0]["order_plan"][0]["arrivals"] is not None


def test_sit_warnings_reach_inspect(client):
    extra = make_sit_workbook([["NOT-A-SKU", "P", "d", 5]])
    r = client.post("/api/inspect", files=files(sit=extra)).json()
    msgs = [w["message"] for w in r["warnings"]]
    assert "1 stock codes in the Stock in Transit file are not in the Sales Forecast file; ignored" in msgs
    assert "212 SKUs in the Sales Forecast file are not in the Stock in Transit file; their SIT is 0" in msgs


def test_inspect_flags_stock_reports_far_from_the_default_plan_date(client):
    from tests.helpers import DEFAULT_HEADERS, make_workbook
    r = client.post("/api/inspect", files=files()).json()      # stock as of 12 Oct, default plan date 12 Oct
    assert not any("the plan date" in w["message"] for w in r["warnings"])
    headers = [h.replace("(1-11 Oct)", "(1-19 Oct)") for h in DEFAULT_HEADERS]
    late = with_city_forecast(make_workbook([["F1", "Sup", "Noodles", 10, 0, 6, 7, 100, 0, 0, 5] + [50] * 12],
                                            headers=headers))
    r = client.post("/api/inspect", files=files(data=late)).json()
    assert r["default_plan_date"] == "2026-10-20"
    msgs = [w["message"] for w in r["warnings"]]
    assert "PDG Stock List was printed on 12 Oct 2026, 8 days before the plan date" in msgs
    assert "PG Expiry Check is as of 12 Oct 2026, 8 days before the plan date" in msgs


def test_swapped_stock_files_return_400(client):
    from tests.helpers import make_pg_workbook
    pg_only = make_pg_workbook([["3102111001", "W", "Sellable", 1, 1, 1, None, None]])
    r = client.post("/api/inspect", files=files(pdg=pg_only))
    assert r.status_code == 400 and r.json()["detail"].startswith("PDG Stock List: No sheet has StockCode")
    r = client.post("/api/runs", files=files(pg=SALES))
    assert r.status_code == 400 and r.json()["detail"].startswith("PG Expiry Check: No sheet has Item Code")


def test_run_stores_stock_and_date_warning(client):
    run = client.post("/api/runs", files=files(), data={"plan_date": "2026-10-20"}).json()
    assert run["pg_file_name"] == "pg.xlsx" and run["stock"]["skus_with_stock"] == 136
    msgs = [w["message"] for w in run["stock"]["warnings"]]
    assert "PG Expiry Check is as of 12 Oct 2026, 8 days before the plan date" in msgs
    rec = client.post(f"/api/runs/{run['id']}/recalculate").json()
    assert rec["stock"] == run["stock"]
    assert client.get("/api/runs").json()[0]["pdg_file_name"] == "pdg.xlsx"


MOQ_ERROR = "Principal 'Acme': MOQ must be a whole number of cartons, 0 or more."
LEAD_ERROR = "Principal 'Acme': lead time must be a whole number of days from 0 to 365, or blank."


def test_settings_round_trip(client):
    client.post("/api/runs", files=files())
    assert client.put("/api/settings", json=[row("CFC", 90, moq=200, lead=7)]).status_code == 200
    s = {x["supplier"]: x for x in client.get("/api/settings").json()}
    assert (s["CFC"]["holding_days"], s["CFC"]["moq"], s["CFC"]["lead_time_days"], s["CFC"]["sku_count"]) == (90, 200, 7, 5)
    assert all(x["moq"] == 0 and x["lead_time_days"] is None for name, x in s.items() if name != "CFC")
    log = client.get("/api/settings/log").json()
    assert sorted((e["supplier"], e["field"], e["new_value"]) for e in log) == [
        ("CFC", "holding_days", 90), ("CFC", "lead_time_days", 7), ("CFC", "moq", 200)]


def test_settings_validation_moq_and_lead(client):
    for bad in (-1, 1.5, True, "x", None):
        r = client.put("/api/settings", json=[row("Acme", 60, moq=bad)])
        assert r.status_code == 422 and r.json()["detail"] == MOQ_ERROR, bad
    for bad in (-1, 366, 2.5, True):
        r = client.put("/api/settings", json=[row("Acme", 60, lead=bad)])
        assert r.status_code == 422 and r.json()["detail"] == LEAD_ERROR, bad
    r = client.put("/api/settings", json=[row("Good", 60, moq=8000.0, lead=None), row("Acme", 60, moq=-1)])
    assert r.status_code == 422 and client.get("/api/settings/log").json() == []
    assert client.put("/api/settings", json=[row("Good", 60, moq=8000.0, lead=None)]).status_code == 200
    good = next(x for x in client.get("/api/settings").json() if x["supplier"] == "Good")
    assert good["moq"] == 8000 and good["lead_time_days"] is None


def test_settings_missing_keys_returns_422(client):
    r = client.put("/api/settings", json=[{"supplier": "A", "holding_days": 90}])
    assert r.status_code == 422
    assert r.json()["detail"] == ("Each setting needs a supplier name and holding_days, moq, lead_time_days "
                                  "and order_cycle_weeks values.")
    old_client_body = {"supplier": "A", "holding_days": 90, "moq": 0, "lead_time_days": None,
                       "order_cycle_months": 1}   # a client still sending the months cycle
    assert client.put("/api/settings", json=[old_client_body]).status_code == 422


CYCLE_ERROR = "Principal 'Acme': order cycle must be a whole number of weeks from 1 to 52."


@pytest.mark.parametrize("bad", [0, 53, 1.5, "4", None, True, -1])
def test_order_cycle_validation(client, bad):
    r = client.put("/api/settings", json=[row("Acme", 60, cycle=bad)])
    assert r.status_code == 422 and r.json()["detail"] == CYCLE_ERROR


def test_order_cycle_default_and_round_trip(client):
    client.post("/api/runs", files=files())
    assert all(v["order_cycle_weeks"] == 4 for v in client.get("/api/settings").json())
    assert client.put("/api/settings", json=[row("CFC", 90, cycle=52.0)]).status_code == 200
    s = {x["supplier"]: x for x in client.get("/api/settings").json()}
    assert s["CFC"]["order_cycle_weeks"] == 52
    assert all(x["order_cycle_weeks"] == 4 for name, x in s.items() if name != "CFC")
    log = client.get("/api/settings/log").json()
    assert ("CFC", "order_cycle_weeks", 4, 52) in [(e["supplier"], e["field"], e["old_value"], e["new_value"])
                                                   for e in log]


def test_saved_month_cycle_run_shows_recalculate(client, db_conn):
    import json
    run_id = client.post("/api/runs", files=files()).json()["id"]
    # rewrite the stored result as a run saved with a months cycle
    result = json.loads(db_conn.execute("SELECT result_json FROM runs WHERE id = %s", (run_id,)).fetchone()["result_json"])
    for item in result["skus"] + result["settings_used"]:
        item.pop("order_cycle_weeks")
        item["order_cycle_months"] = 3
    db_conn.execute("UPDATE runs SET result_json = %s WHERE id = %s", (json.dumps(result), run_id))
    db_conn.commit()
    old = client.get(f"/api/runs/{run_id}").json()["result"]
    assert all(s["order_plan"] is None and s["plan_order_qty"] is None for s in old["skus"])
    assert old["plan_counts"] is None and all(s["monthly"] is not None for s in old["skus"])
    assert all(x["order_cycle_weeks"] is None and x["plan_total_order_qty"] is None
               for x in client.get(f"/api/runs/{run_id}/suppliers").json())
    assert client.get(f"/api/runs/{run_id}/export").status_code == 200
    fresh = client.post(f"/api/runs/{run_id}/recalculate").json()["result"]
    assert all(s["order_cycle_weeks"] == 4 and s["order_plan"] is not None for s in fresh["skus"])


def test_recalculate_refreshes_monthly_plan(client):
    run = client.post("/api/runs", files=files()).json()
    assert client.put("/api/settings", json=[row("CFC", 90, moq=500, lead=7)]).status_code == 200
    rec = client.post(f"/api/runs/{run['id']}/recalculate").json()
    orders = [m["order"] for m in next(s for s in rec["result"]["skus"] if s["sap_code"] == "3102111001")["monthly"]]
    assert 500 in orders and 0 in orders and rec["result"]["plan_months"][0] == "2026-10"
    assert client.put("/api/settings", json=[row("CFC", 90, moq=0, lead=7)]).status_code == 200
    rec = client.post(f"/api/runs/{run['id']}/recalculate").json()
    orders = [m["order"] for m in next(s for s in rec["result"]["skus"] if s["sap_code"] == "3102111001")["monthly"]]
    assert 500 not in orders

def test_upload_without_city_forecast_is_rejected(client):
    for url in ("/api/inspect", "/api/runs"):
        r = client.post(url, files=files(data=DATA))
        assert r.status_code == 400
        assert r.json()["detail"] == ("Sales Forecast file: the Data sheet has no Yangon and Mandalay forecast "
                                      "columns (headers like \"Oct'26\" under 'YGN IMS' and 'MDY IMS' labels).")


def test_run_has_a_row_per_city_with_something(client):
    run = client.post("/api/runs", files=files()).json()
    rows = run["result"]["skus"]
    assert {r["city"] for r in rows} == {"YGN", "MDY"}
    codes = {r["sap_code"] for r in rows}
    assert len(codes) == 212 and run["sku_count"] == 212
    assert all(sum(1 for r in rows if r["sap_code"] == c and r["city"] == "YGN") <= 1 for c in codes)
    assert run["actual"]["city_cartons"]["MDY"]   # the fixture's sales include Mandalay branches