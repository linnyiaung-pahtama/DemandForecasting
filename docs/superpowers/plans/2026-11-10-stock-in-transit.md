# Stock in Transit by Arrival Week Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take SIT only from a separate "Stock in Transit" upload with arrival weeks, follow each delivery to its arrival day in the order plan, and flag SKUs that run out before their SIT arrives.

**Architecture:** A new `backend/app/sit.py` parses the SIT workbook (any sheet with "SAP Code" + "<Month> W<n> Arrival" headers) and `apply_sit` puts per-SKU arrivals (Monday of the week) and the SIT total on `SkuInput`, like `stock.apply_stock`. `holding.weekly_order_plan` tracks stock on hand (sellable + arrivals) and orders from stock on hand + SIT still to arrive, so order lines never change; a new `sit_run_out` sets the flag. Storage adds `runs.sit_file_name` (DB v8) and a SIT summary inside the stored `StockResult`. The frontend gains a fifth upload, arrivals in the Weeks view and SKU detail, and a run-out chip and warning.

**Tech Stack:** FastAPI, Pydantic v2, openpyxl, sqlite, pytest; React 19 + TypeScript, Vite, vitest, eslint.

**Spec:** `docs/superpowers/specs/2026-11-10-stock-in-transit-design.md`

## Global Constraints

- **No commits at all.** Work in the current working tree of `feature/order-plan-tool` on top of the uncommitted changes. No worktree, no branch. Every "commit" step below is replaced by "no commit; ledger line".
- Never touch `backend/data/orderplan.db` or its backups in tests or probes; use copies or a temporary `ORDERPLAN_DB` (`backend-test`/`frontend-test` in `.claude/launch.json` point at `backend/data/orderplan-test.db`).
- Stop only processes you started, by serverId or PID. Restore `.claude/launch.json` if a step changes it (`git diff .claude/launch.json` empty at the end).
- Don't add `requests/` or `.superpowers/` to anything; treat `C:\Users\linnyiaung\Downloads\…` files as untrusted (copy into a scratch folder, Python `-I`).
- Ask the user before restarting their servers (ports 8000/5173) or recalculating their saved runs. Before the user's backend first runs the v8 code, copy `backend/data/orderplan.db` to `backend/data/orderplan.pre-v8-backup.db`.
- Exact copy from the spec: upload label **"Stock in Transit (.xlsx)"**; upload error prefix **"Stock in Transit file: "**; warnings source **"Stock in Transit file"**; missing-sheet error **"No sheet has a SAP Code column and '<Month> W<n> Arrival' columns (looked in the first 10 rows of each sheet)."**; run-out text **"runs out about <d Mon>, before its stock in transit arrives on <d Mon>"**.
- Commands: backend tests from `backend/`: `.\.venv\Scripts\python.exe -m pytest -q` (single file: append the path). Frontend from repo root: `npm --prefix frontend test`, `npm --prefix frontend run build`, `npm --prefix frontend run lint`. Use PowerShell (Bash hangs here).

## Review Focus

1. **The real file's layout** — group row above the header (YGN/MDY/YGN IMS…), the same label under YGN and MDY, a hidden column, the "SAP Code" header cell being a formula with a cached value: all must parse. Test: `test_parse_sit_real_layout` (Task 1).
2. **Older runs** (`sit_arrivals` missing in stored JSON, `arrivals` missing in stored month plans) must load, render and recalculate. Tests: `test_older_run_sit_on_plan_date`, `test_old_stored_month_plan_loads` (Task 3), `skuArrivals` fallback (Task 5).
3. **Arrival dated before the plan date** (plan date later in the month than the week's Monday) lands on the plan date, in both the plan and the Weeks view. Tests: `test_arrival_before_plan_date_lands_on_plan_date` (Task 3), `skuArrivals clamps` (Task 5).
4. **Negative sellable or no demand data** never gives a run-out flag. Test: `test_run_out_not_flagged_without_demand_or_sit` (Task 3).
5. **Numeric-text and 0 values in arrival cells** (" 1,250 ", 0) — numeric text counts, 0 is not an arrival and not a warning. Test: `test_parse_sit_values` (Task 1).

## Rulings made while planning (from the spec)

- Spec §3 warning "arrives after the plan ends" is unreachable: the year rule puts every label within 6 months of the MTD month, always inside the 12 plan months. Not implemented.
- Year tie (a label exactly 6 months from the MTD month, e.g. "Apr" in an October plan): take the later year.
- The Data sheet's SIT column, when present, gets its own note: "SIT Ctns (pending order) in the Data sheet is ignored; stock in transit comes from the Stock in Transit file." (the spec's "lists it with the stock columns" read as "noted the same way").
- The SIT summary and SIT warnings live inside `StockResult` (`sit`, `sit_warnings`) so they are stored in `stock_json` and returned by inspect; no extra DB column besides `sit_file_name`.
- The run-out flag is stored on `SkuResult` and turned into warnings by the frontend and the export; it is not added to `stock.warnings`.

