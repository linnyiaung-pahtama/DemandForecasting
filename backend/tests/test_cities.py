from datetime import date

import pytest

from app.cities import branch_city, group_labels, label_city
from app.models import InputFileError
from app.parsing import parse_input
from app.sales import actual_cartons, parse_sales
from app.sit import apply_sit, parse_sit
from app.stock import apply_stock, parse_pdg, parse_pg
from tests.helpers import (DEFAULT_HEADERS, PDG_HEADERS, PG_HEADERS, city_headers, make_pdg_workbook,
                           make_pg_workbook, make_sales_workbook, make_sit_workbook, make_workbook)

ROW = ["1001", "Honesty", "X", 12, 0, 6, 14, 0, 0, 0, 5] + [10] * 12   # DEFAULT_HEADERS row, combined forecast 10


def test_branch_city_rule():
    for b in ("Mandalay", "Taunggyi", "Naypyitaw", "Nay Pyi Taw", "SubDistributor-Upper", " mandalay "):
        assert branch_city(b) == "MDY", b
    for b in ("Yangon", "Bago", "SubDistributor-Lower", "Monywa", "NULL", None, ""):
        assert branch_city(b) == "YGN", b


def test_label_city():
    assert [label_city(x) for x in ("YGN IMS", "MDY IMS", "Yangon", "Mandalay", "YGN", "MDY")] == \
        ["YGN", "MDY", "YGN", "MDY", "YGN", "MDY"]
    assert label_city("Total IMS") is None and label_city("YGN IMS Total") is None and label_city("x") is None


def test_group_labels_carry_right_and_skip_numbers():
    rows = [(None, None, "YGN", None, 5, "MDY", None), (None, 12.5, None, None, None, None, None)]
    assert group_labels(rows, 7) == [None, None, "YGN", "YGN", "YGN", "MDY", "MDY"]


# ---- Data sheet: forecast by city ---------------------------------------------------------------

def test_city_forecast_parsed():
    headers, labels = city_headers()
    p = parse_input(make_workbook([ROW + [7, 8, 9, 3, 2, 1]], headers=headers, labels=labels))
    cities = p.skus[0].cities
    assert cities["YGN"].forecast == {"2026-10": 7, "2026-11": 8, "2026-12": 9}
    assert cities["MDY"].forecast == {"2026-10": 3, "2026-11": 2, "2026-12": 1}
    assert p.skus[0].forecast["2026-10"] == 10   # the combined columns still give the combined forecast
    assert not [w for w in p.warnings if "Yangon + Mandalay" in w.message]


def test_city_forecast_mismatch_warns_once_per_sku():
    headers, labels = city_headers()
    p = parse_input(make_workbook([ROW + [7, 8, 9, 2, 2, 1]], headers=headers, labels=labels))
    w = [w for w in p.warnings if "Yangon + Mandalay" in w.message]
    assert len(w) == 1 and w[0].sap_code == "1001"
    assert w[0].message == "Yangon + Mandalay forecast differs from the combined forecast in Oct 2026"


def test_combined_forecast_optional_with_city_groups():
    base = [h for h in DEFAULT_HEADERS if not h.endswith(" IMS")]
    headers, labels = city_headers(base)
    p = parse_input(make_workbook([ROW[:11] + [7, 8, 9, 3, 2, 1]], headers=headers, labels=labels))
    assert p.skus[0].forecast == {"2026-10": 10, "2026-11": 10, "2026-12": 10}
    assert p.forecast_months == ["2026-10", "2026-11", "2026-12"]


def test_total_group_and_total_columns_ignored():
    headers, labels = city_headers()
    headers = headers + ["YGN IMS Total", "Oct'26"]
    labels = {**labels, len(headers): "Total IMS"}
    p = parse_input(make_workbook([ROW + [7, 8, 9, 3, 2, 1, 24, 999]], headers=headers, labels=labels))
    assert p.skus[0].cities["YGN"].forecast["2026-10"] == 7 and p.skus[0].cities["MDY"].forecast["2026-10"] == 3


def test_only_one_city_group_rejected():
    headers = DEFAULT_HEADERS + ["Oct'26", "Nov'26", "Dec'26"]
    with pytest.raises(InputFileError, match="Mandalay forecast columns"):
        parse_input(make_workbook([ROW + [7, 8, 9]], headers=headers, labels={len(DEFAULT_HEADERS) + 1: "YGN IMS"}))


def test_no_city_groups_parses_combined_only():
    p = parse_input(make_workbook([ROW]))
    assert p.skus[0].cities is None


