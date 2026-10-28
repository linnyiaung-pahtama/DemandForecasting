from datetime import date
import pytest
from pathlib import Path
from app.parsing import parse_input
from app.models import InputFileError
from tests.helpers import make_workbook

SAMPLE = Path(__file__).parent / "fixtures" / "sample_input.xlsx"

def test_parses_sample_file():
    p = parse_input(SAMPLE.read_bytes())
    assert len(p.skus) == 212
    assert len({s.supplier for s in p.skus}) == 17
    assert p.forecast_months == ["2026-10","2026-11","2026-12","2027-01","2027-02","2027-03",
                                 "2027-04","2027-05","2027-06","2027-07","2027-08","2027-09"]
    assert p.mtd_month == "2026-10"
    assert p.mtd_end == date(2026, 10, 11)
    assert p.default_plan_date == date(2026, 10, 12)
    sku = next(s for s in p.skus if s.sap_code == "3401111006")
    assert sku.supplier == "MayMyo Fresh Coffee"
    assert sku.lead_time_days == 7 and sku.packing_size == 30 and sku.shelf_life_months == 12
    assert sku.sellable == pytest.approx(44.1, abs=0.01)
    assert sku.sit == pytest.approx(41, abs=0.01)
    assert sku.forecast["2026-10"] == pytest.approx(128.71, abs=0.01)

def test_sample_warnings_for_zero_shelf_life_and_negative_mtd():
    p = parse_input(SAMPLE.read_bytes())
    msgs = [w.message for w in p.warnings]
    assert sum("shelf life 0" in m for m in msgs) == 3
    assert sum("negative MTD" in m for m in msgs) == 10
    # '-' shelf life means no expiry: no warning, value None
    assert sum(1 for s in p.skus if s.shelf_life_months is None) == 46  # 43 '-' + 3 zero

def test_detects_columns_by_pattern_in_next_cycle_file():
    headers = ["SAP Code","By Principal","Description","Packing Size","MOQ","Shelf Life month",
               "Lead Time","Total Sellable (Ctns)","Total Non-Sellable (Ctns)",
               "SIT  Ctns (pending order)","Nov'26   MTD Sale (1-8 Nov)",
               "2026 Nov IMS","2026  Dec IMS"]
    data = make_workbook([["1001","Honesty","X",12,0,6,14,10,0,0,5,100,90]], headers=headers)
    p = parse_input(data)
    assert p.forecast_months == ["2026-11","2026-12"]
    assert p.mtd_month == "2026-11" and p.default_plan_date == date(2026, 11, 9)

def test_supplier_names_are_trimmed():
    data = make_workbook([["1001","Honesty  ","X",12,0,6,14,10,0,0,5] + [10]*12])
    assert parse_input(data).skus[0].supplier == "Honesty"

def test_numeric_sap_code_has_no_decimal():
    data = make_workbook([[127902330249,"MVE","X",12,0,"-",30,10,0,0,5] + [10]*12])
    assert parse_input(data).skus[0].sap_code == "127902330249"

def test_blank_and_text_numbers_become_zero_with_warning():
    data = make_workbook([["1001","Honesty","X",12,0,6,14,None,0,"n/a",5] + [10]*12])
    p = parse_input(data)
    assert p.skus[0].sellable == 0 and p.skus[0].sit == 0
    assert {w.column for w in p.warnings} >= {"Total Sellable (Ctns)", "SIT Ctns (pending order)"}

def test_missing_lead_time_is_none_with_warning():
    data = make_workbook([["1001","Honesty","X",12,0,6,None,10,0,0,5] + [10]*12])
    p = parse_input(data)
    assert p.skus[0].lead_time_days is None
    assert any(w.column == "Lead Time" for w in p.warnings)

def test_negative_lead_time_is_none_with_warning():
    data = make_workbook([["1001","Honesty","X",12,0,6,-5,10,0,0,5] + [10]*12])
    p = parse_input(data)
    assert p.skus[0].lead_time_days is None
    assert any(w.column == "Lead Time" and "negative lead time" in w.message for w in p.warnings)

