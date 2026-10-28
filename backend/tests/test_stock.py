from datetime import date, datetime
from pathlib import Path

import pytest

from app.models import InputFileError
from app.stock import parse_pdg, parse_pg
from tests.helpers import make_pdg_workbook, make_pg_workbook

SAMPLE = Path(__file__).parent / "fixtures" / "sample_input.xlsx"


def test_pg_lines_and_split():
    r = parse_pg(make_pg_workbook([["A1", "W1", "Sellable", 24, 12, 2, None, None],
                                   ["A1", "W2", "Non-Sellable", 6, 12, 0.5, None, None]]))
    assert r.source == "PG" and [(l.code, l.sellable, l.cartons) for l in r.lines] == [("A1", True, 2), ("A1", False, 0.5)]


def test_pdg_cartons_are_bin_qty_over_ratio_and_cs_is_ignored():
    r = parse_pdg(make_pdg_workbook([[120701330181, "Wine", "DC-YGN01", None, 12, 159, 999]]))
    assert r.lines[0].cartons == pytest.approx(13.25) and r.lines[0].sellable and r.as_of == date(2026, 10, 12)


def test_pdg_numeric_codes_and_trimmed_pg_codes():
    assert parse_pdg(make_pdg_workbook([[120701330181.0, "x", "L", None, 1, 1, None]])).lines[0].code == "120701330181"
    assert parse_pg(make_pg_workbook([["  3102111001 ", "W", "Sellable", 1, 1, 1, None, None]])).lines[0].code == "3102111001"


def test_flag_values_ignore_case_and_spaces():
    pg = parse_pg(make_pg_workbook([["A", "W", " sellable ", 1, 1, 1, None, None], ["A", "W", "NON-SELLABLE", 1, 1, 1, None, None]]))
    pdg = parse_pdg(make_pdg_workbook([["1", "x", "L", " NON ", 1, 1, None]]))
    assert [l.sellable for l in pg.lines] == [True, False] and pg.warnings == []
    assert pdg.lines[0].sellable is False and pdg.warnings == []


def test_unknown_flag_values_count_as_non_sellable_with_one_warning_per_value():
    r = parse_pg(make_pg_workbook([["A", "W", "Transit", 1, 1, 1, None, None]] * 3))
    assert [l.sellable for l in r.lines] == [False] * 3
    assert [w.message for w in r.warnings] == [
        "PG Expiry Check: 3 rows have Location 'Transit' (not Sellable or Non-Sellable); counted as non-sellable"]
    p = parse_pdg(make_pdg_workbook([["1", "x", "L", "Hold", 1, 1, None]]))
    assert p.warnings[0].message == "PDG Stock List: 1 rows have Sell or Non 'Hold' (not blank or Non); counted as non-sellable"


def test_unreadable_quantities_are_skipped_with_codes_recorded():
    r = parse_pdg(make_pdg_workbook([["1", "x", "L", None, 0, 5, None], ["2", "x", "L", None, 12, "n/a", None],
                                     ["3", "x", "L", None, 12, 24, None]]))
    assert [l.code for l in r.lines] == ["3"] and r.skipped_codes == ["1", "2"]
    assert r.warnings[0].message == "PDG Stock List: 2 rows have no readable Bin_Qty or U_Ratio; skipped"


def test_pg_as_of_is_most_common_expiry_minus_days_left():
    rows = [["A", "W", "Sellable", 1, 1, 1, datetime(2027, 1, 1), 81], ["A", "W", "Sellable", 1, 1, 1, datetime(2027, 1, 2), 82],
            ["A", "W", "Sellable", 1, 1, 1, datetime(2027, 1, 1), 1], ["A", "W", "Sellable", 1, 1, 1, " ", None]]
    assert parse_pg(make_pg_workbook(rows)).as_of == date(2026, 10, 12)


def test_hidden_rows_still_count_with_warning():
    r = parse_pg(make_pg_workbook([["A", "W", "Sellable", 1, 1, 1, None, None]] * 2, hidden_rows=(4,)))
    assert len(r.lines) == 2
    assert r.warnings[-1].message == "PG Expiry Check: 1 rows are hidden by a filter; they are still counted"


def test_rejections():
    with pytest.raises(InputFileError, match="Could not read"):
        parse_pg(b"not a workbook")
    with pytest.raises(InputFileError, match="No sheet has StockCode"):
        parse_pdg(make_pg_workbook([["A", "W", "Sellable", 1, 1, 1, None, None]]))
    with pytest.raises(InputFileError, match="No data rows"):
        parse_pg(make_pg_workbook([]))


def test_fixture_reports():
    pg, pdg = parse_pg(SAMPLE.read_bytes()), parse_pdg(SAMPLE.read_bytes())
    assert pg.as_of == date(2026, 10, 12) and pdg.as_of == date(2026, 10, 12)
    assert len(pg.lines) == 6224 and len(pdg.lines) == 236 and pg.warnings == [] and pdg.warnings == []
