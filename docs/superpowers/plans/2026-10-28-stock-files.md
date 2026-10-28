# Stock From PDG Stock List and PG Expiry Check — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read stock from two new uploads, the PDG Stock List and PG Expiry Check files, instead of from the Data sheet's stock columns. The order calculation is unchanged.

**Architecture:**
- A new `backend/app/stock.py` parses each stock report into plain `StockLine`s (code, sellable yes/no, cartons). `apply_stock` then totals the lines per Data SKU and fills `SkuInput.sellable`/`non_sellable` plus a PG/PDG breakdown.
- `holding.py` keeps reading only `SkuInput`, so a database source can later produce the same `StockLine`s.
- Runs store the stock file names and a `StockResult` summary. The SQLite schema goes to version 3 with an additive `ALTER TABLE`, so existing v2 runs keep working.
- The frontend gets two more upload slots and shows the PG/PDG split.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, openpyxl, sqlite3, pytest; React 19 + TypeScript, Vite 6, vitest.

**Spec:** `docs/superpowers/specs/2026-10-28-stock-files-design.md`. Read it with `docs/superpowers/specs/2026-10-23-holding-based-order-plan-design.md` (v2).

## Global Constraints

- **The calculation (v2 section 6) does not change.** Available = Total Sellable + SIT. SIT still comes from the Data sheet.
- **PG sellable split:** `Location` = `Sellable` → sellable; `Non-Sellable` → non-sellable; any other value → non-sellable, with a warning. Compare values after `_norm`.
- **PDG sellable split:** `Sell or Non` blank → sellable; `Non` → non-sellable; any other value → non-sellable, with a warning. Compare values after `_norm`.
- **Cartons:** PG = `Ctn`. PDG = `Bin_Qty ÷ U_Ratio`. The `cs` column is not required and not read.
- **Header row:** found within the first 10 rows (`HEADER_SEARCH_ROWS`) of any sheet.
  - PG requires `Item Code`, `Location`, `Ctn`.
  - PDG requires `StockCode`, `Location`, `Bin_Qty`, `U_Ratio`, `Sell or Non`.
- **Error prefixes:** API errors for the new files start with `PG Expiry Check: ` or `PDG Stock List: `. The existing ones start with `Data file: ` or `Sales export: `.
- **Old-date tolerance:** warn when `abs(plan_date − as_of)` is more than 3 days.
- **Never touch `backend/data/orderplan.db` or `orderplan.v1-backup*.db`.** Tests use `tmp_path` or the `ORDERPLAN_DB` set in `conftest.py`.
- **Stop only processes you started, by PID. Never use `taskkill /IM`.**
- **Do not commit `requests/` or `.superpowers/`.**
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **The fixture `backend/tests/fixtures/sample_input.xlsx` is the planner's full workbook**, already committed in v1. It contains `Data`, `PDG Stock List`, `PG Expiry Check` and other sheets. Because sheets are found by headers, the same bytes can be uploaded as the Data file, the PG file and the PDG file. This replaces the spec's "run the 3.4 check once against the planner's file": the check becomes a normal test.

## Review Focus

1. **Stock files in the wrong slot.** PG uploaded as PDG, or the sales export in a stock slot, must return 400 with the right prefix, not a 500 or silently empty stock. Covered by Task 4 `test_swapped_stock_files_return_400`.
2. **Codes stored differently.** PDG `StockCode` is numeric (e.g. `120701330181.0`). PG `Item Code` is text and may have stray spaces. Both must match the Data SAP codes. Covered by Task 1 `test_pdg_numeric_codes_and_trimmed_pg_codes`.
3. **Flag values with different case or spaces** (`"sellable "`, `"NON"`) must still be recognised, not counted as unknown. Covered by Task 1 `test_flag_values_ignore_case_and_spaces`.
4. **An old Data file whose stock columns disagree with the stock files.** The stock files must win. Covered by Task 2 `test_stock_files_override_data_sheet_stock`.
5. **The planner's existing v2 runs after the upgrade** must open, list and recalculate, with `stock` = None and the breakdown = None. Covered by Task 4 `test_v2_database_is_migrated_in_place`.

---

### Task 1: Stock report parsers

**Files:**
- Modify: `backend/app/models.py` (add stock models)
- Modify: `backend/app/parsing.py` (add the shared `find_header_row`)
- Modify: `backend/app/sales.py` (use `find_header_row` instead of its private `_find_header`)
- Create: `backend/app/stock.py`
- Modify: `backend/tests/helpers.py` (add `make_pg_workbook`, `make_pdg_workbook`)
- Create: `backend/tests/test_stock.py`

