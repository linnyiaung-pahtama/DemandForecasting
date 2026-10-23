# Holding-Based Order Plan (v2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the v1 day-by-day reorder simulation with the planner's holding-based calculation. Add admin's sales export as a second upload and log every holding change, keeping the rest of the existing tool.

**Architecture:** This amends the built tool on branch `feature/order-plan-tool`. The backend changes are:
- new pure modules `months.py`, `sales.py` (export parser and carton conversion) and `holding.py` (calculation, plus the plan-date rules moved from `engine.py`);
- the storage, API, summary and export are switched to the v2 models;
- `engine.py`, `demand.py` and their tests are removed.

The frontend pages are then reworked against the new JSON.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, openpyxl, sqlite3, pytest. React 19, TypeScript, Vite 6, react-router-dom 6, vitest 5 (node environment).

**Spec:** `docs/superpowers/specs/2026-10-23-holding-based-order-plan-design.md` (v2). It amends `docs/superpowers/specs/2026-10-22-order-plan-tool-design.md` (v1). Read v2 fully before any task.

## Global Constraints

- Two uploads per cycle: the **Data file** (multipart field `data_file`) and the **sales export** (multipart field `sales_file`).
- Actual months = the 3 calendar months immediately before the MTD month. Forecast months = the MTD month and the next 2.
- Valid demand value = a number **> 0**. Zero, negative, blank and missing values are skipped.
- Buffer = mean of valid values. Target = buffer × holding. Available = Total Sellable + SIT. Required = max(target − available, 0), rounded **up** to whole cartons. If 0 < required < MOQ, the order = MOQ (MOQ applied). If required = 0, the order = 0. Stock cover = available ÷ buffer (in months). Next calculation date = plan date + lead time (days).
- Lead time does **not** change the order quantity.
- Holding is per supplier, in months, decimals allowed, valid range **0.5–24**, and there is no default. A supplier without holding is **blocked**: status `HOLDING_NOT_SET`, target/required/order = null. The run is not rejected.
- `ZERO_FORECAST` flag: all 3 forecast values are invalid and at least 1 actual is valid. The order is still calculated.
- Every holding change is logged as supplier, old value, new value and timestamp. There is no user name.
- Sales export conversion: sum `Qty` over all rows per item and month, then ÷ Data `Packing Size`. This gives cartons.
- Plan-date rules are unchanged from v1. Earliest = MTD end + 1 day. Latest = max(last day of MTD month, earliest).
- Quantities are cartons. There are no money values; the export's `Amount` column is ignored. JSON is snake_case, and `frontend/src/types.ts` mirrors `backend/app/models.py` exactly.
- Environment: Windows. Backend tests: `cd backend && .venv/Scripts/python -m pytest -q`. Frontend: `npm --prefix frontend test`, `npm --prefix frontend run build`, `npm --prefix frontend run lint`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A sales export for a different period** (e.g. Aug–Oct uploaded with an October Data file). Only the overlapping actual months are used, with a warning naming each missing month. If none overlap, the result is a 400. This is pinned by `test_export_covering_other_months_warns_and_uses_overlap` and `test_export_with_no_actual_months_is_rejected` (Task 2).
2. **Numeric item codes in the export** (`5401111001` stored as a number) must match the Data SAP Code as text with no `.0`. This is pinned by `test_numeric_item_codes_match` (Task 2).
3. **The two files uploaded in the wrong slots** must give a 400 that says which file is wrong, never a 500. This is pinned by `test_swapped_files_return_400` (Task 4).
4. **The planner's existing v1 database** (it may contain v1 runs and settings, from testing) must not crash startup or be silently destroyed. It is moved aside to `orderplan.v1-backup.db`, and a fresh v2 DB is created. This is pinned by `test_v1_database_is_backed_up_and_replaced` (Task 3).
5. **A holding cleared or typed out of range** on the settings page. Blank means "not set" (the supplier becomes blocked, and the change is logged). 0, 25 and text are rejected with an inline error and a 422. This is pinned by `test_holding_validation` (Task 4) and `validateHolding` tests (Task 7).

---

## File Structure

```
backend/app/
  months.py      NEW  month-key helpers (prev/next months, labels)
  sales.py       NEW  parse_sales(), actual_cartons()
  holding.py     NEW  plan_sku(), plan_all(), plan_date_bounds(), validate_plan_date()
  models.py      MOD  add v2 models (Task 1–2); remove v1-only models (Task 4)
  summary.py     MOD  rewritten for v2 (Task 4)
  db.py          MOD  v2 schema + v1 backup (Task 3)
  repository.py  MOD  holdings, settings log, runs with sales data (Task 3)
  main.py        MOD  v2 routes (Task 4)
  export.py      MOD  v2 sheets (Task 5)
  config.py      MOD  drop DEFAULT_REORDER_DAYS/TARGET_DAYS/EXCESS_FACTOR (Task 4)
  engine.py, demand.py  DELETE (Task 4)
backend/tests/
  fixtures/sales_export.xlsx  NEW  copy of admin's export
  helpers.py     MOD  add make_sales_workbook()
  test_months.py, test_sales.py, test_holding.py  NEW
  test_repository.py, test_api.py, test_summary.py, test_export.py  REWRITTEN
  test_engine.py, test_demand.py  DELETE (Task 4; plan-date tests move to test_holding.py)
frontend/src/
  types.ts, api.ts                    MOD (Task 6)
  pages/UploadPage.tsx                MOD (Task 6)
  lib/filters.ts (+test)              REWRITTEN (Task 7)
  lib/format.ts (+test)               MOD (Task 7: status labels, orderExplanation)
  pages/PlanPage.tsx, components/SkuDetail.tsx, components/FlagChips.tsx → StatusChip.tsx  MOD (Task 7)
  pages/SupplierPage.tsx, pages/SettingsPage.tsx, lib/settings.ts (+test)  MOD (Task 8)
  lib/useWeeksInput.ts                DELETE (Task 7; no window in v2)
README.md                             MOD (Task 9)
```