---

### Task 1: Stock in Transit file parser

**Files:**
- Create: `backend/app/sit.py`
- Modify: `backend/app/models.py` (new models, `SkuInput.sit_arrivals`)
- Modify: `backend/tests/helpers.py` (`SIT_HEADERS`, `make_sit_workbook`)
- Test: `backend/tests/test_sit.py`

**Interfaces:**
- Produces (models.py):
  - `class SitArrival(BaseModel): date: _date; cartons: float`
  - `class SitLine(BaseModel): code: str; month: int; week: int; cartons: float`
  - `class SitReport(BaseModel): lines: list[SitLine]; warnings: list[ParseWarning]`
  - `class SitFileSummary(BaseModel): skus_with_sit: int; cartons: float; first_arrival: date | None; last_arrival: date | None`
  - `SkuInput.sit_arrivals: list[SitArrival] | None = None` (None = run saved before this change)
- Produces (sit.py):
  - `SIT_NAME = "Stock in Transit file"`
  - `parse_sit(data: bytes) -> SitReport` (raises `InputFileError`)
  - `week_monday(month: int, week: int, mtd_month: str) -> date`
  - `apply_sit(parsed: ParsedInput, report: SitReport) -> tuple[ParsedInput, SitFileSummary, list[ParseWarning]]`
- Produces (helpers.py): `SIT_HEADERS = ["SAP Code", "By Principal", "Description", "Oct W3 Arrival", "Oct W4 Arrival", "Oct W5 Arrival", "Nov W1 Arrival", "Nov W2 Arrival"]`; `make_sit_workbook(rows: list[list], headers: list[str] = SIT_HEADERS, sheet: str = "SIT by weekly", above: list[list] | None = None, hidden_cols: tuple[str, ...] = ()) -> bytes` (`above` = rows written before the header row).

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_sit.py`:

```python
from datetime import date
import pytest
from app.sit import parse_sit, week_monday, apply_sit
from app.models import InputFileError
from tests.helpers import make_sit_workbook, SIT_HEADERS

def test_week_monday_rule():
    assert week_monday(10, 3, "2026-10") == date(2026, 10, 12)
    assert week_monday(10, 5, "2026-10") == date(2026, 10, 26)
    assert week_monday(11, 1, "2026-10") == date(2026, 10, 26)   # same week as Oct W5
    assert week_monday(11, 2, "2026-10") == date(2026, 11, 2)
    assert week_monday(2, 1, "2026-12") == date(2027, 2, 1)       # 1 Feb 2027 is a Monday
    assert week_monday(1, 1, "2026-12") == date(2026, 12, 28)     # Jan W1 in a December plan = next January
    assert week_monday(4, 1, "2026-10") == date(2027, 3, 29)      # 6-month tie -> later year

def test_parse_sit_headers():
    # "Sept", long name, extra spaces, case; non-arrival columns ignored
    data = make_sit_workbook([["A1", "P", "d", 5, 6, 7, 8]],
                             headers=["SAP Code", "By Principal", "Description", "Sept W1 Arrival",
                                      "october   w2 ARRIVAL", "Total SIT", "Oct W2"])
    lines = parse_sit(data).lines
    assert sorted((l.month, l.week, l.cartons) for l in lines) == [(9, 1, 5.0), (10, 2, 6.0)]