**Interfaces:**
- Produces, in `models.py`:
  ```python
  StockSource = Literal["PG", "PDG"]

  class StockLine(BaseModel):
      code: str            # normalised like Data SAP codes
      sellable: bool
      cartons: float

  class StockReport(BaseModel):
      source: StockSource
      lines: list[StockLine]
      as_of: date | None           # PDG: Printed_Date; PG: most common (expired Date − Day Left)
      skipped_codes: list[str]     # codes of rows skipped for an unreadable quantity (distinct, in file order)
      warnings: list[ParseWarning] # file-level; every message starts with the report name
  ```
- Produces, in `parsing.py`: `find_header_row(rows: list[tuple], required: list[str]) -> tuple[int, dict[str, int]] | None`. It returns the row index and a map from normalised header to column index, for the first of the first `HEADER_SEARCH_ROWS` rows that has every required header. This is the body of today's `sales._find_header`, with `required` as a parameter. `sales.py` calls it with its own `REQUIRED_COLUMNS`.
- Produces, in `stock.py`:
  - `PG_NAME = "PG Expiry Check"`, `PDG_NAME = "PDG Stock List"`
  - `parse_pg(data: bytes) -> StockReport`
  - `parse_pdg(data: bytes) -> StockReport`
  - Both raise `InputFileError` with these messages (no prefix; `main.py` adds it):
    - `"Could not read the file as an Excel .xlsx workbook."`
    - `"No sheet has Item Code, Location and Ctn columns (looked in the first 10 rows of each sheet)."` for PG, or `"No sheet has StockCode, Location, Bin_Qty, U_Ratio and Sell or Non columns (looked in the first 10 rows of each sheet)."` for PDG
    - `"No data rows under the header row."`

**Warning texts** (`sap_code=None`, `column=None`; `n` is a row count; `{value}` is the original cell text):
- `f"PG Expiry Check: {n} rows have Location '{value}' (not Sellable or Non-Sellable); counted as non-sellable"`
- `f"PDG Stock List: {n} rows have Sell or Non '{value}' (not blank or Non); counted as non-sellable"`
- `f"PG Expiry Check: {n} rows have no readable Ctn; skipped"`
- `f"PDG Stock List: {n} rows have no readable Bin_Qty or U_Ratio; skipped"`. A `U_Ratio` that is 0, blank or non-numeric is unreadable.
- `f"{name}: {n} rows are hidden by a filter; they are still counted"`

**Parsing details:**
- **Rows:** a row with a blank code is skipped silently. These are trailing blank rows and the totals row.
- **Codes:** normalise each code with the same expression the Data parser uses: `str(int(v)) if _is_number(v) else str(v).strip()`.
- **Loading:** open the workbook with `load_workbook(..., read_only=True, data_only=True)` and call `ws.reset_dimensions()`, as `sales.py` does. Full (non-read-only) loading takes about 11 s on the fixture, so don't use it.
- **Hidden rows:** read them from the xlsx zip directly with a private `_hidden_rows(data: bytes, sheet_title: str) -> int`.
  1. Map the sheet title to its part through `xl/workbook.xml` and `xl/_rels/workbook.xml.rels`.
  2. `iterparse` that part.
  3. Count `row` elements whose `hidden` attribute is `"1"` or `"true"`.
  4. Return 0 if anything in the zip can't be read.
- **PDG `as_of`:** in the rows above the header, find a cell whose `_norm` is `printed_date`. The cell directly below it, if it is a date or datetime, gives `as_of` (use the date part). Otherwise `as_of` is None.
- **PG `as_of`:** over rows where `expired Date` is a date or datetime and `Day Left` is a number, take the most common `(expired Date).date() − timedelta(days=Day Left)`. Ties go to the latest date. If no row has both values, `as_of` is None. Columns that are absent from the header just give None.

- [ ] **Step 1: Add the helpers and write the failing tests.**

In `tests/helpers.py`:
- `make_pg_workbook(rows: list[list], headers: list[str] = PG_HEADERS, hidden_rows: tuple[int, ...] = ()) -> bytes`
  - Row 1 is a totals row with a number in the `Ctn` column.
  - Row 2 holds the headers. Data starts at row 3.
  - `hidden_rows` lists sheet row numbers to set `ws.row_dimensions[r].hidden = True`.
  - `PG_HEADERS = ["Item Code", "Whs Code", "Location", "SOH", "UOM", "Ctn", "expired Date", "Day Left"]`.