---

### Task 1: Month helpers and the holding calculation

**Files:**
- Create: `backend/app/months.py`, `backend/app/holding.py`, `backend/tests/test_months.py`, `backend/tests/test_holding.py`
- Modify: `backend/app/models.py` (add models only; remove nothing)

**Interfaces:**
- Consumes: `SkuInput`, `ParsedInput` (existing `models.py`).
- Produces (`months.py`):
  - `prev_months(key: str, n: int) -> list[str]`: the n months before `key`, oldest first (`prev_months("2026-10", 3) == ["2026-07","2026-08","2026-09"]`).
  - `next_months(key: str, n: int) -> list[str]`: `key` and the following n−1 months (`next_months("2026-11", 3) == ["2026-11","2026-12","2027-01"]`).
  - `month_label(key: str) -> str`: `"Jul 2026"`.
- Produces (`models.py`):
  - `class SkuStatus(str, Enum)`: `TO_ORDER`, `NO_ORDER_NEEDED`, `HOLDING_NOT_SET`, `NO_DEMAND_DATA`.
  - `class DemandValue(BaseModel)`: `month: str`, `source: Literal["actual","forecast"]`, `value: float | None`, `valid: bool`.
  - `class SkuResult(BaseModel)`:
    - identity: `sap_code`, `supplier`, `description: str`;
    - inputs: `packing_size: float | None`, `lead_time_days: int | None`, `moq: float`, `sellable: float`, `sit: float`, `available: float`, `demand_values: list[DemandValue]` (6 items: actuals then forecasts, oldest first);
    - calculation: `valid_count: int`, `buffer: float | None`, `holding_months: float | None`, `target: float | None`, `required: int | None`, `order_qty: int | None`, `moq_applied: bool`, `stock_cover_months: float | None`, `next_calc_date: date | None`;
    - outcome: `status: SkuStatus`, `zero_forecast: bool`.
- Produces (`holding.py`):
  - `plan_sku(sku: SkuInput, actuals: dict[str, float], actual_months: list[str], forecast_months: list[str], holding_months: float | None, plan_date: date) -> SkuResult`
  - `plan_date_bounds(parsed: ParsedInput) -> tuple[date, date]` and `validate_plan_date(parsed: ParsedInput, plan_date: date) -> None`. Move these unchanged (body, docstrings and message) from `engine.py`; `engine.py` keeps its own copy until Task 4 deletes it.

- [ ] **Step 1: Write the failing tests**

```python
# test_months.py
from app.months import prev_months, next_months, month_label
def test_month_helpers():
    assert prev_months("2026-10", 3) == ["2026-07", "2026-08", "2026-09"]
    assert prev_months("2027-02", 3) == ["2026-11", "2026-12", "2027-01"]
    assert next_months("2026-11", 3) == ["2026-11", "2026-12", "2027-01"]
    assert month_label("2026-07") == "Jul 2026"
```

```python
# test_holding.py
from datetime import date
import pytest
from app.holding import plan_sku
from app.models import SkuInput, SkuStatus

ACT = ["2026-07", "2026-08", "2026-09"]; FC = ["2026-10", "2026-11", "2026-12"]
PD = date(2026, 10, 14)

def sku(sellable=200, sit=60, moq=150, lead=61, fc=(130, 140, 120)):
    return SkuInput(sap_code="N1", supplier="Alpha Foods", description="Noodles", packing_size=10,
                    moq=moq, shelf_life_months=None, lead_time_days=lead, sellable=sellable,
                    non_sellable=0, sit=sit, mtd_sales=0, forecast=dict(zip(FC, fc)))

def run(actuals=(100, 120, 110), holding=3, **kw):
    return plan_sku(sku(**kw), dict(zip(ACT, actuals)), ACT, FC, holding, PD)

def test_spec_worked_example():
    r = run()
    assert r.buffer == pytest.approx(120) and r.valid_count == 6
    assert r.target == pytest.approx(360) and r.available == pytest.approx(260)
    assert r.required == 100 and r.order_qty == 150 and r.moq_applied
    assert r.stock_cover_months == pytest.approx(260 / 120)
    assert r.next_calc_date == date(2026, 12, 14)
    assert r.status == SkuStatus.TO_ORDER and not r.zero_forecast
    assert [d.month for d in r.demand_values] == ACT + FC
    assert [d.source for d in r.demand_values] == ["actual"] * 3 + ["forecast"] * 3

def test_invalid_values_are_skipped():
    r = run(actuals=(-5, 0, 110))          # -5 and 0 invalid
    assert r.valid_count == 4 and r.buffer == pytest.approx((110 + 130 + 140 + 120) / 4)
    assert [d.valid for d in r.demand_values] == [False, False, True, True, True, True]
    r2 = plan_sku(sku(), {"2026-09": 110}, ACT, FC, 3, PD)   # Jul/Aug missing from actuals
    assert r2.demand_values[0].value is None and r2.valid_count == 4

def test_required_rounds_up_and_moq_rules():
    r = run(actuals=(120.1, 120, 120), fc=(120, 120, 120), moq=0)   # buffer 120.0167, target 360.05
    assert r.required == 101 and r.order_qty == 101 and not r.moq_applied
    r0 = run(sellable=500)                                          # available 560 > target 360
    assert r0.required == 0 and r0.order_qty == 0 and not r0.moq_applied
    assert r0.status == SkuStatus.NO_ORDER_NEEDED

def test_holding_not_set_blocks_order_but_shows_buffer():
    r = run(holding=None)
    assert r.status == SkuStatus.HOLDING_NOT_SET
    assert r.target is None and r.required is None and r.order_qty is None
    assert r.buffer == pytest.approx(120) and r.stock_cover_months == pytest.approx(260 / 120)

def test_no_demand_data():
    r = run(actuals=(0, 0, 0), fc=(0, 0, 0))
    assert r.status == SkuStatus.NO_DEMAND_DATA and r.buffer is None
    assert r.target == 0 and r.required == 0 and r.order_qty == 0 and r.stock_cover_months is None
    assert run(actuals=(0, 0, 0), fc=(0, 0, 0), holding=None).status == SkuStatus.HOLDING_NOT_SET

def test_zero_forecast_flag_still_orders():
    r = run(fc=(0, 0, 0))                  # buffer from actuals only = 110
    assert r.zero_forecast and r.buffer == pytest.approx(110) and r.order_qty == 150
    assert not run(actuals=(0, 0, 0), fc=(0, 0, 0)).zero_forecast   # no valid actuals either

def test_missing_lead_time_has_no_next_date():
    assert run(lead=None).next_calc_date is None
    assert run(lead=-3).next_calc_date is None
```