def test_negative_and_text_city_values():
    headers, labels = city_headers()
    p = parse_input(make_workbook([ROW + [-4, "n/a", 10, 0, 0, 0]], headers=headers, labels=labels))
    ygn = p.skus[0].cities["YGN"].forecast
    assert ygn["2026-10"] == 0 and ygn["2026-11"] == 0
    msgs = {(w.column, w.message) for w in p.warnings if w.sap_code == "1001"}
    assert ("YGN IMS Oct'26", "negative forecast treated as 0") in msgs
    assert ("YGN IMS Nov'26", "empty or non-numeric value treated as 0") in msgs


# ---- Actual Sales by branch -----------------------------------------------------------------------

def _city_parsed():
    headers, labels = city_headers()
    return parse_input(make_workbook([ROW + [7, 8, 9, 3, 2, 1]], headers=headers, labels=labels))


def test_sales_split_by_branch():
    sales = make_sales_workbook([["PG", "Yangon", "P", "B", "1001", "x", 2026, "Sep", 120, 0],
                                 ["PG", "Taunggyi", "P", "B", "1001", "x", 2026, "Sep", 24, 0],
                                 ["PG", "SubDistributor-Upper", "P", "B", "1001", "x", 2026, "Aug", 36, 0],
                                 ["PG", "SubDistributor-Lower", "P", "B", "1001", "x", 2026, "Aug", 12, 0]])
    actual = actual_cartons(parse_sales(sales), _city_parsed())
    assert actual.cartons["1001"] == {"2026-09": 12, "2026-08": 4}
    assert actual.city_cartons["YGN"]["1001"] == {"2026-09": 10, "2026-08": 1}
    assert actual.city_cartons["MDY"]["1001"] == {"2026-09": 2, "2026-08": 3}


def test_sales_without_branch_column_count_as_yangon_with_warning():
    headers = ["itemCode", "Year", "Month", "Qty"]
    actual = actual_cartons(parse_sales(make_sales_workbook([["1001", 2026, "Sep", 24]], headers=headers)),
                            _city_parsed())
    assert actual.city_cartons["YGN"]["1001"] == {"2026-09": 2} and actual.city_cartons["MDY"] == {}
    assert any(w.message == "The Actual Sales file has no BranchName column; all its sales count as Yangon"
               for w in actual.warnings)


def test_sales_without_cities_in_parsed_have_no_city_cartons():
    actual = actual_cartons(parse_sales(make_sales_workbook([["PG", "Mandalay", "P", "B", "1001", "x", 2026, "Sep", 24, 0]])),
                            parse_input(make_workbook([ROW])))
    assert actual.city_cartons is None


# ---- stock by branch ------------------------------------------------------------------------------

PG_CITY = PG_HEADERS + ["BranchName"]
PDG_CITY = PDG_HEADERS + ["WH B"]


def test_stock_split_by_branch():
    pg = parse_pg(make_pg_workbook([["1001", "W", "Sellable", 0, 1, 5, None, None, "Yangon"],
                                    ["1001", "W", "Sellable", 0, 1, 2, None, None, "Naypyitaw"],
                                    ["1001", "W", "Non-Sellable", 0, 1, 1, None, None, "Mandalay"]], headers=PG_CITY))
    pdg = parse_pdg(make_pdg_workbook([["1001", "x", "L", None, 1, 3, None, "Mandalay"],
                                       ["1001", "x", "L", None, 1, 4, None, "Yangon"]], headers=PDG_CITY))
    parsed, stock = apply_stock(_city_parsed(), pg, pdg)
    c = parsed.skus[0].cities
    assert (c["YGN"].sellable, c["YGN"].pg_sellable, c["YGN"].pdg_sellable) == (9, 5, 4)
    assert (c["MDY"].sellable, c["MDY"].pg_sellable, c["MDY"].pdg_sellable, c["MDY"].non_sellable) == (5, 2, 3, 1)
    assert parsed.skus[0].sellable == 14 and stock.warnings == []


def test_stock_without_city_columns_counts_as_yangon_with_warning():
    pg = parse_pg(make_pg_workbook([["1001", "W", "Sellable", 0, 1, 5, None, None]]))
    pdg = parse_pdg(make_pdg_workbook([["1001", "x", "L", None, 1, 3, None]]))
    parsed, stock = apply_stock(_city_parsed(), pg, pdg)
    assert parsed.skus[0].cities["YGN"].sellable == 8 and parsed.skus[0].cities["MDY"].sellable == 0
    msgs = [w.message for w in stock.warnings]
    assert "PG Expiry Check has no BranchName column; all its stock counts as Yangon" in msgs
    assert "PDG Stock List has no WH B column; all its stock counts as Yangon" in msgs


