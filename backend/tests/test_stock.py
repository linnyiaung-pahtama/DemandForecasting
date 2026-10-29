from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pytest

from openpyxl import load_workbook

from app.models import InputFileError, ParseWarning, StockLine, StockReport
from app.parsing import parse_input
from app.stock import apply_stock, parse_pdg, parse_pg, stock_date_warnings
from tests.helpers import DEFAULT_HEADERS, make_pdg_workbook, make_pg_workbook, make_workbook

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
                                     ["3", "x", "L", None, 12, 24, None], ["4", "x", "L", None, -12, 12, None]]))
    assert [l.code for l in r.lines] == ["3"] and r.skipped_codes == ["1", "2", "4"]
    assert r.warnings[0].message == "PDG Stock List: 3 rows have no readable Bin_Qty or U_Ratio; skipped"


def test_pg_as_of_is_most_common_expiry_minus_days_left():
    rows = [["A", "W", "Sellable", 1, 1, 1, datetime(2027, 1, 1), 81], ["A", "W", "Sellable", 1, 1, 1, datetime(2027, 1, 2), 82],
            ["A", "W", "Sellable", 1, 1, 1, datetime(2027, 1, 1), 1], ["A", "W", "Sellable", 1, 1, 1, " ", None]]
    assert parse_pg(make_pg_workbook(rows)).as_of == date(2026, 10, 12)


def test_pg_as_of_skips_rows_with_an_absurd_day_left():
    rows = [["A", "W", "Sellable", 1, 1, 1, datetime(2027, 1, 1), 10 ** 7], ["A", "W", "Sellable", 1, 1, 1, datetime(2027, 1, 1), 81]]
    r = parse_pg(make_pg_workbook(rows))
    assert len(r.lines) == 2 and r.as_of == date(2026, 10, 12)


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


# ---- totals per Data SKU ----------------------------------------------------------------------

def _data_sheet_stock(raw: bytes) -> dict[str, tuple[float, float, float, float]]:
    """SAP code -> (Sellable PG, Sellable PDG, Non-Sellable PG, Non-Sellable PDG) as typed in the Data sheet."""
    wb = load_workbook(BytesIO(raw), read_only=True, data_only=True)
    rows = list(wb["Data"].iter_rows(values_only=True))
    wb.close()
    header = list(rows[2])
    idx = [header.index(h) for h in ("Sellable (PG)", "Sellable (PDG)", "Non-Sellable (PG)", "Non-Sellable (PDG)")]
    return {str(int(r[0])) if isinstance(r[0], (int, float)) else str(r[0]).strip(): tuple(float(r[i] or 0) for i in idx)
            for r in rows[3:] if r[0] not in (None, "")}


def _data(*codes: str) -> bytes:
    """A Data workbook without stock columns, one SKU per code."""
    headers = [h for h in DEFAULT_HEADERS if h not in ("Total Sellable (Ctns)", "Total Non-Sellable (Ctns)")]
    return make_workbook([[c, "Sup", "X", 12, 0, 6, 7, 0, 5] + [10] * 12 for c in codes], headers=headers)


def _pg(*lines: tuple[str, bool, float], skipped=(), as_of=None) -> StockReport:
    return StockReport(source="PG", lines=[StockLine(code=c, sellable=s, cartons=n) for c, s, n in lines],
                       as_of=as_of, skipped_codes=list(skipped), warnings=[])


def _pdg(*lines: tuple[str, bool, float], as_of=None) -> StockReport:
    return StockReport(source="PDG", lines=[StockLine(code=c, sellable=s, cartons=n) for c, s, n in lines],
                       as_of=as_of, skipped_codes=[], warnings=[])


def test_fixture_reproduces_data_sheet_stock_for_all_212_skus():
    # the Data sheet's own stock columns are the expected values (spec 3.4)
    raw = SAMPLE.read_bytes()
    parsed, stock = apply_stock(parse_input(raw), parse_pg(raw), parse_pdg(raw))
    expected = _data_sheet_stock(raw)
    assert len(parsed.skus) == 212
    for s in parsed.skus:
        assert (s.pg_sellable, s.pdg_sellable, s.pg_non_sellable, s.pdg_non_sellable) == pytest.approx(
            expected[s.sap_code], abs=1e-6)
        assert s.sellable == pytest.approx(s.pg_sellable + s.pdg_sellable)
        assert s.non_sellable == pytest.approx(s.pg_non_sellable + s.pdg_non_sellable)
    assert stock.skus_with_stock == 136
    assert stock.pg.sellable_cartons == pytest.approx(11859.0418, abs=1e-3)
    assert stock.pdg.sellable_cartons == pytest.approx(1638.7426, abs=1e-3)
    by_code = {s.sap_code: s for s in parsed.skus}
    assert by_code["127902330249"].pdg_sellable == pytest.approx(230.3333, abs=1e-3)
    assert by_code["127902330249"].pdg_non_sellable == pytest.approx(0.75)
    assert by_code["3401111006"].pg_sellable == pytest.approx(44.1) and by_code["3401111006"].pg_non_sellable == pytest.approx(1)
    msgs = [w.message for w in stock.warnings]
    assert "PG Expiry Check: 32 stock codes are not in the Data sheet; ignored" in msgs
    assert "PDG Stock List: 8 stock codes are not in the Data sheet; ignored" in msgs


def test_apply_stock_does_not_mutate_its_input():
    parsed = parse_input(_data("A1"))
    apply_stock(parsed, _pg(("A1", True, 4)), _pdg())
    assert parsed.skus[0].sellable == 0 and parsed.skus[0].pg_sellable is None