Move `test_validate_plan_date_range`, `test_plan_date_bounds_end_at_mtd_month_end` and `test_plan_date_bounds_when_mtd_ends_on_month_end` from `test_engine.py` into `test_holding.py`, importing from `app.holding`. Leave the originals in place; Task 4 deletes `test_engine.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_months.py tests/test_holding.py -q`
Expected: FAIL (`ModuleNotFoundError: app.months`).

- [ ] **Step 3: Implement `months.py`, the models and `holding.py`**

- `plan_sku` follows the Global Constraints formula.
- Status precedence: `HOLDING_NOT_SET` (holding is None) > `NO_DEMAND_DATA` (no valid values) > `TO_ORDER` (order_qty > 0) > `NO_ORDER_NEEDED`.
- Use `ceil(x - 1e-9)` for rounding up. `next_calc_date` = `plan_date + timedelta(days=lead)` when lead ≥ 0, else None.

- [ ] **Step 4: Run all backend tests**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: all pass (v1 tests untouched).

- [ ] **Step 5: Commit** `feat: holding-based calculation and month helpers`

---

### Task 2: Sales export parser and carton conversion

**Files:**
- Create: `backend/app/sales.py`, `backend/tests/test_sales.py`, `backend/tests/fixtures/sales_export.xlsx` (copy of `C:/Users/linnyiaung/Downloads/actual-sales-3m.xlsx`)
- Modify: `backend/app/models.py` (add models), `backend/tests/helpers.py` (add `make_sales_workbook`)