# ---- stock in transit by city label ----------------------------------------------------------------

def test_sit_split_by_label():
    headers = ["SAP Code", "By Principal", "Description", "Oct W3 Arrival", "Oct W4 Arrival", "Oct W3 Arrival",
               "Oct W4 Arrival", "Total SIT"]
    data = make_sit_workbook([["1001", "P", "d", 41, None, 10, 2, 53]], headers=headers,
                             above=[[None, None, None, "YGN", None, "MDY"], [None] * 8])
    report = parse_sit(data)
    parsed, summary, _ = apply_sit(_city_parsed(), report)
    c = parsed.skus[0].cities
    assert (c["YGN"].sit, [(a.date, a.cartons) for a in c["YGN"].sit_arrivals]) == (41, [(date(2026, 10, 12), 41)])
    assert (c["MDY"].sit, [(a.date, a.cartons) for a in c["MDY"].sit_arrivals]) == (
        12, [(date(2026, 10, 12), 10), (date(2026, 10, 19), 2)])
    assert parsed.skus[0].sit == 53 and summary.cartons == 53


def test_sit_without_labels_is_yangon():
    report = parse_sit(make_sit_workbook([["1001", "P", "d", 5]]))
    parsed, _, _ = apply_sit(_city_parsed(), report)
    assert parsed.skus[0].cities["YGN"].sit == 5 and parsed.skus[0].cities["MDY"].sit == 0


# ---- planning per city ----------------------------------------------------------------------------

from app.holding import plan_all  # noqa: E402
from app.models import ActualSales, CityInput, ParsedInput, SitArrival, SkuInput, SupplierSettings  # noqa: E402

ACT, FC = ["2026-07", "2026-08", "2026-09"], ["2026-10", "2026-11", "2026-12"]
PD = date(2026, 10, 12)


def _sku(code, ygn: CityInput, mdy: CityInput) -> SkuInput:
    total = lambda f: ygn.__getattribute__(f) + mdy.__getattribute__(f)
    return SkuInput(sap_code=code, supplier="S", description=code, packing_size=1, moq=0, shelf_life_months=None,
                    lead_time_days=None, sellable=total("sellable"), non_sellable=total("non_sellable"),
                    sit=total("sit"), mtd_sales=0,
                    forecast={m: ygn.forecast.get(m, 0) + mdy.forecast.get(m, 0) for m in FC},
                    sit_arrivals=[*ygn.sit_arrivals, *mdy.sit_arrivals], cities={"YGN": ygn, "MDY": mdy})


def _plan_cities(skus, city_actuals, moq=0, holding=90):
    parsed = ParsedInput(skus=skus, forecast_months=FC, mtd_month="2026-10", mtd_label="x",
                         mtd_end=date(2026, 10, 11), default_plan_date=PD, warnings=[])
    cartons = {}
    for city in city_actuals.values():
        for code, months in city.items():
            for m, v in months.items():
                cartons.setdefault(code, {})[m] = cartons.get(code, {}).get(m, 0) + v
    actual = ActualSales(months=ACT, cartons=cartons, skus_with_sales=len(cartons), warnings=[],
                         city_cartons={"YGN": city_actuals.get("YGN", {}), "MDY": city_actuals.get("MDY", {})})
    settings = {"S": SupplierSettings(supplier="S", holding_days=holding, moq=moq, lead_time_days=None,
                                      order_cycle_weeks=4)}
    return plan_all(parsed, actual, settings, PD)


def test_each_city_planned_from_its_own_inputs():
    ygn = CityInput(sellable=100, forecast={m: 120 for m in FC})
    mdy = CityInput(sellable=10, forecast={m: 30 for m in FC})
    result = _plan_cities([_sku("A", ygn, mdy)], {"YGN": {"A": {m: 120 for m in ACT}}, "MDY": {"A": {m: 30 for m in ACT}}})
    rows = {r.city: r for r in result.skus}
    assert set(rows) == {"YGN", "MDY"}
    assert (rows["YGN"].avg_sales, rows["YGN"].buffer, rows["YGN"].available, rows["YGN"].order_qty) == (120, 360, 100, 260)
    assert (rows["MDY"].avg_sales, rows["MDY"].buffer, rows["MDY"].available, rows["MDY"].order_qty) == (30, 90, 10, 80)
    assert all(r.sap_code == "A" and r.order_plan is not None for r in result.skus)