- `make_pdg_workbook(rows: list[list], headers: list[str] = PDG_HEADERS, printed: datetime | None = datetime(2026, 10, 12, 6, 45)) -> bytes`
  - Row 1 is `["Printed_Date", "Item_Code"]` and row 2 is `[printed, "ALL To ALL"]`. Row 3 is blank.
  - Row 4 holds the headers. Data starts at row 5.
  - `PDG_HEADERS = ["StockCode", "Description", "Location", "Sell or Non", "U_Ratio", "Bin_Qty", "cs"]`.

In `tests/test_stock.py`, using `SAMPLE = fixtures/sample_input.xlsx`:

```python
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
```

- [ ] **Step 2: Run the tests and check they fail.**
Run from `backend/`: `.venv/Scripts/python -m pytest tests/test_stock.py -q`
Expected: collection error (`app.stock` does not exist).

- [ ] **Step 3: Implement the code.**
Add the models. Add `find_header_row` and switch `sales.py` to it. Write `stock.py` with `parse_pg`, `parse_pdg`, `_hidden_rows`, and one shared private routine for finding the sheet and rows. Both parsers differ only in their required headers, quantity rule, flag rule and `as_of` rule.

- [ ] **Step 4: Run the full backend suite and check it passes.**
Run from `backend/`: `.venv/Scripts/python -m pytest -q`
Expected: all pass. `test_sales.py` must be unchanged and still green after the `find_header_row` refactor.

- [ ] **Step 5: Commit.**
```bash
git add backend/app/models.py backend/app/parsing.py backend/app/sales.py backend/app/stock.py backend/tests/helpers.py backend/tests/test_stock.py
git commit -m "feat: parse PDG Stock List and PG Expiry Check into stock lines"
```

---

### Task 2: Stock totals per SKU, and the Data sheet without stock columns

**Files:**
- Modify: `backend/app/models.py` (`SkuInput` breakdown, `StockFileSummary`, `StockResult`)
- Modify: `backend/app/parsing.py` (stock columns optional)
- Modify: `backend/app/stock.py` (`apply_stock`, `stock_date_warnings`)
- Modify: `backend/tests/test_parsing.py`, `backend/tests/test_stock.py`

**Interfaces:**
- Consumes: `StockReport`, `parse_pg`, `parse_pdg`, `PG_NAME`, `PDG_NAME` (Task 1).
- Produces, in `models.py`:
  ```python
  class SkuInput(BaseModel):               # existing fields unchanged, plus:
      pg_sellable: float | None = None     # None only in runs saved before this change
      pdg_sellable: float | None = None
      pg_non_sellable: float | None = None
      pdg_non_sellable: float | None = None

  class StockFileSummary(BaseModel):
      source: StockSource
      as_of: date | None
      skus_with_stock: int         # Data SKUs with at least one line in this file
      sellable_cartons: float      # summed over Data SKUs only
      non_sellable_cartons: float

  class StockResult(BaseModel):
      pg: StockFileSummary
      pdg: StockFileSummary
      skus_with_stock: int         # Data SKUs with a line in either file
      warnings: list[ParseWarning] # report warnings (PG then PDG), then merge warnings
  ```
- Produces, in `stock.py`:
  - `apply_stock(parsed: ParsedInput, pg: StockReport, pdg: StockReport) -> tuple[ParsedInput, StockResult]`. It returns a copy of `parsed` whose SKUs have:
    - `sellable = pg_sellable + pdg_sellable` and `non_sellable = pg_non_sellable + pdg_non_sellable`;
    - all four breakdown fields set, with 0.0 when the SKU has no lines.
  - `stock_date_warnings(stock: StockResult, plan_date: date) -> list[ParseWarning]`
- `parse_input` now returns SKUs with `sellable = non_sellable = 0.0` and the breakdown fields None. Only `apply_stock` fills stock.

**Merge warnings** (`sap_code=None` unless stated):
- `f"{name}: {n} stock codes are not in the Data sheet; ignored"`: distinct codes, one warning per file, only when n > 0.
- `f"{name} has no stock for any SKU in the Data sheet — check that it is the right report"`: when the report's lines match no Data SKU.
- Per Data SKU in `report.skipped_codes`: `sap_code=code`, `column="Stock"`, `message=f"{name}: a stock row for this SKU could not be read and was skipped"`.
- Per SKU whose total sellable is below 0: `sap_code=code`, `column="Total Sellable"`, `message="negative stock — check the stock report"`. This text is the same as v2's.