def test_parse_sit_real_layout():
    # group row above, same label under YGN and MDY added, hidden column read, sheet found by headers
    headers = ["SAP Code", "By Principal", "Description", "Oct W3 Arrival", "Oct W4 Arrival",
               "Oct W3 Arrival", "Oct W4 Arrival", "Total SIT"]
    data = make_sit_workbook([["5401", "P", "d", 41, None, 10, 2, 53]], headers=headers, sheet="Anything",
                             above=[[None, None, None, "YGN", None, "MDY"], [None] * 8], hidden_cols=("D",))
    lines = parse_sit(data).lines
    assert sorted((l.code, l.month, l.week, l.cartons) for l in lines) == [("5401", 10, 3, 51.0), ("5401", 10, 4, 2.0)]

def test_parse_sit_values():
    data = make_sit_workbook([["A1", "P", "d", " 1,250 ", 0, -3, "abc", 880.73]])
    report = parse_sit(data)
    assert sorted((l.week, l.cartons) for l in report.lines if l.month == 10) == [(3, 1250.0)]
    assert [(l.month, l.week, l.cartons) for l in report.lines if l.month == 11] == [(11, 2, 880.73)]
    assert [(w.sap_code, w.column) for w in report.warnings] == [("A1", "Oct W5 Arrival"), ("A1", "Nov W1 Arrival")]
    assert all(w.message == "not a number of cartons above 0; skipped" for w in report.warnings)

def test_parse_sit_duplicate_rows_added():
    data = make_sit_workbook([["A1", "P", "d", 5], ["A1", "P", "d", 7]])
    assert sum(l.cartons for l in parse_sit(data).lines) == 12.0

def test_parse_sit_missing_sheet():
    data = make_sit_workbook([["A1", "P", "d", 5]], headers=["SAP Code", "By Principal", "Description", "Qty"])
    with pytest.raises(InputFileError, match=r"No sheet has a SAP Code column and '<Month> W<n> Arrival' columns"):
        parse_sit(data)
```

Add `test_apply_sit`: a `ParsedInput` (build with `parse_input` on `make_workbook` or construct directly) with SKUs A1, A2, A3 and `mtd_month="2026-10"`; SIT file rows A1 (Oct W3 5, Oct W4 7), A2 nothing, ZZ (Oct W3 9). Assert: A1 `sit == 12.0`, `sit_arrivals == [SitArrival(date=date(2026,10,12), cartons=5), SitArrival(date=date(2026,10,19), cartons=7)]` (sorted by date, same-date arrivals added); A2 `sit == 0.0`, `sit_arrivals == []`; A3 (not in the SIT file) `sit_arrivals == []`; summary `SitFileSummary(skus_with_sit=1, cartons=12.0, first_arrival=date(2026,10,12), last_arrival=date(2026,10,19))`; warnings include `"1 stock codes in the Stock in Transit file are not in the Sales Forecast file; ignored"` and `"1 SKUs in the Sales Forecast file are not in the Stock in Transit file; their SIT is 0"` (A3 only — A2 has a row), both with `sap_code=None`.

- [ ] **Step 2: Run to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_sit.py -q` (from `backend/`)
Expected: FAIL — `ModuleNotFoundError: No module named 'app.sit'`.

- [ ] **Step 3: Implement** the models and `sit.py`.
  - Load like `stock._load` (read-only, `reset_dimensions`, "Could not read the file as an Excel .xlsx workbook." on failure). Per sheet, scan the first `HEADER_SEARCH_ROWS` rows for a row with a cell whose `_norm` is `"sap code"` and at least one cell matching `ARRIVAL_RE = re.compile(r"^([a-z]+)\s*w\s*([1-5])\s*arrival$")` on `_norm(h)` with `_month_number(group1)` not None. First such sheet wins.
  - Code via `stock._code`; skip rows with a blank code. Value via `parsing._to_number`: None (blank) → nothing; 0 → nothing; > 0 → a line; negative or text → warning `ParseWarning(sap_code=code, column=<header text, whitespace collapsed>, message="not a number of cartons above 0; skipped")`.
  - `parse_sit` returns one line per (code, month, week), summing cells with the same label (YGN + MDY) and duplicate rows; `apply_sit` then sums lines that land on the same date (e.g. Oct W5 + Nov W1).
  - `week_monday`: year = the one of `Y-1, Y, Y+1` (Y = mtd year) minimising `abs(months between (year, month) and mtd_month)`, ties → later; Monday = `first - timedelta(days=first.weekday())` + `7 * (week - 1)` days.
  - `apply_sit` warning texts exactly as in Step 1 (counted over distinct codes; the "not in the Stock in Transit file" warning counts Data SKUs with no row in the file at all and is omitted when 0). Report warnings come first, then merge warnings; drop per-cell warnings whose code is not a Data SKU.