def test_moq_applies_to_each_city_order():
    ygn = CityInput(sellable=0, forecast={m: 120 for m in FC})
    mdy = CityInput(sellable=0, forecast={m: 10 for m in FC})
    result = _plan_cities([_sku("A", ygn, mdy)], {}, moq=50)
    rows = {r.city: r for r in result.skus}
    assert (rows["MDY"].order_qty, rows["MDY"].moq_applied) == (50, True)   # 30 needed, raised to the MOQ
    assert (rows["YGN"].order_qty, rows["YGN"].moq_applied) == (360, False)


def test_city_without_anything_has_no_row():
    ygn = CityInput(sellable=5, forecast={m: 10 for m in FC})
    result = _plan_cities([_sku("A", ygn, CityInput()), _sku("B", CityInput(), CityInput())], {})
    assert [(r.sap_code, r.city) for r in result.skus] == [("A", "YGN"), ("B", "YGN")]


def test_city_with_only_stock_or_sit_or_sales_gets_a_row():
    stock = _sku("A", CityInput(), CityInput(non_sellable=2))
    sit = _sku("B", CityInput(), CityInput(sit=4, sit_arrivals=[SitArrival(date=date(2026, 10, 19), cartons=4)]))
    sales = _sku("C", CityInput(), CityInput())
    result = _plan_cities([stock, sit, sales], {"MDY": {"C": {"2026-09": 3}}})
    assert [(r.sap_code, r.city) for r in result.skus] == [("A", "MDY"), ("B", "MDY"), ("C", "MDY")]


def test_run_out_flag_per_city():
    ygn = CityInput(sellable=500, forecast={m: 30 for m in FC})
    mdy = CityInput(sellable=5, forecast={m: 30 for m in FC}, sit=100,
                    sit_arrivals=[SitArrival(date=date(2026, 10, 19), cartons=100)])
    result = _plan_cities([_sku("A", ygn, mdy)], {})
    rows = {r.city: r for r in result.skus}
    assert rows["YGN"].runs_out_on is None
    assert (rows["MDY"].runs_out_on, rows["MDY"].runs_out_arrival) == (date(2026, 10, 17), date(2026, 10, 19))


def test_run_without_cities_plans_combined_rows():
    sku = _sku("A", CityInput(sellable=5, forecast={m: 10 for m in FC}), CityInput()).model_copy(update={"cities": None})
    parsed = ParsedInput(skus=[sku], forecast_months=FC, mtd_month="2026-10", mtd_label="x",
                         mtd_end=date(2026, 10, 11), default_plan_date=PD, warnings=[])
    actual = ActualSales(months=ACT, cartons={}, skus_with_sales=0, warnings=[])
    result = plan_all(parsed, actual, {}, PD)
    assert [(r.sap_code, r.city) for r in result.skus] == [("A", None)]

# ---- summary, export, storage, upload --------------------------------------------------------------

def _two_city_result():
    ygn = CityInput(sellable=100, forecast={m: 120 for m in FC})
    mdy = CityInput(sellable=5, forecast={m: 30 for m in FC}, sit=100,
                    sit_arrivals=[SitArrival(date=date(2026, 10, 19), cartons=100)])
    return _plan_cities([_sku("A", ygn, mdy), _sku("B", CityInput(sellable=1, forecast={m: 5 for m in FC}), CityInput())],
                        {})


def test_summary_counts_distinct_skus_and_sums_cities():
    from app.summary import summarize_suppliers
    result = _two_city_result()
    s = summarize_suppliers(result)[0]
    assert s.sku_count == 2   # A (two cities) and B
    assert s.total_order_qty == sum(r.order_qty for r in result.skus)
    assert s.skus_to_order == 2   # A (Yangon) and B; A's Mandalay SIT covers its buffer