def test_duplicate_sap_code_keeps_first_with_warning():
    row = ["1001","Honesty","X",12,0,6,14,10,0,0,5] + [10]*12
    p = parse_input(make_workbook([row, row]))
    assert len(p.skus) == 1 and any("duplicate" in w.message for w in p.warnings)

def test_rejects_missing_data_sheet():
    with pytest.raises(InputFileError, match="Data"):
        parse_input(make_workbook([], sheet="Other"))

def test_rejects_missing_required_column():
    headers = ["SAP Code","By Principal","Description"]
    with pytest.raises(InputFileError, match="Lead Time"):
        parse_input(make_workbook([], headers=headers))

def test_rejects_non_excel_bytes():
    with pytest.raises(InputFileError):
        parse_input(b"SAP Code,By Principal\n1,2\n")

def test_numeric_text_is_parsed():
    data = make_workbook([["1001","Honesty","X"," 12 ","0"," 6 ","14.4","1,250.5","3","  7","1,000"] + ["1,250.5"]*12])
    p = parse_input(data)
    s = p.skus[0]
    assert s.packing_size == 12 and s.moq == 0 and s.shelf_life_months == 6
    assert s.lead_time_days == 14
    assert s.sellable == 1250.5 and s.non_sellable == 3 and s.sit == 7 and s.mtd_sales == 1000
    assert s.forecast["2026-10"] == 1250.5
    assert p.warnings == []


# ---- header handling and value cleaning ------------------------------------------------------

ROW = ["1001", "Honesty", "X", 12, 0, 6, 14, 10, 0, 0, 5]
BASE = ["SAP Code", "By Principal", "Description", "Packing Size", "MOQ", "Shelf Life month", "Lead Time",
        "Total Sellable (Ctns)", "Total Non-Sellable (Ctns)", "SIT Ctns (pending order)"]


def test_forecast_gap_is_rejected():
    headers = BASE + ["Oct'26 MTD Sale (1-11 Oct)", "2026 Oct IMS", "2026 Dec IMS"]
    with pytest.raises(InputFileError, match=r"consecutive.*2026-11.*2026-10.*2026-12"):
        parse_input(make_workbook([ROW + [10, 10]], headers=headers))


def test_forecast_starting_after_mtd_month_is_rejected():
    headers = BASE + ["Oct'26 MTD Sale (1-11 Oct)", "2026 Nov IMS", "2026 Dec IMS"]
    with pytest.raises(InputFileError, match="2026-11.*2026-10"):
        parse_input(make_workbook([ROW + [10, 10]], headers=headers))


def test_duplicate_forecast_month_is_rejected():
    headers = BASE + ["Oct'26 MTD Sale (1-11 Oct)", "2026 Oct IMS", "2026 October IMS"]
    with pytest.raises(InputFileError, match="2026-10"):
        parse_input(make_workbook([ROW + [10, 10]], headers=headers))


def test_unmatched_ims_header_gives_warning():
    headers = BASE + ["Oct'26 MTD Sale (1-11 Oct)", "2026 Oct IMS", "2026 Nov IMS", "Dec IMS (revised)"]
    p = parse_input(make_workbook([ROW + [10, 10, 10]], headers=headers))
    assert p.forecast_months == ["2026-10", "2026-11"]
    w = next(w for w in p.warnings if w.column == "Dec IMS (revised)")
    assert w.sap_code is None and "forecast" in w.message


def test_sept_and_curly_apostrophe_headers_parse():
    headers = BASE + ["Sept\u201926 MTD Sale (1-8 Sept)", "2026 Sept IMS", "2026 October IMS", "2026 Nov IMS"]
    p = parse_input(make_workbook([ROW + [10, 10, 10]], headers=headers))
    assert p.mtd_month == "2026-09" and p.mtd_end == date(2026, 9, 8)
    assert p.forecast_months == ["2026-09", "2026-10", "2026-11"]
    assert p.warnings == []