**Interfaces:**
- Consumes: `months.prev_months`, `month_label` (Task 1); `ParsedInput`, `ParseWarning`, `InputFileError`; `parsing._norm`, `parsing._month_number`, `parsing._to_number` (reuse them; don't copy).
- Produces (`models.py`):
  - `class SalesExport(BaseModel)`: `pieces: dict[str, dict[str, float]]` (sap code → "YYYY-MM" → summed pieces), `months: list[str]` (sorted, months with ≥ 1 row), `warnings: list[ParseWarning]`.
  - `class ActualSales(BaseModel)`: `months: list[str]` (the 3 actual months), `cartons: dict[str, dict[str, float]]` (Data SAP code → month → cartons; only months present in the export; only SKUs with packing size > 0), `skus_with_sales: int` (count of Data SKUs with at least one export row in the actual months, i.e. keys of `cartons`; negative net months still count here and are judged invalid later by `plan_sku`), `warnings: list[ParseWarning]`.
- Produces (`sales.py`):
  - `parse_sales(data: bytes) -> SalesExport`. Raises `InputFileError` when the file is not a readable .xlsx ("Could not read the sales export as an Excel .xlsx workbook."). It also raises when no sheet has a header row (in the first 10 rows) containing `itemCode`, `Year`, `Month` and `Qty`, matched with `_norm`. Message: "The sales export has no sheet with itemCode, Year, Month and Qty columns."
  - `actual_cartons(export: SalesExport, parsed: ParsedInput) -> ActualSales`. Raises `InputFileError("The sales export has no rows for {labels} (the 3 months before the MTD month).")` when none of the 3 actual months are present.
- Produces (`tests/helpers.py`): `make_sales_workbook(rows: list[list], headers: list[str] | None = None, sheet: str = "Sheet1") -> bytes`. Default headers: `["Company","BranchName","Principal","Brand","itemCode","Itemname","Year","Month","Qty","Amount"]`, on row 1.

- [ ] **Step 1: Write the failing tests**

```python
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
```

Note: in `make_workbook`'s default 23 headers, column 4 is `Packing Size`; `None` there gives packing None plus a parse warning.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_sales.py -q`
Expected: FAIL (`ModuleNotFoundError: app.sales`).

- [ ] **Step 3: Implement `parse_sales` and `actual_cartons`**

- Month key = `f"{int(Year):04d}-{_month_number(_norm(Month)):02d}"`. If a row's Year or Month can't be read, skip it with a warning.
- Item code: `str(int(v))` for numbers, otherwise `str(v).strip()`.
- Per-item, per-month warnings use `sap_code`. Month-level warnings use `column=None`. Every message names the month with `month_label`.

- [ ] **Step 4: Run all backend tests.** Expected: all pass.

- [ ] **Step 5: Commit** `feat: parse sales export and convert to cartons`

---

### Task 3: Storage for holdings, settings log and v2 runs

**Files:**
- Modify: `backend/app/db.py`, `backend/app/repository.py`, `backend/app/models.py` (add models), `backend/tests/test_repository.py` (rewrite)

**Interfaces:**
- Consumes: `ParsedInput`, `ActualSales` (Task 2).
- Produces (`models.py`):
  - `class SupplierHolding(BaseModel)`: `supplier: str`, `holding_months: float | None`.
  - `class SettingsLogEntry(BaseModel)`: `id: int`, `supplier: str`, `old_value: float | None`, `new_value: float | None`, `changed_at: datetime`.
  - `class HoldingPlan(BaseModel)`: `plan_date: date`, `actual_months: list[str]`, `forecast_months: list[str]` (the 3 used), `skus: list[SkuResult]`, `settings_used: list[SupplierHolding]`, `blocked_suppliers: list[str]`, `counts: dict[str, int]`. The counts keys are `TO_ORDER`, `NO_ORDER_NEEDED`, `HOLDING_NOT_SET`, `NO_DEMAND_DATA` and `ZERO_FORECAST`, always present, 0 when none.
  - `class RunListItemV2(BaseModel)`: `id: int`, `created_at: datetime`, `file_name: str`, `sales_file_name: str`, `plan_date: date`, `sku_count: int`.
  - `class RunRecordV2(RunListItemV2)`: `parsed: ParsedInput`, `actual: ActualSales`, `result: HoldingPlan`. Task 4 renames these two to `RunListItem`/`RunRecord` once the v1 models are removed.
- Produces (`db.py`):
  - `SCHEMA_VERSION = 2`, stored in `PRAGMA user_version`.
  - `connect(db_path)`: if the file exists and `user_version` < 2 and it has a `supplier_settings` table with a `reorder_days` column (a v1 DB), close it and rename the file to `orderplan.v1-backup.db` in the same folder. If that name is taken, add `-1`, `-2` and so on. Then create a fresh DB.
  - Tables:
    - `supplier_settings(supplier TEXT PRIMARY KEY, holding_months REAL NULL, updated_at TEXT NOT NULL)`
    - `settings_log(id INTEGER PRIMARY KEY AUTOINCREMENT, supplier TEXT NOT NULL, old_value REAL NULL, new_value REAL NULL, changed_at TEXT NOT NULL)`
    - `runs(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, file_name TEXT NOT NULL, sales_file_name TEXT NOT NULL, plan_date TEXT NOT NULL, sku_count INTEGER NOT NULL, parsed_json TEXT NOT NULL, actual_json TEXT NOT NULL, result_json TEXT NOT NULL)`
- Produces (`repository.py`, replacing the v1 settings and run methods):
  - `get_holdings() -> dict[str, float]` (only suppliers with a value)
  - `save_holdings(items: list[SupplierHolding]) -> list[SettingsLogEntry]`: upserts, and logs only items whose value differs from the stored one. A missing row counts as None. Returns the new log entries.
  - `get_settings_log(limit: int = 200) -> list[SettingsLogEntry]` (newest first)
  - `create_run(file_name: str, sales_file_name: str, parsed: ParsedInput, actual: ActualSales, result: HoldingPlan) -> int`
  - `update_run_result(run_id: int, result: HoldingPlan) -> None`
  - `get_run(run_id) -> RunRecordV2 | None`
  - `list_runs() -> list[RunListItemV2]` (reads the `sku_count` column, with no JSON parsing)
  - `latest_run_id() -> int | None`

  Remove `get_settings`, `save_settings` and `add_default_settings`. `main.py` still calls them until Task 4, so in this task the API tests are expected to fail. **Run only the non-API tests in this task** and record it in the report.

- [ ] **Step 1: Write the failing tests**

```python
from app.repository import Repository
from app.models import SupplierHolding
import sqlite3

def test_holdings_and_log(tmp_path):
    repo = Repository(tmp_path / "t.db")
    repo.save_holdings([SupplierHolding(supplier="A", holding_months=3)])
    repo.save_holdings([SupplierHolding(supplier="A", holding_months=3)])      # unchanged: no log
    repo.save_holdings([SupplierHolding(supplier="A", holding_months=2.5)])
    repo.save_holdings([SupplierHolding(supplier="A", holding_months=None)])   # cleared
    assert repo.get_holdings() == {}
    log = repo.get_settings_log()
    assert [(e.old_value, e.new_value) for e in log] == [(2.5, None), (3, 2.5), (None, 3)]

def test_v1_database_is_backed_up_and_replaced(tmp_path):
    db = tmp_path / "orderplan.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE supplier_settings (supplier TEXT PRIMARY KEY, reorder_days INTEGER NOT NULL, "
                  "target_days INTEGER NOT NULL, is_default INTEGER NOT NULL, updated_at TEXT NOT NULL)")
        c.execute("INSERT INTO supplier_settings VALUES ('A', 20, 30, 1, 'x')")
    repo = Repository(db)
    assert (tmp_path / "orderplan.v1-backup.db").exists()
    assert repo.get_holdings() == {} and repo.list_runs() == []
```

Also add `test_run_round_trip(tmp_path)`. It builds a run from `parse_input(make_workbook(...))`, `actual_cartons(parse_sales(make_sales_workbook(...)), parsed)` and `plan_all` (Task 4 provides this; until then build a `HoldingPlan` by hand from one `plan_sku` result). It asserts equality after the round trip, that `sales_file_name` is kept, that `list_runs()[0].sku_count == 1`, and that `get_run(999) is None`.

- [ ] **Step 2: Run the tests to verify they fail.** Run: `cd backend && .venv/Scripts/python -m pytest tests/test_repository.py -q`

- [ ] **Step 3: Implement the v2 `db.py` and `Repository`.** Keep the one-connection-per-call pattern (`closing()` + `with conn`).

- [ ] **Step 4: Run the non-API suites.** Run: `cd backend && .venv/Scripts/python -m pytest -q --ignore=tests/test_api.py --ignore=tests/test_export.py`. Expected: pass.

- [ ] **Step 5: Commit** `feat: v2 storage with holdings, settings log and sales data`

---

### Task 4: Switch the API and supplier summary to v2; remove v1 engine

**Files:**
- Modify: `backend/app/holding.py` (add `plan_all`), `backend/app/summary.py` (rewrite), `backend/app/main.py`, `backend/app/models.py` (remove v1-only models, rename V2 run models), `backend/app/config.py`, `backend/app/export.py` (temporary minimal compile fix only, see Step 3)
- Delete: `backend/app/engine.py`, `backend/app/demand.py`, `backend/tests/test_engine.py`, `backend/tests/test_demand.py`
- Test: `backend/tests/test_api.py` (rewrite), `backend/tests/test_summary.py` (rewrite), `backend/tests/test_holding.py` (add `plan_all` tests)

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces (`holding.py`): `plan_all(parsed: ParsedInput, actual: ActualSales, holdings: dict[str, float], plan_date: date) -> HoldingPlan`. Actual months = `actual.months`. Forecast months = `next_months(parsed.mtd_month, 3)`. `settings_used` lists every supplier in the file, in order of first appearance. `blocked_suppliers` lists the ones without holding.
- Produces (`models.py`):
  - Removed: `SupplierSetting`, `FlagCode`, `Flag`, `OrderReason`, `PlannedOrder`, `WeekProjection`, `SkuPlan`, `PlanResult`, and the v1 `RunListItem`/`RunRecord`/`SupplierSettingView`/`SupplierSummary`.
  - Renamed: `RunListItemV2` → `RunListItem`, `RunRecordV2` → `RunRecord`.
  - New `class SupplierSummary(BaseModel)`: `supplier`, `holding_months: float | None`, `sku_count`, `skus_to_order`, `total_order_qty: int`, `blocked_skus`, `no_demand_skus`, `zero_forecast_skus: int`, `max_lead_time_days: int | None`.
  - New `class SupplierSettingView(BaseModel)`: `supplier`, `holding_months: float | None`, `sku_count: int`, `max_lead_time_days: int | None`.
  - `InspectResponse` gains `sales_file_name: str`, `actual_months: list[str]`, `forecast_window: list[str]` and `skus_with_sales: int`. Its `warnings` field contains the Data warnings followed by the sales warnings.
- Produces (`summary.py`): `summarize_suppliers(result: HoldingPlan) -> list[SupplierSummary]`, sorted by `total_order_qty` descending, then supplier name.
- Routes (`main.py`):

| Method & path | Body / params | Returns |
|---|---|---|
| `POST /api/inspect` | multipart `data_file`, `sales_file` | `InspectResponse` |
| `POST /api/runs` | multipart `data_file`, `sales_file`, optional form `plan_date` | `RunRecord` |
| `GET /api/runs`, `GET /api/runs/{id}` | | as v1 |
| `POST /api/runs/{id}/recalculate` | | `RunRecord`, using current holdings and the same plan date, updated in place |
| `GET /api/runs/{id}/suppliers` | (no window) | `list[SupplierSummary]` |
| `GET /api/settings` | | `list[SupplierSettingView]`: every supplier in the latest run **plus** any saved supplier, sorted by name; holding null when not set |
| `PUT /api/settings` | `list[SupplierHolding]` | `list[SupplierSettingView]` |
| `GET /api/settings/log` | | `list[SettingsLogEntry]` |

- Errors:
  - A Data-file `InputFileError` gives 400 with the detail prefixed "Data file: ".
  - A sales-export `InputFileError` gives 400 with the detail prefixed "Sales export: ".
  - An invalid plan date gives 422, as in v1.
  - Holding validation gives 422 with detail `"Supplier '{name}': holding must be between 0.5 and 24 months, or blank."`. A value is valid if it is null or a number with 0.5 ≤ v ≤ 24.

- [ ] **Step 1: Write the failing tests**

```python
# test_api.py (new)
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from app.main import create_app

FIX = Path(__file__).parent / "fixtures"
DATA, SALES = (FIX / "sample_input.xlsx").read_bytes(), (FIX / "sales_export.xlsx").read_bytes()

@pytest.fixture
def client(tmp_path): return TestClient(create_app(tmp_path / "t.db"))

def files(data=DATA, sales=SALES):
    return {"data_file": ("data.xlsx", data), "sales_file": ("sales.xlsx", sales)}

def test_inspect_reports_months_and_coverage(client):
    r = client.post("/api/inspect", files=files()).json()
    assert r["actual_months"] == ["2026-07", "2026-08", "2026-09"]
    assert r["forecast_window"] == ["2026-10", "2026-11", "2026-12"]
    assert r["sku_count"] == 212 and r["skus_with_sales"] == 141 and r["sales_file_name"] == "sales.xlsx"

def test_new_run_blocks_all_suppliers_until_holding_set(client):
    run = client.post("/api/runs", files=files()).json()
    assert run["result"]["counts"]["HOLDING_NOT_SET"] == 212
    assert len(run["result"]["blocked_suppliers"]) == 17
    s = client.get("/api/settings").json()
    assert len(s) == 17 and all(x["holding_months"] is None for x in s)

def test_set_holding_recalculates_real_sku(client):
    run = client.post("/api/runs", files=files()).json()
    assert client.put("/api/settings", json=[{"supplier": "CFC", "holding_months": 3}]).status_code == 200
    rec = client.post(f"/api/runs/{run['id']}/recalculate").json()
    sku = next(x for x in rec["result"]["skus"] if x["sap_code"] == "3102111001")
    # actuals 2113/40, 1451/40, 1647/40; forecast 55, 55, 55 -> buffer 49.2125
    assert sku["buffer"] == pytest.approx(49.2125)
    assert sku["target"] == pytest.approx(147.6375) and sku["available"] == pytest.approx(38.15)
    assert sku["order_qty"] == 110 and sku["status"] == "TO_ORDER"
    assert sku["next_calc_date"] == "2026-10-19"
    log = client.get("/api/settings/log").json()
    assert log[0]["supplier"] == "CFC" and log[0]["old_value"] is None and log[0]["new_value"] == 3

def test_holding_validation(client):
    for bad in (0, 25, "abc"):
        assert client.put("/api/settings", json=[{"supplier": "A", "holding_months": bad}]).status_code == 422
    assert client.put("/api/settings", json=[{"supplier": "A", "holding_months": None}]).status_code == 200

def test_swapped_files_return_400(client):
    r = client.post("/api/inspect", files=files(data=SALES, sales=DATA))
    assert r.status_code == 400 and r.json()["detail"].startswith("Data file:")
    r = client.post("/api/runs", files=files(sales=DATA))
    assert r.status_code == 400 and r.json()["detail"].startswith("Sales export:")

def test_plan_date_range_and_404s(client):
    assert client.post("/api/runs", files=files(), data={"plan_date": "2026-11-02"}).status_code == 422
    assert client.get("/api/runs/999").status_code == 404
    assert client.post("/api/runs/999/recalculate").status_code == 404
```

`test_summary.py`: one test. Run `plan_all` on the real fixtures with holdings `{"CFC": 3}` and assert:
- CFC: `sku_count == 5`, `holding_months == 3`, `blocked_skus == 0`, and `total_order_qty` equal to the sum of its SKUs' `order_qty`;
- every other supplier has `blocked_skus == sku_count`;
- CFC sorts first.

`test_holding.py`: add `test_plan_all_counts_and_zero_forecast`, using the real fixtures with no holdings. Assert:
- `counts["HOLDING_NOT_SET"] == 212`;
- `counts["ZERO_FORECAST"]` equals the number of SKUs with `zero_forecast` true, and is > 0;
- `forecast_months == ["2026-10","2026-11","2026-12"]`.

- [ ] **Step 2: Run the tests to verify they fail.** Run the three files.

- [ ] **Step 3: Implement**

- Wire `main.py` to v2.
- Rewrite `summary.py`.
- Delete the v1 modules and tests, and remove v1 models and config constants.
- `export.py`: make it compile against v2 with a stub that raises `NotImplementedError`, mark `test_export.py` with `pytest.skip("rewritten in Task 5")`, and keep the export route returning 501. Task 5 replaces all three.

- [ ] **Step 4: Run all backend tests.** Expected: all pass, with test_export skipped.

- [ ] **Step 5: Commit** `feat: switch API and supplier summary to holding-based plan`

---

### Task 5: Excel export for v2

**Files:**
- Modify: `backend/app/export.py`, `backend/app/main.py` (route), `backend/tests/test_export.py`

**Interfaces:**
- Consumes: `RunRecord` (v2), `summarize_suppliers`, `month_label`.
- Produces: `build_export(run: RunRecord) -> bytes` and the route `GET /api/runs/{id}/export`, with the filename unchanged (`order-plan-<plan_date>-run<id>.xlsx`) and no `window_weeks`.
- Sheets and columns, in this order:
  - **`SKU Plan`**:
    - Supplier, SAP Code, Description, Status, Zero Forecast (Yes/No), Sellable, SIT, Available;
    - one column per actual month labelled `"{month_label} Actual"` and one per forecast month labelled `"{month_label} Forecast"` (blank when value is None);
    - Valid Values, Buffer, Holding (months), Target, Required, MOQ, MOQ Applied (Yes/No), Order Qty, Stock Cover (months), Lead Time (days), Next Calculation Date.
  - **`Supplier Summary`**: Supplier, Holding (months), SKUs, SKUs to Order, Total Order Qty, Blocked SKUs, No Demand SKUs, Zero Forecast SKUs.
  - **`Settings Used`**: Supplier, Holding (months) (blank = not set).
  - **`Warnings`**: Source (`Data file` / `Sales export`), SAP Code, Column, Message.
- Keep v1's header styling (bold, frozen) and real Excel dates.
- Prefix any string cell starting with `=`, `+`, `-` or `@` with `'`. Strip characters that openpyxl rejects (`openpyxl.utils.exceptions.IllegalCharacterError`; use `openpyxl.cell.cell.ILLEGAL_CHARACTERS_RE`).

- [ ] **Step 1: Write the failing test** `test_export_v2_sheets_and_values`. It uses the TestClient from Task 4's fixtures, sets CFC holding to 3, creates a run, downloads the export, and asserts:
  - sheet names equal the list above;
  - `SKU Plan` has 213 rows;
  - the header contains `"Jul 2026 Actual"` and `"Dec 2026 Forecast"`;
  - the row for `3102111001` has Order Qty 110 and Status `TO_ORDER`;
  - `Warnings` has a header row only, since the real files produce no warnings.

  Also add `test_export_neutralises_formula_text`: a SKU description `"=SUM(A1)"` is written as `"'=SUM(A1)"`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run all backend tests.** Expected: all pass, with nothing skipped.
- [ ] **Step 5: Commit** `feat: v2 Excel export`

---

### Task 6: Frontend types, API client and two-file upload page

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/pages/UploadPage.tsx`, `frontend/src/lib/format.ts` (add `monthLabel`)

**Interfaces:**
- Consumes: the Task 4/5 API.
- Produces:
  - `types.ts` mirrors every v2 model in `models.py` field for field: `SkuStatus` (a union of the 4 values), `DemandValue`, `SkuResult`, `HoldingPlan`, `ActualSales` (`SalesExport` stays backend-only), `SupplierHolding`, `SettingsLogEntry`, `SupplierSummary`, `SupplierSettingView`, `RunListItem`, `RunRecord` and `InspectResponse`. Remove the v1 types.
  - `api.ts`:
    - `inspectFiles(dataFile: File, salesFile: File)`, `createRun(dataFile: File, salesFile: File, planDate?: string)`, `getRun`, `listRuns`, `recalculate`;
    - `getSupplierSummary(id: number)` (no weeks);
    - `getSettings()`, `saveSettings(items: SupplierHolding[])`, `getSettingsLog()`;
    - `exportUrl(id: number)`.
  - `format.ts`: `monthLabel(key: string): string` (`"2026-07"` → `"Jul 2026"`), with a test in `format.test.ts`.
- Upload page:
  - Two labelled pickers, "Data file (.xlsx)" and "Sales export (.xlsx)". Inspect runs when both are chosen, and again when either changes; ignore a stale response by checking that the files are still the current ones.
  - Show:
    - SKU and supplier counts;
    - "Actual months: Jul 2026 – Sep 2026";
    - "Forecast months: Oct 2026 – Dec 2026";
    - "{skus_with_sales} of {sku_count} SKUs have actual sales";
    - the plan date input with min/max and the existing "Stock figures are as of …" note;
    - combined warnings.
  - Calculate is disabled until inspect succeeds. It calls `createRun` and navigates to `/runs/{id}`.
  - Show errors inline. Their detail already names the file.

- [ ] **Step 1:** Add the `monthLabel` test (`expect(monthLabel('2026-07')).toBe('Jul 2026')`) and run `npm --prefix frontend test`. Expected: FAIL.
- [ ] **Step 2:** Implement the types, API client, `monthLabel` and UploadPage. The other pages may fail type-check until Tasks 7–8. To keep `npm run build` green in this task, give the other pages a minimal placeholder render ("Being updated for holding-based plans"), and replace them in Tasks 7–8.
- [ ] **Step 3:** `npm --prefix frontend test`, `npm --prefix frontend run build` and `npm --prefix frontend run lint` all pass.
- [ ] **Step 4:** Manual check. Start both servers with `ORDERPLAN_DB` set to a temp file. Use curl through the Vite proxy to `/api/inspect` with both fixtures (field names `data_file` and `sales_file`), and confirm 141 SKUs with sales. Stop only the processes you started, by PID.
- [ ] **Step 5: Commit** `feat: two-file upload and v2 frontend types`

---

### Task 7: Order plan page and SKU detail

**Files:**
- Modify: `frontend/src/lib/filters.ts` (+ `filters.test.ts`), `frontend/src/lib/format.ts` (+ test), `frontend/src/pages/PlanPage.tsx`, `frontend/src/components/SkuDetail.tsx`
- Rename: `frontend/src/components/FlagChips.tsx` → `StatusChip.tsx`
- Delete: `frontend/src/lib/useWeeksInput.ts`; remove `recharts` from `package.json`

**Interfaces:**
- Produces (`filters.ts`):
  - `interface SkuFilter { supplier: string | null; status: SkuStatus | null; zeroForecastOnly: boolean; search: string }`
  - `filterSkus(skus: SkuResult[], f: SkuFilter): SkuResult[]`, sorted by status order (`TO_ORDER`, `HOLDING_NOT_SET`, `NO_DEMAND_DATA`, `NO_ORDER_NEEDED`), then `order_qty` descending (null last), then supplier, then description.
- Produces (`format.ts`):
  - `statusLabel(s: SkuStatus): string`: "To order", "No order needed", "Holding not set", "No demand data".
  - `orderExplanation(r: SkuResult): string[]`: one line per calculation step, built only from the stored numbers and using `fmtQty`. For the spec's worked example it returns exactly:
    - `"Buffer = (100 + 120 + 110 + 130 + 140 + 120) ÷ 6 = 120 a month"`
    - `"Target = 120 × 3 months = 360"`
    - `"Available = 200 sellable + 60 SIT = 260"`
    - `"Required = 360 − 260 = 100"`
    - `"MOQ check: 100 is below the MOQ of 150, so the order is 150"`
    - `"Stock cover = 260 ÷ 120 = 2.2 months"`
    - `"Next calculation date = 14 Oct 2026 + 61 days lead time = 14 Dec 2026"`
  - Edge cases:
    - Skipped values are left out of the sum, and the divisor is `valid_count`.
    - When holding is not set, the Target/Required/MOQ lines are replaced by `"Holding not set for {supplier} — no order calculated"`.
    - With no demand data the result is `["No valid demand values (all 6 months are zero, negative or missing)"]`.
    - When required is 0: `"Required = 0 (available already covers the target)"`.
    - When MOQ is 0 or not applied, the MOQ line is omitted.
    - With lead time missing, the last line is `"Next calculation date: no lead time"`.
- Plan page:
  - Header: plan date, the "{file} + {sales file}" names, and buttons for Supplier summary, Recalculate and Export.
  - Count cards: To order, Holding not set, No demand data and Zero forecast. Clicking a card sets the matching filter (status, or `zeroForecastOnly` for Zero forecast); clicking it again clears it.
  - Blocked banner, shown when `blocked_suppliers` is non-empty: "{N} suppliers have no holding set, so their SKUs are not calculated — set holding in Supplier settings", with a link.
  - Filters: supplier select, status select, "Zero forecast only" checkbox, search box.
  - Table columns:
    - Supplier, SAP Code, Description, Available, Buffer, Valid, Holding;
    - Target, Order qty (with an "MOQ" tag when `moq_applied`), Stock cover (one decimal, then "mo");
    - Next calc date, Status (chip, plus a "Zero forecast" chip when flagged).
    - The Valid column shows "n/6".
  - SkuDetail panel: a 6-row table (Month, Source, Value, Valid ✓/✗), the `orderExplanation` lines, lead time, MOQ, packing size, and any warnings for this SAP code from `run.parsed.warnings` and `run.actual.warnings`.
  - Keep v1's patterns for the run-loading effect cancellation, the recalculate race guard and resetting filters per run.

- [ ] **Step 1: Write the failing tests:**
  - `filters.test.ts`: sort order, each filter, and `zeroForecastOnly`;
  - `format.test.ts`: `orderExplanation` for the worked example (exact strings above), holding not set, no demand data, required 0, and lead time missing.
- [ ] **Step 2:** `npm --prefix frontend test`. Expected: FAIL.
- [ ] **Step 3:** Implement. `npm uninstall recharts --prefix frontend`.
- [ ] **Step 4:** test, build and lint all pass.
- [ ] **Step 5: Commit** `feat: holding-based order plan page and SKU detail`

---

### Task 8: Supplier summary, holding settings and change log pages

**Files:**
- Modify: `frontend/src/pages/SupplierPage.tsx`, `frontend/src/pages/SettingsPage.tsx`, `frontend/src/lib/settings.ts` (+ `settings.test.ts`)

**Interfaces:**
- Produces (`settings.ts`, replacing `validateSetting`/`changedSettings`):
  - `validateHolding(text: string): { value: number | null; error: string | null }`:
    - blank → `{value: null, error: null}`;
    - a number from 0.5 to 24 (decimals allowed) → the value;
    - otherwise the error `"Holding must be a number from 0.5 to 24 months, or blank."`
  - `changedHoldings(original: SupplierSettingView[], edited: Record<string, number | null>): SupplierHolding[]`: only the rows whose value differs.
- Supplier page:
  - Table: Supplier, Holding (or a "not set" tag), SKUs, SKUs to order, Total order qty, Blocked, No demand, Zero forecast.
  - Expanding a supplier lists its SKUs with `order_qty > 0` (SAP code, description, order qty with MOQ tag, next calc date), which is the list for one purchase order.
  - No weeks input.
- Settings page:
  - Table: Supplier, SKUs, Max lead time (days), Holding (months) as a text input.
  - Rows with null holding are highlighted "Holding not set — SKUs blocked".
  - Inline errors come from `validateHolding`. Save is disabled while there is an error or no change.
  - Save sends `changedHoldings`, reloads from the response, recalculates the latest run, and shows "Saved. Plan for {file} recalculated." with a link (or "Saved." when there are no runs).
  - Below the table, a **Change log** section shows `getSettingsLog()` with columns When, Supplier, From and To ("not set" for null). It is refreshed after each save.
  - The intro text, verbatim: "Holding is how many months of stock to keep for each supplier. Order = average monthly demand × holding − (sellable + SIT). Lead time does not change the order quantity."

- [ ] **Step 1: Write the failing tests** in `settings.test.ts`:
  - `validateHolding`: `''` → null; `'1.5'` → 1.5; `'0.5'` and `'24'` are OK; `'0'`, `'25'` and `'abc'` give the error.
  - `changedHoldings`: one changed row, one unchanged null row, and one cleared row (3 → null) included as null.
- [ ] **Step 2:** `npm --prefix frontend test`. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** test, build and lint all pass.
- [ ] **Step 5: Commit** `feat: holding settings with change log and v2 supplier summary`

---

### Task 9: README and end-to-end check

**Files:**
- Modify: `README.md`

- [ ] **Step 1:** Update the README:
  - **Uploads:** two uploads, and what admin's sales export must contain (headers `itemCode`, `Year`, `Month`, `Qty`; one row per branch, item and month; Qty in pieces; the 3 months before the MTD month).
  - **Calculation:** the steps with the spec's worked example.
  - **Holding settings:** blocked suppliers and the change log.
  - **v1 database:** the backup behaviour.
  - **Known limitations:**
    - no order tracking;
    - stock in transit counts as available;
    - lead time does not change the order quantity;
    - no minimum number of valid values.
  - **Removed v1 concepts:** reorder/target days, future orders and the stock chart.
- [ ] **Step 2:** Run every check from the project root: backend pytest, `npm --prefix frontend test`, `npm --prefix frontend run build`, `npm --prefix frontend run lint`. All pass.
- [ ] **Step 3:** Start both servers with `ORDERPLAN_DB` pointing to a temp file. Through the proxy, run inspect, create a run, PUT CFC holding 3, recalculate, and download the export. Confirm that SKU `3102111001` has order 110, and stop only your processes. (The controller does the browser click-through.)
- [ ] **Step 4: Commit** `docs: README for holding-based order plan`