**Date warnings:** for each file with `as_of`, when `abs((plan_date − as_of).days) > 3`:
- PDG: `f"PDG Stock List was printed on {d}, {n} days {before|after} the plan date"`
- PG: `f"PG Expiry Check is as of {d}, {n} days {before|after} the plan date"`
- `d` is written like `2 Oct 2026`: day without a leading zero, the fixed English month abbreviation used by `months.month_label`, then the year.

**Data sheet changes in `parse_input`:**
- `REQUIRED_COLUMNS` no longer includes `Total Sellable (Ctns)` or `Total Non-Sellable (Ctns)`.
- `STOCK_COLUMNS = ["Sellable (PG)", "Sellable (PDG)", "Total Sellable (Ctns)", "Non-Sellable (PG)", "Non-Sellable (PDG)", "Total Non-Sellable (Ctns)"]`. If any of these is present, add one warning with `sap_code=None`, `column=None` and the message `"Stock columns in the Data sheet are ignored; stock comes from the PDG Stock List and PG Expiry Check files."` These columns are never read.
- The negative-SIT warning stays. The negative-sellable warning moves to `apply_stock`.

- [ ] **Step 1: Write the failing tests.**

In `test_stock.py`:

```python
def test_fixture_reproduces_data_sheet_stock_for_all_212_skus():
    # the Data sheet's own stock columns are the expected values (spec 3.4)
    raw = SAMPLE.read_bytes()
    parsed, stock = apply_stock(parse_input(raw), parse_pg(raw), parse_pdg(raw))
    expected = _data_sheet_stock(raw)   # test helper: SAP code -> (Sellable PG, Sellable PDG, Non PG, Non PDG), read with openpyxl from the Data sheet (header row 3)
    assert len(parsed.skus) == 212
    for s in parsed.skus:
        assert (s.pg_sellable, s.pdg_sellable, s.pg_non_sellable, s.pdg_non_sellable) == pytest.approx(expected[s.sap_code], abs=1e-6)
        assert s.sellable == pytest.approx(s.pg_sellable + s.pdg_sellable)
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

def test_sku_in_neither_file_has_zero_stock_without_warning(): ...
    # Data SKU "Z9" absent from both reports -> all four fields 0.0, sellable 0.0, no warning with sap_code "Z9"

def test_same_code_in_both_files_adds_up(): ...
    # PG sellable 2 + PDG sellable 3 for one code -> sellable 5, pg_sellable 2, pdg_sellable 3

def test_stock_files_override_data_sheet_stock():
    # old-style Data row (DEFAULT_HEADERS) with Total Sellable 999; PG gives 5 cartons
    # -> sellable == 5 and parsed.warnings contains the "Stock columns in the Data sheet are ignored..." message once

def test_report_matching_no_data_sku_warns(): ...
    # PG lines only for code "OTHER" -> message "PG Expiry Check has no stock for any SKU in the Data sheet — check that it is the right report"

def test_skipped_rows_and_negative_totals_give_per_sku_warnings(): ...
    # skipped_codes ["F1"] -> (sap_code "F1", column "Stock", "PG Expiry Check: a stock row for this SKU could not be read and was skipped")
    # PG lines summing to -2 for F1 -> (sap_code "F1", column "Total Sellable", "negative stock — check the stock report")

def test_stock_date_warnings():
    # pg.as_of 2026-10-12, pdg.as_of 2026-10-02, plan 2026-10-12 ->
    # ["PDG Stock List was printed on 2 Oct 2026, 10 days before the plan date"]
    # plan 2026-10-15 -> []   (3 days is within tolerance)
    # pg.as_of None -> no PG warning
```

In `test_parsing.py`:
- Add `test_data_sheet_without_stock_columns_parses`: headers = `DEFAULT_HEADERS` minus the two totals, rows shortened to match. It parses with no stock warning and `sellable == 0`.
- Update the tests that asserted `sellable`/`non_sellable` from the Data sheet. These are at lines 22, 55–56, 94, 103 and 188–190 today. Drop the sellable asserts, which now live in `test_stock.py`, and keep their SIT/MTD/other asserts.
- In `test_negative_stock…` (line 188), keep only the SIT warning.

- [ ] **Step 2: Run the tests and check they fail.**
Run from `backend/`: `.venv/Scripts/python -m pytest tests/test_stock.py tests/test_parsing.py -q`
Expected: FAIL (`apply_stock` is not defined; the Data sheet still requires the totals).