def test_four_letter_june_forecast_header_parses():
    headers = BASE + ["Jun'27 MTD Sale (1-8 June)", "2027 June IMS", "2027 July IMS"]
    p = parse_input(make_workbook([ROW + [10, 10]], headers=headers))
    assert p.forecast_months == ["2027-06", "2027-07"] and p.mtd_month == "2027-06"


def test_negative_shelf_life_becomes_unknown_with_warning():
    p = parse_input(make_workbook([["1001", "Honesty", "X", 12, 0, -6, 14, 10, 0, 0, 5] + [10] * 12]))
    assert p.skus[0].shelf_life_months is None
    assert any(w.column == "Shelf Life month" and "shelf life" in w.message and "not used" in w.message
               for w in p.warnings)


def test_negative_forecast_is_clamped_with_warning():
    p = parse_input(make_workbook([["1001", "Honesty", "X", 12, 0, 6, 14, 10, 0, 0, 5, -40] + [10] * 11]))
    assert p.skus[0].forecast["2026-10"] == 0
    w = next(w for w in p.warnings if "negative forecast" in w.message)
    assert w.sap_code == "1001" and w.column == "2026 Oct IMS"


# ---- forecast-window coverage ---------------------------------------------------------------

def test_missing_window_months_get_file_level_warnings():
    headers = BASE + ["Oct'26 MTD Sale (1-11 Oct)", "2026 Oct IMS"]
    p = parse_input(make_workbook([ROW + [10]], headers=headers))
    missing = [w for w in p.warnings if "No forecast column" in w.message]
    assert [w.message for w in missing] == ["No forecast column for Nov 2026 — counted as missing",
                                            "No forecast column for Dec 2026 — counted as missing"]
    assert all(w.sap_code is None for w in missing)


def test_full_window_has_no_coverage_warning():
    p = parse_input(SAMPLE.read_bytes())
    assert not any("No forecast column" in w.message for w in p.warnings)


def test_forecast_entirely_before_the_window_is_rejected():
    months = ["Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    headers = BASE + ["Oct'26 MTD Sale (1-11 Oct)"] + [
        f"{2025 if m in ('Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec') else 2026} {m} IMS" for m in months]
    with pytest.raises(InputFileError, match="Oct 2026.*Nov 2026.*Dec 2026"):
        parse_input(make_workbook([ROW + [10] * 12], headers=headers))


# ---- negative stock and v1-only wording -------------------------------------------------------

def test_negative_stock_warns():
    p = parse_input(make_workbook([["1001", "Honesty", "X", 12, 0, 6, 14, -20, 0, -3, 5] + [10] * 12]))
    assert p.skus[0].sellable == -20 and p.skus[0].sit == -3
    msgs = {w.column: w.message for w in p.warnings if "negative stock" in w.message}
    assert msgs == {"Total Sellable (Ctns)": "negative stock — check the stock report",
                    "SIT Ctns (pending order)": "negative stock — check the stock report"}
    assert all(w.sap_code == "1001" for w in p.warnings if "negative stock" in w.message)


def test_v1_only_warnings_say_they_are_not_used():
    rows = [["1001", "Honesty", "X", 12, 0, 0, 14, 10, 0, 0, -5] + [10] * 12,
            ["1002", "Honesty", "X", 12, 0, -2, 14, 10, 0, 0, 5] + [10] * 12,
            ["1003", "Honesty", "X", 12, 0, "n/a", 14, 10, 0, 0, 5] + [10] * 12]
    msgs = [w.message for w in parse_input(make_workbook(rows)).warnings]
    assert sorted(msgs) == [
        "negative MTD sales (not used in the order calculation)",
        "negative shelf life (not used in the order calculation)",
        "non-numeric shelf life (not used in the order calculation)",
        "shelf life 0 (not used in the order calculation)"]