- [ ] **Step 4: Run to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_sit.py -q`
Expected: all pass.

- [ ] **Step 5: No commit.** Ledger: `Task 1: complete (tests: pytest tests/test_sit.py → N passed)`.

---

### Task 2: Sales Forecast file without SIT, with UOM

**Files:**
- Modify: `backend/app/parsing.py:11-18, 114-128, 189-262`
- Test: `backend/tests/test_parsing.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `parse_input` returns SKUs with `sit=0.0` and `sit_arrivals=None` (filled only by `sit.apply_sit`); `REQUIRED_COLUMNS` without "SIT Ctns (pending order)"; packing size read from "Packing Size" or "UOM".

- [ ] **Step 1: Write the failing tests** in `test_parsing.py` (use `make_workbook` with edited headers):
  - `test_sit_column_not_required`: headers without "SIT Ctns (pending order) " parse; every SKU `sit == 0.0`.
  - `test_sit_column_ignored_with_note`: headers with it and a value 99 → `sit == 0.0`, and a warning with `sap_code None` and message `"SIT Ctns (pending order) in the Data sheet is ignored; stock in transit comes from the Stock in Transit file."`.
  - `test_uom_accepted_as_packing_size`: "Packing Size" renamed "UOM", value 25 → `packing_size == 25.0`.
  - `test_missing_packing_size_and_uom`: neither header → `InputFileError` matching `"missing required column\(s\): Packing Size \(or UOM\)"`.
  - Update any existing test that asserts `sit` read from the Data sheet or the negative-SIT warning (delete those assertions; ledger a ruling naming them).

- [ ] **Step 2: Run to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_parsing.py -q`
Expected: the four new tests FAIL (sit read as 99; "missing required column(s): Packing Size").

- [ ] **Step 3: Implement** in `parsing.py`: drop SIT from `REQUIRED_COLUMNS`; replace "Packing Size" in the required check with "either `packing size` or `uom`" (error text `Packing Size (or UOM)`); add the SIT note; remove the SIT read and the negative-SIT warning; set `sit=0.0` with a comment like the sellable one.

- [ ] **Step 4: Run** `.\.venv\Scripts\python.exe -m pytest tests/test_parsing.py tests/test_sit.py -q` → pass.

- [ ] **Step 5: No commit.** Ledger line.

---

### Task 3: Arrivals in the order plan and the run-out flag

**Files:**
- Modify: `backend/app/models.py` (`MonthPlan.arrivals`, `SkuResult` fields)
- Modify: `backend/app/holding.py:38-82, 140-195, 239-267`
- Test: `backend/tests/test_holding.py`

**Interfaces:**
- Consumes: `SitArrival`, `SkuInput.sit_arrivals` (Task 1).
- Produces:
  - `MonthPlan.arrivals: float | None = None` — order-plan months: SIT landing in the month (0.0 when none); forecast months and month plans stored before this change: None.
  - `SkuResult.sit_arrivals: list[SitArrival] | None = None` (copied from `SkuInput` in `plan_sku`); `SkuResult.runs_out_on: date | None = None`; `SkuResult.runs_out_arrival: date | None = None`.
  - `holding.arrival_days(sku: SkuResult, plan_date: date) -> list[tuple[date, float]]` — sorted; `sit_arrivals is None` → `[(plan_date, sku.sit)]` when `sku.sit != 0` else `[]`; otherwise each arrival at `max(a.date, plan_date)`, same days added.
  - `holding.sit_run_out(sku: SkuResult, months: list[str], plan_date: date) -> tuple[date, date] | None`.

- [ ] **Step 1: Write the failing tests** in `test_holding.py` (build `SkuResult` through the existing helper `run()` / `plan_sku` path, with `SkuInput.sellable`, `sit`, `sit_arrivals` set; plan date `date(2026, 10, 12)`, plan months Oct 2026 – Sep 2027, cycle 4 weeks):

```python
def test_orders_identical_for_any_arrival_timing():
    # avg sales 120 (all 6 values 120), holding 90 days, sellable 100, SIT 300
    early = plan(sellable=100, sit_arrivals=[(date(2026, 10, 12), 300)])
    late = plan(sellable=100, sit_arrivals=[(date(2026, 11, 30), 200), (date(2027, 1, 4), 100)])
    old = plan(sellable=100, sit=300, sit_arrivals=None)
    lines = lambda r: [(o.date, o.qty) for m in r.order_plan for o in m.orders]
    assert lines(early) == lines(late) == lines(old)