def test_summary_sku_columns_count_skus_not_rows():
    from app.summary import summarize_suppliers
    # A: Yangon to order, Mandalay no demand data (stock only); B: no demand in either city; C: zero forecast in both
    a = _sku("A", CityInput(sellable=0, forecast={m: 30 for m in FC}), CityInput(sellable=4))
    b = _sku("B", CityInput(non_sellable=1), CityInput(non_sellable=1))
    c = _sku("C", CityInput(), CityInput())
    result = _plan_cities([a, b, c], {"YGN": {"C": {m: 10 for m in ACT}}, "MDY": {"C": {m: 5 for m in ACT}}})
    assert sorted((r.sap_code, r.city) for r in result.skus) == [
        ("A", "MDY"), ("A", "YGN"), ("B", "MDY"), ("B", "YGN"), ("C", "MDY"), ("C", "YGN")]
    s = summarize_suppliers(result)[0]
    assert s.sku_count == 3
    assert s.no_demand_skus == 1      # only B has no demand data in every city
    assert s.zero_forecast_skus == 1  # C, flagged in both cities
    assert s.skus_to_order == 2 and s.plan_skus_to_order == 2   # A (Yangon) and C (both cities: still 1 SKU)
    assert sum(1 for r in result.skus if r.order_qty > 0) == 3
    blocked = summarize_suppliers(_plan_cities([a, b, c], {}, holding=None))[0]
    assert blocked.blocked_skus == 3


def test_export_has_city_columns_and_city_run_out_text():
    from datetime import datetime
    from io import BytesIO
    import openpyxl
    from app.export import build_export
    from app.models import RunRecord
    result = _two_city_result()
    parsed = ParsedInput(skus=[], forecast_months=FC, mtd_month="2026-10", mtd_label="x",
                         mtd_end=date(2026, 10, 11), default_plan_date=PD, warnings=[])
    run = RunRecord(id=1, created_at=datetime(2026, 11, 11), file_name="d", sales_file_name="s", plan_date=PD,
                    sku_count=2, parsed=parsed, actual=ActualSales(months=ACT, cartons={}, skus_with_sales=0, warnings=[]),
                    result=result)
    wb = openpyxl.load_workbook(BytesIO(build_export(run)))
    for sheet in ("SKU Plan", "12-Month Plan", "Order Plan", "Order Dates"):
        header = [c.value for c in wb[sheet][1]]
        assert header[:4] == ["Principal", "SAP Code", "Region", "Description"], sheet
    cities = [(r[1], r[2]) for r in wb["SKU Plan"].iter_rows(min_row=2, values_only=True)]
    assert cities == [("A", "Yangon"), ("A", "Mandalay"), ("B", "Yangon")]
    warns = [r[3] for r in wb["Warnings"].iter_rows(min_row=2, values_only=True)]
    assert "Mandalay: runs out about 17 Oct, before its stock in transit arrives on 19 Oct" in warns


def test_stored_sku_count_is_distinct_skus(tmp_path):
    from app.models import StockFileSummary, StockResult
    from app.repository import Repository
    repo = Repository(tmp_path / "t.db")
    result = _two_city_result()
    parsed = ParsedInput(skus=[], forecast_months=FC, mtd_month="2026-10", mtd_label="x",
                         mtd_end=date(2026, 10, 11), default_plan_date=PD, warnings=[])
    summary = StockFileSummary(source="PG", as_of=None, skus_with_stock=0, sellable_cartons=0, non_sellable_cartons=0)
    stock = StockResult(pg=summary, pdg=summary.model_copy(update={"source": "PDG"}), skus_with_stock=0, warnings=[])
    run_id = repo.create_run("d", "s", "p", "q", "t", parsed,
                             ActualSales(months=ACT, cartons={}, skus_with_sales=0, warnings=[]), stock, result)
    assert repo.get_run(run_id).sku_count == 2 and repo.list_runs()[0].sku_count == 2
    repo.update_run_result(run_id, result)
    assert repo.get_run(run_id).sku_count == 2

def test_city_columns_out_of_order_are_rejected():
    # the labels typed one column to the right of each group's first month: Yangon's Oct'26 falls outside its group
    # and Mandalay's Oct'26 lands inside Yangon's, after Yangon's Dec'26
    headers, _ = city_headers()
    first = len(DEFAULT_HEADERS) + 1
    labels = {first + 1: "YGN IMS", first + 4: "MDY IMS"}
    with pytest.raises(InputFileError, match="Yangon forecast columns are out of order"):
        parse_input(make_workbook([ROW + [7, 8, 9, 3, 2, 1]], headers=headers, labels=labels))


def test_total_ims_header_is_not_a_forecast_warning():
    headers, labels = city_headers()
    headers = headers + ["YGN IMS Total", "Total IMS"]
    p = parse_input(make_workbook([ROW + [7, 8, 9, 3, 2, 1, 24, 30]], headers=headers, labels=labels))
    assert not [w for w in p.warnings if "looks like a forecast column" in w.message]