def test_sku_in_neither_file_has_zero_stock_without_warning():
    parsed, stock = apply_stock(parse_input(_data("A1", "Z9")), _pg(("A1", True, 4)), _pdg())
    z = next(s for s in parsed.skus if s.sap_code == "Z9")
    assert (z.pg_sellable, z.pdg_sellable, z.pg_non_sellable, z.pdg_non_sellable) == (0.0, 0.0, 0.0, 0.0)
    assert z.sellable == 0.0 and z.non_sellable == 0.0
    assert not any(w.sap_code == "Z9" for w in stock.warnings)
    assert stock.skus_with_stock == 1 and stock.pg.skus_with_stock == 1 and stock.pdg.skus_with_stock == 0


def test_same_code_in_both_files_adds_up():
    parsed, stock = apply_stock(parse_input(_data("A1")),
                                _pg(("A1", True, 2), ("A1", False, 0.5)), _pdg(("A1", True, 3), ("A1", False, 1)))
    s = parsed.skus[0]
    assert s.sellable == 5 and s.pg_sellable == 2 and s.pdg_sellable == 3
    assert s.non_sellable == 1.5 and s.pg_non_sellable == 0.5 and s.pdg_non_sellable == 1
    assert stock.skus_with_stock == 1 and stock.pg.skus_with_stock == 1 and stock.pdg.skus_with_stock == 1
    assert stock.pg.sellable_cartons == 2 and stock.pdg.non_sellable_cartons == 1


def test_stock_files_override_data_sheet_stock():
    raw = make_workbook([["A1", "Sup", "X", 12, 0, 6, 7, 999, 0, 0, 5] + [10] * 12])   # old-style Data row
    parsed = parse_input(raw)
    assert parsed.skus[0].sellable == 0
    message = "Stock columns in the Data sheet are ignored; stock comes from the PDG Stock List and PG Expiry Check files."
    assert [w.message for w in parsed.warnings].count(message) == 1
    assert next(w for w in parsed.warnings if w.message == message).sap_code is None
    out, _ = apply_stock(parsed, _pg(("A1", True, 5)), _pdg())
    assert out.skus[0].sellable == 5
    assert [w.message for w in out.warnings].count(message) == 1


def test_report_matching_no_data_sku_warns():
    _, stock = apply_stock(parse_input(_data("A1")), _pg(("OTHER", True, 4)), _pdg(("A1", True, 1)))
    msgs = [w.message for w in stock.warnings]
    assert "PG Expiry Check has no stock for any SKU in the Data sheet — check that it is the right report" in msgs
    assert "PG Expiry Check: 1 stock codes are not in the Data sheet; ignored" in msgs
    assert not any(m.startswith("PDG Stock List") for m in msgs)


def test_not_in_data_count_is_distinct_codes():
    _, stock = apply_stock(parse_input(_data("A1")),
                           _pg(("X", True, 1), ("X", False, 1), ("Y", True, 1), ("A1", True, 1)), _pdg())
    assert "PG Expiry Check: 2 stock codes are not in the Data sheet; ignored" in [w.message for w in stock.warnings]


def test_skipped_rows_and_negative_totals_give_per_sku_warnings():
    _, stock = apply_stock(parse_input(_data("F1")),
                           _pg(("F1", True, -5), ("F1", True, 3), skipped=["F1", "NOTSKU"]), _pdg())
    got = [(w.sap_code, w.column, w.message) for w in stock.warnings if w.sap_code]
    assert ("F1", "Stock", "PG Expiry Check: a stock row for this SKU could not be read and was skipped") in got
    assert ("F1", "Total Sellable", "negative stock — check the stock report") in got
    assert not any(c == "NOTSKU" for c, _, _ in got)


def test_report_warnings_come_first_pg_then_pdg():
    pg = _pg(("A1", True, 1)).model_copy(
        update={"warnings": [ParseWarning(sap_code=None, column=None, message="pg warn")]})
    pdg = _pdg(("A1", True, 1)).model_copy(
        update={"warnings": [ParseWarning(sap_code=None, column=None, message="pdg warn")]})
    _, stock = apply_stock(parse_input(_data("A1")), pg, pdg)
    assert [w.message for w in stock.warnings] == ["pg warn", "pdg warn"]


def test_stock_date_warnings():
    def stock(pg_date, pdg_date):
        return apply_stock(parse_input(_data("A1")), _pg(("A1", True, 1), as_of=pg_date),
                           _pdg(("A1", True, 1), as_of=pdg_date))[1]
    s = stock(date(2026, 10, 12), date(2026, 10, 2))
    assert [w.message for w in stock_date_warnings(s, date(2026, 10, 12))] == [
        "PDG Stock List was printed on 2 Oct 2026, 10 days before the plan date"]
    assert stock_date_warnings(stock(date(2026, 10, 12), date(2026, 10, 12)), date(2026, 10, 15)) == []   # 3 days: ok
    assert len(stock_date_warnings(stock(date(2026, 10, 12), date(2026, 10, 12)), date(2026, 10, 16))) == 2  # 4 days
    s = stock(date(2026, 10, 20), None)   # pdg.as_of None -> no PDG warning
    got = stock_date_warnings(s, date(2026, 10, 12))
    assert [w.message for w in got] == ["PG Expiry Check is as of 20 Oct 2026, 8 days after the plan date"]
    assert got[0].sap_code is None and got[0].column is None