def test_stock_on_hand_and_month_arrivals():
    r = plan(sellable=100, sit_arrivals=[(date(2026, 10, 12), 50), (date(2026, 10, 26), 70), (date(2026, 11, 2), 30)])
    oct_, nov = r.order_plan[0], r.order_plan[1]
    assert oct_.opening == 100 and oct_.arrivals == 120 and nov.arrivals == 30
    assert oct_.closing == pytest.approx(oct_.opening + oct_.arrivals + oct_.order - oct_.demand)
    assert nov.opening == pytest.approx(oct_.closing)

def test_arrival_before_plan_date_lands_on_plan_date():
    r = plan(sellable=0, sit_arrivals=[(date(2026, 10, 5), 40)])
    assert r.order_plan[0].arrivals == 40 and r.order_plan[0].opening == 0

def test_older_run_sit_on_plan_date():
    r = plan(sellable=100, sit=300, sit_arrivals=None)
    assert r.order_plan[0].opening == 100 and r.order_plan[0].arrivals == 300
    assert r.runs_out_on is None

def test_run_out_flagged():
    # avg 30/month: October daily 30/31; sellable 5 runs out on 17 Oct, SIT lands 19 Oct
    r = plan(avg=30, sellable=5, sit_arrivals=[(date(2026, 10, 19), 100)])
    assert (r.runs_out_on, r.runs_out_arrival) == (date(2026, 10, 17), date(2026, 10, 19))

def test_run_out_not_flagged_when_sellable_lasts():
    r = plan(avg=30, sellable=50, sit_arrivals=[(date(2026, 10, 19), 100)])
    assert r.runs_out_on is None

def test_run_out_not_flagged_without_demand_or_sit():
    assert plan(no_demand=True, sellable=-5, sit_arrivals=[(date(2026, 10, 19), 100)]).runs_out_on is None
    assert plan(avg=30, sellable=0, sit_arrivals=[]).runs_out_on is None

def test_forecast_mode_unchanged_by_arrivals():
    r = plan(sellable=100, sit_arrivals=[(date(2026, 11, 30), 300)])
    assert r.available == 400 and all(m.arrivals is None for m in r.monthly)

def test_old_stored_month_plan_loads():
    m = MonthPlan.model_validate({"month": "2026-10", "opening": 1, "demand": 1, "order": 0, "closing": 0})
    assert m.arrivals is None
```

`plan(...)` is a small local helper over the existing `run()`/`plan_sku` + `plan_all` path that sets `avg` (all 6 demand values, default 120), holding 90 days unless given, `no_demand` (all values 0), and `sit` = the arrivals' total unless given; it returns the one `SkuResult`. Write it once at the top of the new tests. The run-out flag is set by `plan_all`, so the helper goes through `plan_all`.

- [ ] **Step 2: Run to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_holding.py -q`
Expected: new tests FAIL (`arrivals` / `runs_out_on` not fields; `sit_arrivals` unknown).

- [ ] **Step 3: Implement.**
  - `weekly_order_plan`: stock on hand starts at `sku.sellable`; per planned day, in order: add that day's arrivals (and to the month's arrivals), then on an order date compute required from `stock + pending` (pending = arrivals dated after that day; arrivals never landing inside the plan stay pending), then take the day's demand. `MonthPlan(..., arrivals=month_arrivals, closing=opening + month_arrivals + order − used)`. Everything else (level, cover, MOQ, plan-date order) unchanged.
  - `sit_run_out`: return None when `sku.valid_count == 0` or `arrival_days` is empty; otherwise walk days from the plan date to the last arrival day: add the day's arrivals, subtract the day's demand (same `daily()` as the plan), and the first day with stock `< -EPS` that is before the last arrival day returns `(that day, first arrival day after it)`.
  - `plan_all`: after `_attach_order_plan`, `result.runs_out_on, result.runs_out_arrival = sit_run_out(...) or (None, None)`.
  - Existing tests whose order-plan month-1 opening includes SIT now expect opening = sellable and arrivals = SIT; update them and ledger a ruling naming each.