- [ ] **Step 3: Implement the code.**
Add the model fields and `apply_stock`/`stock_date_warnings`, and change `parse_input` as above. `apply_stock` uses `parsed.model_copy(update=...)` and must not mutate its inputs.

- [ ] **Step 4: Run the stock and parsing tests and check they pass.**
Run from `backend/`: `.venv/Scripts/python -m pytest tests/test_stock.py tests/test_parsing.py -q`
Expected: PASS. Other suites may fail until Task 4 wires stock into the API: `test_api.py` still sends two files and gets sellable 0. Don't fix them here.

- [ ] **Step 5: Commit.**
```bash
git add backend/app/models.py backend/app/parsing.py backend/app/stock.py backend/tests/test_stock.py backend/tests/test_parsing.py
git commit -m "feat: total stock per SKU from the stock reports; Data sheet stock columns optional"
```

---

### Task 3: Breakdown in results and in the Excel export

**Files:**
- Modify: `backend/app/models.py` (`SkuResult` breakdown)
- Modify: `backend/app/holding.py` (`plan_sku` copies the breakdown)
- Modify: `backend/app/export.py`
- Modify: `backend/tests/test_holding.py`, `backend/tests/test_export.py`

**Interfaces:**
- Consumes: the `SkuInput` breakdown fields and `StockResult` (Task 2).
- Produces:
  - `SkuResult` gains `pg_sellable`, `pdg_sellable`, `pg_non_sellable`, `pdg_non_sellable`, each `float | None = None`, copied unchanged from `SkuInput`.
  - `RunRecord` gains `stock: StockResult | None = None`, defined here so the export can read it. Task 4 stores it.
- **Export, SKU Plan sheet:** the stock columns, in this order, are `Sellable`, `PG Sellable`, `PDG Sellable`, `SIT`, `Available`, `PG Non-Sellable`, `PDG Non-Sellable`.
  - The four new columns use the `0.00` format and are blank when None.
  - Every other column keeps its order.
- **Export, Warnings sheet:** `run.stock.warnings` rows are added after the sales export rows, with Source `"Stock files"`. There are none when `run.stock` is None.

- [ ] **Step 1: Write the failing tests.**
  - `test_holding.py::test_breakdown_is_copied_to_result`: a `SkuInput` with `pg_sellable=150, pdg_sellable=50` → the `SkuResult` has the same values and `sellable` unchanged at 200.
  - `test_export.py`: update the SKU Plan header assertion at line 49 to the new order above. Add `test_export_stock_columns_and_warnings`: a run with breakdown values and a `StockResult` holding one warning. The PG Sellable cell has the value and format `0.00`, and the Warnings sheet has a row whose Source is `Stock files`. A run with `stock=None` and None breakdown gives blank cells and no extra rows.

