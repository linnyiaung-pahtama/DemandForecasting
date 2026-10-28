from pathlib import Path
import pytest
from app.models import InputFileError
from app.parsing import parse_input
from app.sales import parse_sales, actual_cartons
from tests.helpers import make_workbook, make_sales_workbook

FIX = Path(__file__).parent / "fixtures"
DATA = parse_input((FIX / "sample_input.xlsx").read_bytes())
ROW = lambda code, month, qty, year=2026: ["PG", "Yangon", "P", "B", code, "x", year, month, qty, 0]

def test_real_export_converts_to_cartons():
    act = actual_cartons(parse_sales((FIX / "sales_export.xlsx").read_bytes()), DATA)
    assert act.months == ["2026-07", "2026-08", "2026-09"]
    c = act.cartons["3102111001"]
    assert c["2026-07"] == pytest.approx(2113 / 40)
    assert c["2026-08"] == pytest.approx(1451 / 40) and c["2026-09"] == pytest.approx(1647 / 40)
    assert act.skus_with_sales == 141 and act.warnings == []

def test_sums_all_rows_of_an_item_and_month():
    ex = parse_sales(make_sales_workbook([ROW("3102111001", "Jul", 40), ROW("3102111001", "Jul", 80)]))
    assert ex.pieces["3102111001"]["2026-07"] == 120

def test_numeric_item_codes_match():
    ex = parse_sales(make_sales_workbook([ROW(3102111001, "Aug", 40)]))
    assert "3102111001" in ex.pieces

def test_pivot_sheet_without_qty_is_skipped():
    # real fixture has a pivot sheet with itemCode but no Qty; parse must still find Sheet1
    assert parse_sales((FIX / "sales_export.xlsx").read_bytes()).months == ["2026-07", "2026-08", "2026-09"]

def test_export_covering_other_months_warns_and_uses_overlap():
    ex = parse_sales(make_sales_workbook([ROW("3102111001", m, 40) for m in ("Aug", "Sep", "Oct")]))
    act = actual_cartons(ex, DATA)
    msgs = [w.message for w in act.warnings]
    assert any("Jul 2026" in m for m in msgs)            # missing actual month named
    assert any("Oct 2026" in m for m in msgs)            # extra month ignored, named
    assert set(act.cartons["3102111001"]) == {"2026-08", "2026-09"}

def test_export_with_no_actual_months_is_rejected():
    with pytest.raises(InputFileError, match="Jul 2026"):
        actual_cartons(parse_sales(make_sales_workbook([ROW("3102111001", "Nov", 40)])), DATA)

def test_unknown_item_and_missing_packing_and_bad_qty_warn():
    data = parse_input(make_workbook([["1001", "S", "x", None, 0, 6, 7, 10, 0, 0, 0] + [10] * 12]))
    ex = parse_sales(make_sales_workbook([ROW("1001", "Jul", 40), ROW("9999", "Jul", 5), ROW("1001", "Aug", "n/a")]))
    assert any("n/a" in w.message or w.column == "Qty" for w in ex.warnings)    # bad Qty row skipped
    act = actual_cartons(ex, data)
    msgs = " ".join(w.message for w in act.warnings)
    assert "9999" in msgs or any(w.sap_code == "9999" for w in act.warnings)    # not in Data
    assert "1001" not in act.cartons                                             # no packing size
    assert any(w.sap_code == "1001" for w in act.warnings)

def test_not_an_export_is_rejected():
    with pytest.raises(InputFileError, match="itemCode"):
        parse_sales((FIX / "sample_input.xlsx").read_bytes())    # the Data file
    with pytest.raises(InputFileError, match="xlsx"):
        parse_sales(b"not a workbook")