- [ ] **Step 4: Run** `.\.venv\Scripts\python.exe -m pytest -q` (whole backend suite) → only Task 4's API/export areas may fail if they depend on SIT from the Data sheet; list them in the ledger for Task 4. `test_holding.py`, `test_sit.py`, `test_parsing.py` pass.

- [ ] **Step 5: No commit.** Ledger line.

---

### Task 4: Upload, storage, export

**Files:**
- Modify: `backend/app/models.py` (`StockResult.sit`, `StockResult.sit_warnings`, `InspectResponse.sit_file_name`, `RunListItem.sit_file_name`)
- Modify: `backend/app/db.py` (v8), `backend/app/repository.py` (create/get/list), `backend/app/main.py` (`_parse_uploads`, inspect, create_run), `backend/app/export.py:145-149`
- Modify: `backend/tests/helpers.py` (`sit_from_data`), `backend/tests/test_api.py` (`files()`), `test_repository.py`, `test_export.py`
- Test: `backend/tests/test_api.py`, `test_repository.py`, `test_export.py`

**Interfaces:**
- Consumes: `parse_sit`, `apply_sit`, `SIT_NAME` (Task 1); `SkuResult.runs_out_on/runs_out_arrival` (Task 3).
- Produces:
  - `StockResult.sit: SitFileSummary | None = None`; `StockResult.sit_warnings: list[ParseWarning] = []`
  - `InspectResponse.sit_file_name: str`; `RunListItem.sit_file_name: str | None = None`
  - API form field `sit_file` (required) on `POST /api/inspect` and `POST /api/runs`
  - `Repository.create_run(file_name, sales_file_name, pg_file_name, pdg_file_name, sit_file_name, parsed, actual, stock, result) -> int`
  - `db.SCHEMA_VERSION = 8`; `V8_COLUMNS = (("runs", "sit_file_name", "TEXT NULL"),)`
  - helpers: `sit_from_data(data: bytes, label: str = "Oct W3 Arrival") -> bytes` — a SIT workbook with every Data-sheet SKU of the fixture and its old Data-sheet SIT value in one column.

- [ ] **Step 1: Write the failing tests.**
  - `test_api.py`: `files(..., sit=SIT)` with `SIT = sit_from_data(DATA)`; existing tests keep their expectations (forecast mode unchanged; order lines unchanged).
    - `test_inspect_reports_sit_summary`: `r["sit_file_name"] == "sit.xlsx"`, `r["stock"]["sit"]["skus_with_sit"]` equals the number of fixture SKUs with SIT > 0, `cartons` equals their total.
    - `test_sit_file_error_named`: a SIT file without arrival columns → 400 with detail starting `"Stock in Transit file: No sheet has a SAP Code column"`.
    - `test_sit_file_required`: posting without `sit_file` → 422.
    - `test_run_stores_sit_file_name`: run JSON and `GET /api/runs` list have `sit_file_name == "sit.xlsx"`; `run["stock"]["sit_warnings"]` is a list.
  - `test_repository.py`: `test_v7_to_v8_upgrade` — build a v7 database the way the v6→v7 test builds a v6 one (schema without `sit_file_name`, `user_version = 7`, one run row); connect → `sit_file_name` column exists and is NULL for the old row, `user_version == 8`; connecting again is a no-op. Older run rows read back with `sit_file_name is None`.
  - `test_export.py`: `test_warnings_sheet_has_sit_and_run_out` — a run whose `stock.sit_warnings` has one warning and one SKU with `runs_out_on=date(2026,10,17)`, `runs_out_arrival=date(2026,10,19)`: the Warnings sheet has rows `["Stock in Transit file", None, None, <warning message>]` and `["Stock in Transit file", <sap>, None, "runs out about 17 Oct, before its stock in transit arrives on 19 Oct"]`.