- [ ] **Step 2: Run the tests and check they fail.**
Run from `backend/`: `.venv/Scripts/python -m pytest tests/test_holding.py tests/test_export.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the model fields, the `plan_sku` copy and the export columns.**

- [ ] **Step 4: Run the tests and check they pass.**
Run from `backend/`: `.venv/Scripts/python -m pytest tests/test_holding.py tests/test_export.py -q`
Expected: PASS.

- [ ] **Step 5: Commit.**
```bash
git add backend/app/models.py backend/app/holding.py backend/app/export.py backend/tests/test_holding.py backend/tests/test_export.py
git commit -m "feat: PG/PDG stock breakdown in SKU results and the Excel export"
```

---

### Task 4: Storage migration and the four-file API

**Files:**
- Modify: `backend/app/db.py`, `backend/app/repository.py`, `backend/app/main.py`, `backend/app/models.py`
- Modify: `backend/tests/test_api.py`, `backend/tests/test_repository.py`

**Interfaces:**
- Consumes: `parse_pg`, `parse_pdg`, `apply_stock`, `stock_date_warnings`, `PG_NAME`, `PDG_NAME`, `StockResult` and `RunRecord.stock`.
- **Models:**
  - `RunListItem` gains `pg_file_name: str | None = None` and `pdg_file_name: str | None = None`.
  - `InspectResponse` gains `pg_file_name: str`, `pdg_file_name: str` and `stock: StockResult`.
  - `InspectResponse.warnings` = Data warnings + sales warnings + `stock.warnings` + date warnings at `default_plan_date`.
- **DB:**
  - `SCHEMA_VERSION = 3`.
  - In `SCHEMA`, the `runs` table gains `pg_file_name TEXT NULL`, `pdg_file_name TEXT NULL` and `stock_json TEXT NULL`.
  - `init_schema` adds any of these three columns that are missing, with `ALTER TABLE runs ADD COLUMN …` (read `PRAGMA table_info(runs)` first), before setting `user_version`.
  - The v1 backup logic is unchanged. A v2 DB (user_version 2, no `reorder_days`) must **not** be renamed.
- **Repository:**
  - `create_run(file_name: str, sales_file_name: str, pg_file_name: str, pdg_file_name: str, parsed: ParsedInput, actual: ActualSales, stock: StockResult, result: HoldingPlan) -> int`
  - `get_run` fills `stock` from `stock_json`, or None if it is NULL.
  - `list_runs` returns the two file names.
- **API:**
  - `POST /api/inspect` and `POST /api/runs` take four multipart files: `data_file`, `sales_file`, `pg_file`, `pdg_file`.
  - Parse them in that order. `InputFileError` gives a 400 with the prefix `Data file: `, `Sales export: `, `PG Expiry Check: ` or `PDG Stock List: `.
  - `parsed` passes through `apply_stock` before `plan_all`.
  - `POST /api/runs` appends `stock_date_warnings(stock, chosen_plan_date)` to `stock.warnings` before storing.
  - Recalculate reuses the stored `parsed` and `stock` and reads no files. That is today's behaviour; keep it.

- [ ] **Step 1: Write the failing tests.**

In `test_api.py`:
- Change `files()` to `files(data=DATA, sales=SALES, pg=DATA, pdg=DATA)`, sending `pg_file` as `("pg.xlsx", pg)` and `pdg_file` as `("pdg.xlsx", pdg)`. The fixture workbook carries both stock sheets.
- The existing assertions must still pass, including `available == pytest.approx(38.15)` for 3102111001: 22.15 PG sellable + 16 SIT, now from the stock files.

New tests:

```python
def test_inspect_reports_stock(client):
    r = client.post("/api/inspect", files=files()).json()
    assert r["pg_file_name"] == "pg.xlsx" and r["pdg_file_name"] == "pdg.xlsx"
    assert r["stock"]["skus_with_stock"] == 136
    assert r["stock"]["pg"]["as_of"] == "2026-10-12" and r["stock"]["pdg"]["as_of"] == "2026-10-12"
    assert any(w["message"].startswith("Stock columns in the Data sheet are ignored") for w in r["warnings"])

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
```

In `test_repository.py`:

```python
def test_v2_database_is_migrated_in_place(tmp_path):
    # Build a v2 DB by hand: the v2 SCHEMA text (copied literally into the test, user_version 2),
    # one supplier_settings row and one runs row whose parsed_json/result_json were dumped from
    # current models with the four breakdown keys removed from every sku, and no stock columns.
    repo = Repository(tmp_path / "v2.db")
    assert (tmp_path / "v2.db").exists() and not list(tmp_path.glob("orderplan.v1-backup*.db"))
    run = repo.get_run(1)
    assert run.stock is None and run.parsed.skus[0].pg_sellable is None and run.result.skus[0].pg_sellable is None
    assert repo.list_runs()[0].pg_file_name is None and repo.get_holdings() == {"CFC": 2.0}
    # user_version is now 3; a second Repository() on the same file changes nothing
    rec = TestClient(create_app(tmp_path / "v2.db")).post("/api/runs/1/recalculate")
    assert rec.status_code == 200 and rec.json()["stock"] is None
```

- [ ] **Step 2: Run the tests and check they fail.**
Run from `backend/`: `.venv/Scripts/python -m pytest tests/test_api.py tests/test_repository.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the DB migration, the repository changes and the API wiring.**
Use a helper in `main.py`, `_parse_uploads(data_file, sales_file, pg_file, pdg_file) -> tuple[ParsedInput, ActualSales, StockResult]`.

- [ ] **Step 4: Run the full backend suite and check it passes.**
Run from `backend/`: `.venv/Scripts/python -m pytest -q`
Expected: all pass. `test_isolation.py` must still show the real DB untouched.

- [ ] **Step 5: Commit.**
```bash
git add backend/app/db.py backend/app/repository.py backend/app/main.py backend/app/models.py backend/tests/test_api.py backend/tests/test_repository.py
git commit -m "feat: four-file upload API; store stock per run; migrate v2 database in place"
```

---

