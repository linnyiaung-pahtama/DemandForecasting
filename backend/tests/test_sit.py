from datetime import date

import pytest

from app.models import InputFileError, ParsedInput, SitArrival, SitFileSummary, SkuInput
from app.sit import apply_sit, parse_sit, week_monday
from tests.helpers import make_sit_workbook


def test_week_monday_rule():
    assert week_monday(10, 3, "2026-10") == date(2026, 10, 12)
    assert week_monday(10, 5, "2026-10") == date(2026, 10, 26)
    assert week_monday(11, 1, "2026-10") == date(2026, 10, 26)  # same week as Oct W5
    assert week_monday(11, 2, "2026-10") == date(2026, 11, 2)
    assert week_monday(2, 1, "2026-12") == date(2027, 2, 1)  # 1 Feb 2027 is a Monday
    assert week_monday(1, 1, "2026-12") == date(2026, 12, 28)  # Jan W1 in a December plan = next January
    assert week_monday(4, 1, "2026-10") == date(2027, 3, 29)  # 6-month tie -> later year


def test_parse_sit_headers():
    # "Sept", long name, extra spaces, case; non-arrival columns ignored
    data = make_sit_workbook([["A1", "P", "d", 5, 6, 7, 8]],
                             headers=["SAP Code", "By Principal", "Description", "Sept W1 Arrival",
                                      "october   w2 ARRIVAL", "Total SIT", "Oct W2"])
    lines = parse_sit(data).lines
    assert sorted((ln.month, ln.week, ln.cartons) for ln in lines) == [(9, 1, 5.0), (10, 2, 6.0)]


def test_parse_sit_real_layout():
    # group row above, same label under YGN and MDY added, hidden column read, sheet found by headers
    headers = ["SAP Code", "By Principal", "Description", "Oct W3 Arrival", "Oct W4 Arrival",
               "Oct W3 Arrival", "Oct W4 Arrival", "Total SIT"]
    data = make_sit_workbook([["5401", "P", "d", 41, None, 10, 2, 53]], headers=headers, sheet="Anything",
                             above=[[None, None, None, "YGN", None, "MDY"], [None] * 8], hidden_cols=("D",))
    lines = parse_sit(data).lines
    # each city keeps its own line (apply_sit adds them for the SKU's total)
    assert sorted((ln.code, ln.month, ln.week, ln.city, ln.cartons) for ln in lines) == [
        ("5401", 10, 3, "MDY", 10.0), ("5401", 10, 3, "YGN", 41.0), ("5401", 10, 4, "MDY", 2.0)]


def test_parse_sit_numeric_code():
    data = make_sit_workbook([[5401111001, "P", "d", 5]])
    assert [ln.code for ln in parse_sit(data).lines] == ["5401111001"]


def test_parse_sit_values():
    data = make_sit_workbook([["A1", "P", "d", " 1,250 ", 0, -3, "abc", 880.73]])
    report = parse_sit(data)
    assert sorted((ln.week, ln.cartons) for ln in report.lines if ln.month == 10) == [(3, 1250.0)]
    assert [(ln.month, ln.week, ln.cartons) for ln in report.lines if ln.month == 11] == [(11, 2, 880.73)]
    assert [(w.sap_code, w.column) for w in report.warnings] == [("A1", "Oct W5 Arrival"), ("A1", "Nov W1 Arrival")]
    assert all(w.message == "not a number of cartons above 0; skipped" for w in report.warnings)


def test_parse_sit_duplicate_rows_added():
    data = make_sit_workbook([["A1", "P", "d", 5], ["A1", "P", "d", 7]])
    assert sum(ln.cartons for ln in parse_sit(data).lines) == 12.0


def test_parse_sit_missing_sheet():
    data = make_sit_workbook([["A1", "P", "d", 5]], headers=["SAP Code", "By Principal", "Description", "Qty"])
    with pytest.raises(InputFileError, match=r"^No sheet has a SAP Code column and '<Month> W<n> Arrival' columns "
                                             r"\(looked in the first 10 rows of each sheet\)\.$"):
        parse_sit(data)


def test_parse_sit_unreadable_file():
    with pytest.raises(InputFileError, match="Could not read the file as an Excel .xlsx workbook."):
        parse_sit(b"not a workbook")


def _sku(code: str) -> SkuInput:
    return SkuInput(sap_code=code, supplier="P", description="d", packing_size=1, moq=0, shelf_life_months=None,
                    lead_time_days=None, sellable=0, non_sellable=0, sit=0, mtd_sales=0, forecast={})


def _parsed(*codes: str) -> ParsedInput:
    return ParsedInput(skus=[_sku(c) for c in codes], forecast_months=["2026-10"], mtd_month="2026-10",
                       mtd_label="x", mtd_end=date(2026, 10, 11), default_plan_date=date(2026, 10, 12), warnings=[])


def test_apply_sit():
    report = parse_sit(make_sit_workbook([["A1", "P", "d", 5, 7], ["A2", "P", "d"], ["ZZ", "P", "d", 9]]))
    parsed, summary, warnings = apply_sit(_parsed("A1", "A2", "A3"), report)
    a1, a2, a3 = parsed.skus
    assert a1.sit == 12.0
    assert a1.sit_arrivals == [SitArrival(date=date(2026, 10, 12), cartons=5),
                               SitArrival(date=date(2026, 10, 19), cartons=7)]
    assert (a2.sit, a2.sit_arrivals) == (0.0, [])
    assert (a3.sit, a3.sit_arrivals) == (0.0, [])
    assert summary == SitFileSummary(skus_with_sit=1, cartons=12.0, first_arrival=date(2026, 10, 12),
                                     last_arrival=date(2026, 10, 19))
    messages = [(w.sap_code, w.message) for w in warnings]
    assert (None, "1 stock codes in the Stock in Transit file are not in the Sales Forecast file; ignored") in messages
    assert (None, "1 SKUs in the Sales Forecast file are not in the Stock in Transit file; their SIT is 0") in messages


def test_apply_sit_same_week_two_labels_added():
    # Oct W5 and Nov W1 are the same week (26 Oct), so they land on one date
    report = parse_sit(make_sit_workbook([["A1", "P", "d", None, None, 4, 6]]))
    parsed, _, warnings = apply_sit(_parsed("A1"), report)
    assert parsed.skus[0].sit_arrivals == [SitArrival(date=date(2026, 10, 26), cartons=10)]
    assert warnings == []


def test_apply_sit_drops_cell_warnings_for_unknown_codes():
    report = parse_sit(make_sit_workbook([["A1", "P", "d", 5], ["ZZ", "P", "d", -1]]))
    _, _, warnings = apply_sit(_parsed("A1"), report)
    assert all(w.sap_code != "ZZ" for w in warnings)