- [ ] **Step 2: Run to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_api.py tests/test_repository.py tests/test_export.py -q`
Expected: new tests FAIL (unknown field `sit_file`, no `sit` key, schema 7).

- [ ] **Step 3: Implement.**
  - `_parse_uploads(data_file, sales_file, pg_file, pdg_file, sit_file)` parses the SIT file fifth (error prefix `f"{SIT_NAME}: "`), then `apply_stock`, then `apply_sit`; returns the `StockResult` with `sit` and `sit_warnings` set.
  - `inspect`/`create_run` take `sit_file: UploadFile = File(...)`; inspect's `warnings` also include `stock.sit_warnings` at the end; `create_run` passes `sit_file.filename or ""`.
  - DB: add `sit_file_name TEXT NULL` to the `runs` CREATE statement, `_add_columns(conn, V8_COLUMNS)` after v7, version 8.
  - Repository: insert/read/list `sit_file_name`.
  - Export: Warnings rows gain `("Stock in Transit file", w)` for `run.stock.sit_warnings` (when `run.stock`) and one row per SKU with `runs_out_on` (message as above, dates as `d Mon` — reuse the day-month formatting already used by `stock._date_text` without the year).

- [ ] **Step 4: Run** the whole backend suite: `.\.venv\Scripts\python.exe -m pytest -q` → all pass.

- [ ] **Step 5: No commit.** Ledger line.

---

### Task 5: Frontend types and helpers

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api.ts:78-93`, `frontend/src/lib/mode.ts`, `frontend/src/lib/format.ts`, `frontend/src/lib/warnings.ts`
- Test: `frontend/src/lib/mode.test.ts`, `format.test.ts`, `warnings.test.ts`

**Interfaces:**
- Consumes: the API shapes from Tasks 3–4.
- Produces:
  - types: `SitArrival { date: string; cartons: number }`; `SitFileSummary { skus_with_sit: number; cartons: number; first_arrival: string | null; last_arrival: string | null }`; `MonthPlan.arrivals?: number | null`; `SkuResult.sit_arrivals: SitArrival[] | null`, `runs_out_on: string | null`, `runs_out_arrival: string | null`; `StockResult.sit?: SitFileSummary | null`, `sit_warnings?: ParseWarning[]`; `InspectResponse.sit_file_name: string`; `RunListItem.sit_file_name: string | null`.
  - api: `UploadFiles.sit: File`, appended as `sit_file`.
  - mode.ts: `skuArrivals(s: SkuResult, planDate: string): SitArrival[]` (null → one arrival of `s.sit` on the plan date when `s.sit !== 0`; dates before the plan date → the plan date; same dates added; sorted); `arrivalsByWeek(arrivals: SitArrival[]): Map<string, number>` (keyed by `weekStart`).
  - format.ts: `runOutMessage(s: SkuResult): string | null` → `"Runs out about 17 Oct, before its stock in transit arrives on 19 Oct"` or null.
  - warnings.ts: `WarningSource` adds `'Stock in Transit file'`; `groupWarnings(data, sales, stock = [], sit = [])`; `runOutWarnings(skus: SkuResult[]): ParseWarning[]` → one per flagged SKU `{ sap_code, column: null, message: "runs out about 17 Oct, before its stock in transit arrives on 19 Oct" }`.

- [ ] **Step 1: Write the failing tests:**
  - `skuArrivals` — real list kept and sorted; date before plan date clamped and merged with a plan-date arrival; null + sit 300 → `[{date: planDate, cartons: 300}]`; null + sit 0 → `[]`.
  - `arrivalsByWeek` — arrivals on 12 Oct and 14 Oct 2026 → `Map { '2026-10-12' => sum }`; 26 Oct separate.
  - `runOutMessage` — flagged SKU text exact; unflagged → null.
  - `groupWarnings` with a 4th list → source `'Stock in Transit file'`; `runOutWarnings` text exact.

- [ ] **Step 2: Run** `npm --prefix frontend test` → new tests FAIL (not exported).

- [ ] **Step 3: Implement** the helpers and types (UTC date math as in `weekStart`).

- [ ] **Step 4: Run** `npm --prefix frontend test` → pass; `npm --prefix frontend run build` → no type errors except in pages Task 6 changes (list them; Task 6 fixes).

- [ ] **Step 5: No commit.** Ledger line.

---

### Task 6: Screens