### Task 5: Upload page with four files

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/pages/UploadPage.tsx`

**Interfaces:**
- Consumes: the API shapes from Task 4.
- **`types.ts`:**
  - Mirror the new fields: `SkuInput` and `SkuResult` breakdown (`number | null`), `StockFileSummary`, `StockResult`, `InspectResponse.pg_file_name/pdg_file_name/stock`, `RunListItem.pg_file_name/pdg_file_name` (`string | null`) and `RunRecord.stock` (`StockResult | null`).
  - `StockSource = 'PG' | 'PDG'`.
- **`api.ts`:**
  - `export interface UploadFiles { data: File; sales: File; pg: File; pdg: File }`
  - `inspectFiles(files: UploadFiles): Promise<InspectResponse>`
  - `createRun(files: UploadFiles, planDate?: string): Promise<RunRecord>`
  - Form field names: `data_file`, `sales_file`, `pg_file`, `pdg_file`.
- **`UploadPage`:**
  - Four inputs with ids `data-file`, `sales-file`, `pg-file`, `pdg-file` and labels `Data file (.xlsx)`, `Sales export (.xlsx)`, `PG Expiry Check (.xlsx)`, `PDG Stock List (.xlsx)`.
  - Inspect runs when all four are chosen. Keep the existing cleanup-flag pattern.
  - Intro text: `Choose the Data file (only the Data sheet is read), the sales export, and the two stock reports.`
  - Facts added:
    - `SKUs with stock`: `{stock.skus_with_stock} of {sku_count}`
    - `PG sellable`: `{fmtQty(stock.pg.sellable_cartons)} cartons`, plus ` · as of {fmtDate(as_of)}` when present
    - `PDG sellable`: the same, with ` · printed {fmtDate(as_of)}`
  - The heading lists all four file names, separated by ` + `.

- [ ] **Step 1: Make the type and API changes, and update the page.**

- [ ] **Step 2: Type-check, build and run the frontend tests.**
Run: `npm --prefix frontend run build` then `npm --prefix frontend test`
Expected: the build succeeds with no TS errors, and the existing 33 tests pass.

- [ ] **Step 3: Commit.**
```bash
git add frontend/src/types.ts frontend/src/api.ts frontend/src/pages/UploadPage.tsx
git commit -m "feat: upload page takes PG Expiry Check and PDG Stock List files"
```

---

### Task 6: Stock in the plan page, the SKU detail and history

**Files:**
- Modify: `frontend/src/lib/format.ts`, `frontend/src/lib/format.test.ts`
- Modify: `frontend/src/lib/warnings.ts`, `frontend/src/lib/warnings.test.ts`
- Modify: `frontend/src/components/WarningsPanel.tsx`, `frontend/src/components/SkuDetail.tsx`
- Modify: `frontend/src/pages/PlanPage.tsx`, `frontend/src/pages/HistoryPage.tsx`

**Interfaces:**
- Consumes: the types from Task 5.
- **`orderExplanation`:** when `r.pg_sellable !== null && r.pdg_sellable !== null`, the Available line is `` `Available = ${fmtExact(pg)} PG sellable + ${fmtExact(pdg)} PDG sellable + ${fmtExact(r.sit)} SIT = ${fmtExact(r.available)}` ``. Otherwise it is today's line, for old runs.
- **`groupWarnings`:** becomes `groupWarnings(dataWarnings: ParseWarning[], salesWarnings: ParseWarning[], stockWarnings: ParseWarning[] = [])`, with `WarningSource` gaining `'Stock files'`. Stock warnings come last.
- **`WarningsPanel`:** gains the prop `stockWarnings: ParseWarning[]`. `PlanPage` passes `run.stock?.warnings ?? []`.
- **`PlanPage` header:** after `{run.file_name} + {run.sales_file_name}`, append ` + {pg_file_name} + {pdg_file_name}` when both are non-null.
- **`SkuDetail`:** adds a `Non-sellable` fact, `PG {fmtExact} · PDG {fmtExact}`, only when both non-sellable breakdown fields are non-null. The SKU detail's per-SKU warnings must include stock warnings for that SAP code. Find where `PlanPage` builds them and add `run.stock?.warnings`.
- **`HistoryPage`:** two more columns, `PG Expiry Check` and `PDG Stock List`, showing the file name or `—`.

- [ ] **Step 1: Write the failing tests.**
  - `format.test.ts`: add a case where `pg_sellable: 150, pdg_sellable: 50` (with sellable 200 and SIT 60) gives `'Available = 150 PG sellable + 50 PDG sellable + 60 SIT = 260'`.
    - The existing cases set the breakdown to `null` and keep their old expected line.
    - Add the four new fields (as `null`) to the shared fixture object.
  - `warnings.test.ts`: a stock warning with `sap_code: null` lands in `fileLevel` with source `'Stock files'`, after the data and sales ones. Calling with two arguments still works.

- [ ] **Step 2: Run the tests and check they fail.**
Run: `npm --prefix frontend test`
Expected: FAIL on the new cases.

- [ ] **Step 3: Implement the changes listed above.**

- [ ] **Step 4: Run the tests and the build, and check they pass.**
Run: `npm --prefix frontend test` then `npm --prefix frontend run build` then `npm --prefix frontend run lint`
Expected: all pass with no lint errors.

- [ ] **Step 5: Commit.**
```bash
git add frontend/src
git commit -m "feat: show PG/PDG stock in the plan, SKU detail, warnings and history"
```

---

### Task 7: README and end-to-end check

**Files:**
- Modify: `README.md`
- Modify: `.claude/launch.json` (add the test servers)
- Modify: `frontend/vite.config.ts` (the proxy target can come from the environment)

**Interfaces:** none new. In `vite.config.ts`, the `/api` proxy target becomes `process.env.ORDERPLAN_API ?? 'http://127.0.0.1:8000'`, so the default is unchanged.

- [ ] **Step 1: Update `README.md`.**
  - **Uploads:** there are four files. Say what each stock report is, which columns are read, and the sellable rules (PG `Location`; PDG `Sell or Non`; `WH Code info` is not used).
  - **Data sheet:** the stock columns are no longer needed.
  - **Warnings:** add the new warnings.
  - **Upgrade:** the existing database is upgraded in place on first start, and old runs show "—" for the PG/PDG split.
  - **Limitations:** add "near-expiry stock still counts as available".

- [ ] **Step 2: Add test servers to `.claude/launch.json`.**
  - **`backend-test`:** the same command as `backend`, but `--port 8001` and `"env": { "ORDERPLAN_DB": "<absolute scratchpad path>/v3-check.db" }`.
  - **`frontend-test`:** `npm --prefix frontend run dev -- --port 5174` with `"env": { "ORDERPLAN_API": "http://127.0.0.1:8001" }`, port 5174.
  - Don't change the planner's `backend`/`frontend` entries. Their servers may be running on 8000/5173 against the real DB; leave them alone.
  - Start both test servers with `preview_start`. Before using the test backend, confirm it is on the temp DB: `GET http://127.0.0.1:8001/api/runs` must return `[]`, and `v3-check.db` must exist in the scratchpad. If `env` is not honoured, stop and report. Don't fall back to the real DB.