**Files:**
- Modify: `frontend/src/pages/UploadPage.tsx`, `HistoryPage.tsx`, `PlanPage.tsx`, `frontend/src/components/WarningsPanel.tsx`, `SkuDetail.tsx`, `frontend/src/index.css`

**Interfaces:**
- Consumes: Task 5 helpers and types.

- [ ] **Step 1: Implement** (no unit tests exist for pages; verified in Step 3):
  - **UploadPage:** a fifth file input labelled `Stock in Transit (.xlsx)` after PDG Stock List; all five required; intro sentence mentions "the stock in transit file"; the file list line includes `info.sit_file_name`; a summary row "Stock in transit: <skus_with_sit> of <sku_count> SKUs, <cartons> cartons arriving <first d Mon> – <last d Mon>" (or "no stock in transit" when 0); file-level `sit_warnings` in the same alert style as `stockFileWarnings`.
  - **HistoryPage:** a "Stock in Transit file" column after PDG (`'—'` when null).
  - **PlanPage:** "From …" adds ` + ${run.sit_file_name}` when not null; `WarningsPanel` gets `sitWarnings={[...(run.stock?.sit_warnings ?? []), ...runOutWarnings(result.skus)]}`; `WeekCells` also takes `arrivals` (`arrivalsByWeek(skuArrivals(s, result.plan_date))`) and renders `+<qty> arriving` in a muted `.arrival-line` under any order lines; the Status cell adds `<span className="chip chip-red" title={runOutMessage(s)}>Runs out before SIT</span>` when `runs_out_on` is set (both modes); the plan-mode footnote says stock on hand adds SIT in its arrival week while orders count SIT still on its way.
  - **WarningsPanel:** a `sitWarnings` prop passed as the 4th list to `groupWarnings`.
  - **SkuDetail:** a red alert with `runOutMessage(sku)` when set; a "Stock in transit" table (Date, Cartons) from `skuArrivals(sku, planDate)` or the line "No stock in transit"; in plan mode an "Arrivals" column between Opening and Demand showing `m.arrivals == null ? '—' : fmtExact(m.arrivals)`.
  - **CSS:** `.arrival-line` (muted, small, like `.order-week`).

- [ ] **Step 2: Run** `npm --prefix frontend test`, `npm --prefix frontend run build`, `npm --prefix frontend run lint` → all clean.

- [ ] **Step 3: Verify in the browser** on the test servers only: copy `backend/data/orderplan.db` to `backend/data/orderplan-test.db`, `preview_start` `backend-test` and `frontend-test`, upload copies of the planner's files (Sales Forecast = the scratch copy of the new workbook, Actual Sales and stock files as in run 20 if available locally, else the workbook itself for PG/PDG; SIT = the same workbook). Check: the upload summary (44 SKUs, 12,211 cartons, 12 Oct – 26 Oct); Weeks view shows Ya Thar Taw Win's arrivals in 19 Oct; SKU detail lists arrivals and the Arrivals column; History column; an older run opens and shows "—" in Arrivals; no console errors. Stop only the test servers you started.

- [ ] **Step 4: No commit.** Ledger line.

---

### Task 7: README and final check

**Files:**
- Modify: `README.md`

- [ ] **Step 1:** README: the five files (Stock in Transit file and its layout: any sheet with SAP Code + "<Month> W<n> Arrival"); the week rule (Mon–Sun, W1 holds the 1st, Oct W5 = Nov W1, deliveries land on Monday, before the plan date → plan date, year nearest the MTD month); SIT no longer read from the Data sheet; UOM accepted; order plan: stock on hand vs SIT still on its way, orders unchanged, Arrivals column; the run-out flag; older runs; the v8 upgrade and `orderplan.pre-v8-backup.db`.
- [ ] **Step 2:** Whole suites: backend `pytest -q`, frontend test/build/lint — all green; `git diff .claude/launch.json` empty; `git status` shows no new files outside `backend/app/sit.py`, `backend/tests/test_sit.py`, the spec and this plan.
- [ ] **Step 3:** Final whole-change review (fresh reviewer, most capable model) per the execution skill; fix Critical/Important with a failing test first.
- [ ] **Step 4:** Ask the user before backing up `orderplan.db` to `orderplan.pre-v8-backup.db` and restarting their backend/frontend.