- [ ] **Step 3: Check against the planner's real file.**
Using the test backend (never the real DB), `POST /api/runs` with the planner's workbook from `C:\Users\linnyiaung\Downloads\Local Principals data for Demand Forecasting Tool.xlsx` as the data, PG and PDG files, plus `backend/tests/fixtures/sales_export.xlsx`. Read that path only; don't copy it into the repo.
Expected:
  - 212 SKUs, `stock.skus_with_stock == 136`;
  - every SKU's four breakdown values equal the Data sheet's stock columns;
  - the run's counts are identical to a v2 run made from the same files before this change. Compute that baseline first with `git stash` or a checkout of `cf1e6b0` in a temp worktree, against a temp DB.

- [ ] **Step 4: Click through the browser at `http://localhost:5174` (the test frontend).**
Check that:
  - the upload page has four pickers and shows the stock facts;
  - the plan header lists the four files;
  - the SKU detail for `127902330249` shows `230.3333 PDG sellable` and Non-sellable `PG 0 · PDG 0.75`;
  - History shows the stock file names.
Then stop only the servers you started, by PID.

- [ ] **Step 5: Run the full verification.**
Run from `backend/`: `.venv/Scripts/python -m pytest -q`; then `npm --prefix frontend test`; then `npm --prefix frontend run build`.
Expected: all green. Confirm that the real `backend/data/orderplan.db` modification time is unchanged.

- [ ] **Step 6: Commit.**
```bash
git add README.md .claude/launch.json frontend/vite.config.ts
git commit -m "docs: README for stock report uploads; test server launch entries"
```

- [ ] **Step 7: Tell the planner about the upgrade, then wait.**
Their running backend still has the old code. Restarting it upgrades `backend/data/orderplan.db` to schema 3 in place. Offer to copy it first to `backend/data/orderplan.pre-v3-backup.db`, and restart only when they say so.
