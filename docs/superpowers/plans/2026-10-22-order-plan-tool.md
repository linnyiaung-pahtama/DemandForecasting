# Order Plan Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web tool that reads the planner's "Local Principals data" Excel file and calculates a per-SKU order plan (order date, cartons, arrival) using per-supplier reorder/target levels, with supplier summary, run history and Excel export.

**Architecture:** A Python FastAPI backend holds all logic: an input parser for the `Data` sheet, a daily demand series, a per-SKU simulation engine, supplier summaries, SQLite persistence (settings + runs stored as JSON) and an Excel exporter. A React (Vite + TypeScript) frontend is a thin client over a JSON API under `/api`, proxied to the backend in development.

**Tech Stack:** Python 3.12, FastAPI ≥0.115, Pydantic v2, uvicorn, python-multipart, openpyxl ≥3.1, sqlite3 (stdlib), pytest, httpx. Node 22, React 18, TypeScript, Vite, react-router-dom 6, recharts 2, vitest + @testing-library/react + jsdom.

**Spec:** `docs/superpowers/specs/2026-10-22-order-plan-tool-design.md`. Read it before starting any task.

## Global Constraints

- Runs locally on Windows. Backend on `127.0.0.1:8000`, frontend dev server on `localhost:5173` proxying `/api` to the backend.
- Only the `Data` sheet of the input workbook is read. Every other sheet is ignored.
- Quantities are cartons. There are no money values anywhere.
- One order quantity per SKU. There is no Yangon/Mandalay split.
- Reorder and target levels are per supplier, in days of sales, and **both include lead time**.
- Defaults for a supplier without saved settings: reorder **20** days, target **30** days, `is_default = true`.
- Excess flag threshold: days of cover today > target days × **1.5**.
- Shelf life in days = `round(months × 365 / 12)`. `-`, blank or `0` means unknown (no cap).
- MOQ is a minimum (0 = none), not a multiple. Order quantities are whole cartons, rounded up.
- Sales missed during a stock-out are lost: on-hand stock never goes below 0 in the projection.
- JSON field names are snake_case on both sides. The frontend types mirror the Pydantic models exactly.
- Cleaning of input values is never silent: every coerced value produces a `ParseWarning`.

## Review Focus

1. **Next cycle's file.** Headers move, e.g. `Nov'26 MTD Sale (1-8 Nov)` with forecasts `2026 Nov IMS` … `2027 Oct IMS`, extra spaces or column order changes. The parser must detect these by pattern, not position. Pinned by `test_detects_columns_by_pattern_in_next_cycle_file` (Task 1).
2. **Supplier names with stray spaces** (the old workbook has `"Honesty  "`). These must map to one supplier setting, not two. Pinned by `test_supplier_names_are_trimmed` (Task 1).
3. **Formula cells with no cached value or text in number columns.** Expect 0 plus a warning, not a crash. Pinned by `test_blank_and_text_numbers_become_zero_with_warning` (Task 1).
4. **Wrong file uploaded** (the old `.xlsb`, a workbook without `Data`, a CSV). Expect HTTP 400 with a readable message, never 500. Pinned by `test_upload_wrong_file_returns_400` (Task 6).
5. **Plan date overridden** to a day inside the MTD period or outside the forecast horizon. Expect HTTP 422 with the allowed range. Pinned by `test_plan_date_outside_allowed_range_returns_422` (Task 6).

---

## File Structure

```
DemandForecasting/
  .gitignore
  README.md                          # how to install and run (Task 11)
  .claude/launch.json                # preview configs (Task 11)
  backend/
    requirements.txt
    pytest.ini
    app/
      __init__.py
      config.py        # constants: defaults, excess factor, DB path
      models.py        # all Pydantic models + FlagCode enum
      parsing.py       # parse_input(): Data sheet -> ParsedInput
      demand.py        # DemandSeries + build_demand()
      engine.py        # plan_sku(), plan_all()
      summary.py       # summarize_suppliers()
      db.py            # connect(), init_schema()
      repository.py    # Repository: settings + runs
      export.py        # build_export() -> xlsx bytes
      main.py          # create_app(), routes
    tests/
      fixtures/sample_input.xlsx   # copy of the planner's sample file
      helpers.py                   # make_workbook() for synthetic inputs
      test_parsing.py test_demand.py test_engine.py test_summary.py
      test_repository.py test_api.py test_export.py
  frontend/
    (Vite react-ts scaffold)
    vite.config.ts
    src/
      main.tsx App.tsx index.css
      types.ts          # mirrors backend models
      api.ts            # fetch wrappers
      lib/filters.ts    # filterSkus(), nextOrder()
      lib/settings.ts   # validateSetting()
      lib/format.ts     # fmtQty(), fmtDate(), flagLabel()
      pages/UploadPage.tsx PlanPage.tsx SupplierPage.tsx SettingsPage.tsx HistoryPage.tsx
      components/SkuDetail.tsx FlagChips.tsx
      lib/filters.test.ts lib/settings.test.ts
```

---

### Task 1: Project setup, models and input parser

**Files:**
- Create: `.gitignore`, `backend/requirements.txt`, `backend/pytest.ini`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/models.py`, `backend/app/parsing.py`
- Create: `backend/tests/__init__.py`, `backend/tests/helpers.py`, `backend/tests/test_parsing.py`, `backend/tests/fixtures/sample_input.xlsx`

**Interfaces:**
- Produces (`models.py`):
  - `class SkuInput(BaseModel)`: `sap_code: str`, `supplier: str`, `description: str`, `packing_size: float | None`, `moq: float`, `shelf_life_months: float | None`, `lead_time_days: int | None`, `sellable: float`, `non_sellable: float`, `sit: float`, `mtd_sales: float` (raw value, may be negative), `forecast: dict[str, float]` (key `"YYYY-MM"`, ordered by month).
  - `class ParseWarning(BaseModel)`: `sap_code: str | None`, `column: str | None`, `message: str`
  - `class ParsedInput(BaseModel)`: `skus: list[SkuInput]`, `forecast_months: list[str]`, `mtd_month: str` (`"YYYY-MM"`), `mtd_label: str` (header text), `mtd_end: date`, `default_plan_date: date`, `warnings: list[ParseWarning]`
  - `class InputFileError(Exception)`: message is shown to the user.
- Produces (`parsing.py`): `parse_input(data: bytes) -> ParsedInput`
- Produces (`config.py`): `DEFAULT_REORDER_DAYS = 20`, `DEFAULT_TARGET_DAYS = 30`, `EXCESS_FACTOR = 1.5`, `DB_PATH = Path(__file__).resolve().parent.parent / "data" / "orderplan.db"` (overridable by env var `ORDERPLAN_DB`).
- Produces (`tests/helpers.py`): `make_workbook(rows: list[list], headers: list[str] | None = None, sheet: str = "Data") -> bytes` builds an xlsx in memory with row 1 empty, row 2 totals (blank), row 3 headers, data from row 4. The default headers are 23 columns in this order: `SAP Code`, `By Principal`, `Description`, `Packing Size`, `MOQ`, `Shelf Life month`, `Lead Time`, `Total Sellable (Ctns)`, `Total Non-Sellable (Ctns)`, `SIT Ctns (pending order) `, `Oct'26  MTD Sale (1-11 Oct)`, then `2026 Oct IMS` … `2027 Sep IMS`. So a test row is `[sap, supplier, desc, pack, moq, shelf, lead, sellable, non_sellable, sit, mtd] + 12 forecasts`.

- [ ] **Step 1: Set up the repository and backend environment**

Run in `C:\projects\DemandForecasting`:
```bash
git init
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install fastapi "uvicorn[standard]" python-multipart openpyxl pydantic pytest httpx
backend/.venv/Scripts/python -m pip freeze > backend/requirements.txt
cp "C:/Users/linnyiaung/Downloads/Local Principals data for Demand Forecasting Tool.xlsx" backend/tests/fixtures/sample_input.xlsx
```
`.gitignore`: `backend/.venv/`, `backend/data/`, `__pycache__/`, `.pytest_cache/`, `frontend/node_modules/`, `frontend/dist/`.
`pytest.ini`: `[pytest]` with `testpaths = tests` and `pythonpath = .`.
Expected: `backend/.venv/Scripts/python -m pytest` runs (0 tests collected).

- [ ] **Step 2: Write the failing tests** in `backend/tests/test_parsing.py`

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_parsing.py -v`
Expected: FAIL (`ModuleNotFoundError: app.parsing`).

- [ ] **Step 4: Implement `models.py`, `config.py`, `tests/helpers.py` and `parse_input(data: bytes) -> ParsedInput`**

Approach:
- `openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=True)`. Wrap any load exception as `InputFileError("Could not read the file as an Excel .xlsx workbook.")`. A missing `Data` sheet gives `InputFileError("The workbook has no 'Data' sheet.")`.
- Find the header row as the first of rows 1–10 containing a cell whose normalized text is `sap code`. Normalize headers by collapsing whitespace runs to one space, stripping, and casefolding.
- Required fixed columns (normalized match): `SAP Code`, `By Principal`, `Description`, `Packing Size`, `MOQ`, `Shelf Life month`, `Lead Time`, `Total Sellable (Ctns)`, `Total Non-Sellable (Ctns)`, `SIT Ctns (pending order)`. If any are missing, raise `InputFileError` listing the missing names.
- MTD column regex on the normalized header: `^([a-z]{3})'(\d{2}) mtd sale \((\d{1,2})-(\d{1,2}) ([a-z]{3})\)$`. The year is `2000 + group 2`, the month comes from group 1, and `mtd_end` is that month on day group 4. `default_plan_date = mtd_end + 1 day`. Forecast regex: `^(\d{4}) ([a-z]{3}) ims$`. The file needs exactly one MTD column and at least one forecast column, otherwise `InputFileError`. Sort forecast months chronologically.
- Rows: skip a row whose SAP Code is blank. SAP Code is `str(int(v))` for a numeric value, otherwise `str(v).strip()`. Supplier and description are stripped.
- Numbers: `None`, empty string or non-numeric gives `0.0` plus a `ParseWarning(column=<original header>, message="empty or non-numeric value treated as 0")`. The warning column uses the header text as in the file with whitespace collapsed (e.g. `"SIT Ctns (pending order)"`).
- Shelf life: `-` or blank gives `None` silently. `0` gives `None` plus warning `"shelf life 0 treated as unknown (no cap)"`.
- Lead time: missing or non-numeric gives `None` plus a warning. Otherwise `int(round(v))`.
- Negative MTD: keep the raw value and add warning `"negative MTD sales (returns) treated as 0"`.
- A duplicate SAP Code keeps the first row and adds warning `"duplicate SAP Code; later row ignored"`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_parsing.py -v`
Expected: all PASS. If the sample counts differ (212 / 17 / 46 / 3 / 10), inspect the fixture before changing the test. These counts were measured from the sample on 2026-10-22.

- [ ] **Step 6: Commit**

```bash
git add .gitignore backend
git commit -m "feat: parse Data sheet of planner input file"
```

---

### Task 2: Daily demand series

**Files:**
- Create: `backend/app/demand.py`, `backend/tests/test_demand.py`

**Interfaces:**
- Consumes: `SkuInput`, `ParsedInput.forecast_months`, `ParsedInput.mtd_month` (Task 1).
- Produces:
  - `@dataclass class DemandSeries`: `daily: list[float]` (index 0 = plan date, last index = last day of the last forecast month), `tail_rate: float`
    - `horizon -> int` (property, `len(daily)`)
    - `demand(day: int) -> float` (uses `tail_rate` for `day >= horizon`)
    - `cover_qty(day: int, days: int) -> float`: sum of `demand(d)` for `d` in `[day, day+days)`
    - `days_of_cover(day: int, qty: float) -> float | None`: days until `qty` is used up from `day`, fractional within the last day. Returns `None` if `qty` is not used up within `horizon + 3650` days. Returns `0.0` for `qty <= 0`.
  - `build_demand(sku: SkuInput, forecast_months: list[str], mtd_month: str, plan_date: date) -> DemandSeries`

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
import pytest
from app.demand import build_demand, DemandSeries
from app.models import SkuInput

def sku(mtd, fc):
    return SkuInput(sap_code="1", supplier="S", description="d", packing_size=1, moq=0,
                    shelf_life_months=None, lead_time_days=7, sellable=0, non_sellable=0,
                    sit=0, mtd_sales=mtd, forecast=fc)

FC = {"2026-10": 310, "2026-11": 300}
MONTHS = ["2026-10", "2026-11"]

def test_current_month_spreads_remaining_after_mtd():
    d = build_demand(sku(110, FC), MONTHS, "2026-10", date(2026, 10, 12))
    assert d.horizon == 20 + 30
    assert d.daily[0] == pytest.approx(10) and d.daily[19] == pytest.approx(10)
    assert d.daily[20] == pytest.approx(10)   # Nov 300/30
    assert d.tail_rate == pytest.approx(10)

def test_negative_mtd_treated_as_zero():
    d = build_demand(sku(-5, FC), MONTHS, "2026-10", date(2026, 10, 12))
    assert d.daily[0] == pytest.approx(15.5)

def test_mtd_above_forecast_leaves_zero_for_rest_of_month():
    d = build_demand(sku(400, FC), MONTHS, "2026-10", date(2026, 10, 12))
    assert sum(d.daily[:20]) == 0 and d.daily[20] == pytest.approx(10)

def test_plan_date_in_later_month_drops_earlier_months_and_mtd():
    d = build_demand(sku(110, FC), MONTHS, "2026-10", date(2026, 11, 16))
    assert d.horizon == 15 and d.daily[0] == pytest.approx(10)

def test_cover_qty_uses_tail_rate_beyond_horizon():
    d = DemandSeries(daily=[10.0] * 50, tail_rate=10.0)
    assert d.cover_qty(45, 10) == pytest.approx(100)

def test_days_of_cover():
    d = DemandSeries(daily=[10.0] * 50, tail_rate=10.0)
    assert d.days_of_cover(0, 250) == pytest.approx(25.0)
    assert d.days_of_cover(0, 255) == pytest.approx(25.5)
    assert DemandSeries(daily=[0.0] * 50, tail_rate=0.0).days_of_cover(0, 10) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_demand.py -v`
Expected: FAIL (`ModuleNotFoundError: app.demand`).

- [ ] **Step 3: Implement `build_demand` and `DemandSeries`**

Rules (spec §9 step 2):
- Skip months that end before `plan_date`.
- For the plan date's month: if it equals `mtd_month`, the remaining demand `max(fc − max(mtd, 0), 0)` is spread evenly over the days from `plan_date` to month end. Otherwise use `fc / days_in_month` for each day from `plan_date` to month end.
- Later months: `fc / days_in_month` for each day.
- `tail_rate` = last forecast month's quantity divided by its day count.
- Use `calendar.monthrange` for days in month.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_demand.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/demand.py backend/tests/test_demand.py
git commit -m "feat: daily demand series from monthly forecast"
```

---

### Task 3: Per-SKU ordering engine

**Files:**
- Modify: `backend/app/models.py` (add output models)
- Create: `backend/app/engine.py`, `backend/tests/test_engine.py`

**Interfaces:**
- Consumes: `SkuInput` (Task 1), `DemandSeries` (Task 2).
- Produces (`models.py`):
  - `class SupplierSetting(BaseModel)`: `supplier: str`, `reorder_days: int`, `target_days: int`, `is_default: bool = False`
  - `class FlagCode(str, Enum)`: `ORDER_NOW`, `STOCKOUT_RISK`, `EXCESS`, `EXPIRY_RISK`, `NO_FORECAST_HOLDING_STOCK`, `MTD_ABOVE_FORECAST`, `LEAD_TIME_EXCEEDS_REORDER`, `MOQ_EXCEEDS_SHELF_LIFE`, `MISSING_LEAD_TIME`
  - `class Flag(BaseModel)`: `code: FlagCode`, `message: str`
  - `class OrderReason(BaseModel)`: `on_hand: float`, `on_order: float`, `inventory_position: float`, `reorder_qty: float`, `target_qty: float`, `raw_qty: float`, `moq_applied: bool`, `shelf_life_cap: float | None`, `cap_applied: bool`
  - `class PlannedOrder(BaseModel)`: `order_date: date`, `arrival_date: date`, `qty: int`, `reason: OrderReason`
  - `class WeekProjection(BaseModel)`: `week: int` (1-based), `start: date`, `end: date`, `demand: float`, `arrivals: float`, `closing_stock: float`, `lost: float`, `reorder_qty: float`, `target_qty: float` (both at week start)
  - `class SkuPlan(BaseModel)`: `sap_code`, `supplier`, `description: str`, `lead_time_days: int | None`, `moq: float`, `shelf_life_months: float | None`, `sellable`, `non_sellable`, `sit`, `starting_stock: float`, `days_of_cover: float | None`, `total_forecast: float`, `orders: list[PlannedOrder]`, `weeks: list[WeekProjection]`, `flags: list[Flag]`, `stockout_days: int`, `stockout_qty: float`, `first_stockout_date: date | None`
- Produces (`engine.py`): `plan_sku(sku: SkuInput, setting: SupplierSetting, demand: DemandSeries, plan_date: date, current_month_forecast: float = 0.0) -> SkuPlan`. In this task, flags are left empty except `ORDER_NOW`, `STOCKOUT_RISK` and `MOQ_EXCEEDS_SHELF_LIFE`; Task 4 adds the rest.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date, timedelta
import pytest
from app.demand import DemandSeries
from app.engine import plan_sku
from app.models import SkuInput, SupplierSetting, FlagCode

PD = date(2026, 10, 12)
def day(n): return PD + timedelta(days=n)

def run(sellable, sit=0, lt=7, moq=0, shelf=None, reorder=20, target=30, daily=10.0, h=60):
    sku = SkuInput(sap_code="1", supplier="S", description="d", packing_size=1, moq=moq,
                   shelf_life_months=shelf, lead_time_days=lt, sellable=sellable,
                   non_sellable=0, sit=sit, mtd_sales=0, forecast={"2026-10": 1})
    return plan_sku(sku, SupplierSetting(supplier="S", reorder_days=reorder, target_days=target),
                    DemandSeries(daily=[daily] * h, tail_rate=daily), PD)

def codes(p): return {f.code for f in p.flags}

def test_no_order_when_stock_covers_horizon():
    assert run(1000).orders == []

def test_orders_when_position_drops_below_reorder_level():
    p = run(300)
    o1, o2 = p.orders[0], p.orders[1]
    assert (o1.order_date, o1.arrival_date, o1.qty) == (day(11), day(18), 110)
    assert o1.reason.inventory_position == pytest.approx(190)
    assert o1.reason.reorder_qty == pytest.approx(200) and o1.reason.target_qty == pytest.approx(300)
    assert (o2.order_date, o2.qty) == (day(22), 110)
    assert p.stockout_days == 0

def test_sit_counts_as_available_stock():
    assert run(100, sit=200).orders[0].order_date == day(11)

def test_order_now_and_lost_sales_when_already_low():
    p = run(50, lt=14)
    o = p.orders[0]
    assert (o.order_date, o.arrival_date, o.qty) == (day(0), day(14), 250)
    assert p.stockout_days == 9 and p.stockout_qty == pytest.approx(90)
    assert p.first_stockout_date == day(5)
    assert {FlagCode.ORDER_NOW, FlagCode.STOCKOUT_RISK} <= codes(p)

def test_moq_is_a_minimum():
    o = run(300, moq=500).orders[0]
    assert o.qty == 500 and o.reason.moq_applied

def test_shelf_life_caps_quantity():
    o = run(300, shelf=1, target=60).orders[0]   # shelf 30 days; cap = 300 - (190-70) = 180
    assert o.qty == 180 and o.reason.cap_applied
    assert o.reason.shelf_life_cap == pytest.approx(180)

def test_moq_above_shelf_life_cap_is_flagged():
    p = run(300, shelf=1, target=60, moq=500)
    assert p.orders[0].qty == 500 and FlagCode.MOQ_EXCEEDS_SHELF_LIFE in codes(p)

def test_zero_forecast_never_orders():
    p = run(50, daily=0.0)
    assert p.orders == [] and p.days_of_cover is None

def test_missing_lead_time_never_orders():
    assert run(50, lt=None).orders == []

def test_weekly_projection():
    p = run(300)
    w1, w3 = p.weeks[0], p.weeks[2]
    assert (w1.start, w1.end) == (day(0), day(6))
    assert w1.demand == pytest.approx(70) and w1.closing_stock == pytest.approx(230)
    assert w3.arrivals == pytest.approx(110)       # arrival on day 18
    assert len(p.weeks) == 9                       # 60 days -> 8 full weeks + 1 partial
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_engine.py -v`
Expected: FAIL (`ModuleNotFoundError: app.engine`).

- [ ] **Step 3: Implement `plan_sku`**

The loop (spec §9 steps 3–8). The tests do not fully determine its order of operations, so follow this:
```
on_hand = sellable + sit;  pipeline = []   # (arrival_day, qty)
for d in range(demand.horizon):
    on_hand += arrivals due on d (remove from pipeline)
    position = max(on_hand, 0) + sum(pipeline qty)
    if lead_time is not None and position < demand.cover_qty(d, reorder_days):
        target = demand.cover_qty(d, target_days)
        raw = target - position
        qty = ceil(raw - 1e-9); moq_applied = moq > 0 and qty < moq; qty = max(qty, moq)
        if shelf_days:   # round(months*365/12), None if unknown
            at_arrival = max(position - demand.cover_qty(d, lead_time), 0)
            cap = max(demand.cover_qty(d + lead_time, shelf_days) - at_arrival, 0)
            if qty > cap: if moq > 0 and moq > cap: flag MOQ_EXCEEDS_SHELF_LIFE (keep moq)
                          else: qty = floor(cap); cap_applied = True
        if qty > 0: record PlannedOrder(day(d), day(d + lead_time), qty, reason); pipeline add
    need = demand.demand(d)
    if on_hand >= need: on_hand -= need
    else: lost += need - on_hand; stockout day counted; on_hand = 0
```
- Record per-day values for the weekly buckets (7-day buckets from day 0; the last bucket may be partial).
- `days_of_cover = demand.days_of_cover(0, starting_stock)`.
- `ORDER_NOW` if any order has `order_date == plan_date`.
- `STOCKOUT_RISK` if `stockout_qty > 0`, with a message naming the first stock-out date, the days short and the cartons lost.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_engine.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/engine.py backend/tests/test_engine.py
git commit -m "feat: per-SKU reorder simulation engine"
```

---

### Task 4: Remaining flags, whole-file planning and supplier summary

**Files:**
- Modify: `backend/app/engine.py`, `backend/app/models.py`, `backend/tests/test_engine.py`
- Create: `backend/app/summary.py`, `backend/tests/test_summary.py`

**Interfaces:**
- Consumes: `plan_sku`, `build_demand`, `ParsedInput`, `SupplierSetting`, config constants.
- Produces (`models.py`):
  - `class SupplierSummary(BaseModel)`: `supplier: str`, `reorder_days: int`, `target_days: int`, `is_default: bool`, `sku_count: int`, `skus_to_order: int`, `cartons_in_window: int`, `earliest_order_date: date | None`, `flag_counts: dict[str, int]`, `max_lead_time_days: int | None`
  - `class PlanResult(BaseModel)`: `plan_date: date`, `skus: list[SkuPlan]`, `settings_used: list[SupplierSetting]`, `new_suppliers: list[str]`, `flag_counts: dict[str, int]`
- Produces (`engine.py`):
  - `plan_all(parsed: ParsedInput, settings: dict[str, SupplierSetting], plan_date: date) -> PlanResult`. A supplier missing from `settings` gets `SupplierSetting(supplier, DEFAULT_REORDER_DAYS, DEFAULT_TARGET_DAYS, is_default=True)` and is listed in `new_suppliers`.
  - `validate_plan_date(parsed: ParsedInput, plan_date: date) -> None` raises `ValueError` with a message naming the allowed range: after `mtd_end`, and on or before the last day of the last forecast month.
- Produces (`summary.py`): `summarize_suppliers(result: PlanResult, window_weeks: int = 4) -> list[SupplierSummary]`, sorted by `earliest_order_date` (None last), then supplier name.

- [ ] **Step 1: Write the failing tests** (append to `test_engine.py`; new `test_summary.py`)

```python
# test_engine.py additions (reuse run()/codes() helpers)
def test_flags_lead_time_at_or_above_reorder():
    assert FlagCode.LEAD_TIME_EXCEEDS_REORDER in codes(run(1000, lt=30, reorder=20))
    assert FlagCode.LEAD_TIME_EXCEEDS_REORDER not in codes(run(1000, lt=30, reorder=20, daily=0.0))

def test_flags_excess_and_expiry_risk():
    p = run(1000, shelf=1)                 # 100 days cover > 30*1.5; > 300 sells in 30 days
    assert {FlagCode.EXCESS, FlagCode.EXPIRY_RISK} <= codes(p)
    assert FlagCode.EXCESS not in codes(run(400))   # 40 days <= 45

def test_flags_no_forecast_holding_stock():
    assert FlagCode.NO_FORECAST_HOLDING_STOCK in codes(run(50, daily=0.0))
    assert FlagCode.NO_FORECAST_HOLDING_STOCK not in codes(run(0, daily=0.0))

def test_flags_missing_lead_time():
    assert FlagCode.MISSING_LEAD_TIME in codes(run(50, lt=None))

def test_plan_all_uses_defaults_for_new_supplier_and_flags_mtd_above_forecast():
    from app.engine import plan_all
    from tests.helpers import make_workbook
    from app.parsing import parse_input
    parsed = parse_input(make_workbook([["1001","NewCo","X",12,0,6,7,10,0,0,500] + [310]*12]))
    r = plan_all(parsed, {}, parsed.default_plan_date)
    assert r.new_suppliers == ["NewCo"]
    assert r.settings_used[0].reorder_days == 20 and r.settings_used[0].is_default
    assert FlagCode.MTD_ABOVE_FORECAST in {f.code for f in r.skus[0].flags}
    assert r.flag_counts["MTD_ABOVE_FORECAST"] == 1
    # rest of Oct has zero demand, so the 20-day reorder window first exceeds stock (10) on day 1,
    # when it reaches 1 Nov (310/30 = 10.33)
    assert r.skus[0].orders[0].order_date == date(2026, 10, 13)

def test_validate_plan_date_range():
    from app.engine import validate_plan_date
    from app.parsing import parse_input
    from tests.test_parsing import SAMPLE
    parsed = parse_input(SAMPLE.read_bytes())
    validate_plan_date(parsed, date(2026, 10, 12))
    with pytest.raises(ValueError): validate_plan_date(parsed, date(2026, 10, 11))
    with pytest.raises(ValueError): validate_plan_date(parsed, date(2027, 10, 1))
```

```python
# test_summary.py
from datetime import date
from app.engine import plan_all
from app.parsing import parse_input
from app.summary import summarize_suppliers
from app.models import SupplierSetting
from tests.helpers import make_workbook

def test_summary_counts_orders_in_window():
    rows = [["1","A","low",12,0,None,7,5,0,0,0] + [300]*12,     # orders now
            ["2","A","high",12,0,None,7,5000,0,0,0] + [300]*12, # no order within 4 weeks
            ["3","B","low",12,0,None,7,5,0,0,0] + [300]*12]
    parsed = parse_input(make_workbook(rows))
    settings = {"A": SupplierSetting(supplier="A", reorder_days=20, target_days=30)}
    s = summarize_suppliers(plan_all(parsed, settings, parsed.default_plan_date), window_weeks=4)
    a = next(x for x in s if x.supplier == "A")
    assert a.sku_count == 2 and a.skus_to_order == 1
    assert a.earliest_order_date == parsed.default_plan_date
    assert a.max_lead_time_days == 7 and not a.is_default
    assert next(x for x in s if x.supplier == "B").is_default
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_engine.py tests/test_summary.py -v`
Expected: new tests FAIL.

- [ ] **Step 3: Implement the flags, `plan_all`, `validate_plan_date` and `summarize_suppliers`**

- `LEAD_TIME_EXCEEDS_REORDER`: `lead_time_days >= reorder_days` and the SKU has any forecast demand.
- `EXCESS`: `days_of_cover` is not None and greater than `target_days × EXCESS_FACTOR`.
- `EXPIRY_RISK`: shelf life known and `starting_stock > demand.cover_qty(0, shelf_days)`.
- `NO_FORECAST_HOLDING_STOCK`: `total_forecast == 0` and `starting_stock > 0`.
- `MTD_ABOVE_FORECAST`: `mtd_sales > current_month_forecast > 0`. `plan_all` passes `forecast[mtd_month]`.
- `MISSING_LEAD_TIME`: `lead_time_days is None`.
- `total_forecast` = sum of `daily`.
- `flag_counts` counts SKUs per flag code (keys are the enum values).
- Summary "in window" means `order_date < plan_date + 7 × window_weeks days`. `skus_to_order` counts SKUs with at least one order in the window. `cartons_in_window` sums those orders' `qty`.

- [ ] **Step 4: Run all backend tests**

Run: `cd backend && .venv/Scripts/python -m pytest -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: plan flags, whole-file planning and supplier summary"
```

---

### Task 5: SQLite persistence

**Files:**
- Create: `backend/app/db.py`, `backend/app/repository.py`, `backend/tests/test_repository.py`
- Modify: `backend/app/models.py`

**Interfaces:**
- Produces (`models.py`):
  - `class RunListItem(BaseModel)`: `id: int`, `created_at: datetime`, `file_name: str`, `plan_date: date`, `sku_count: int`
  - `class RunRecord(RunListItem)`: `parsed: ParsedInput`, `result: PlanResult`
- Produces (`db.py`): `connect(db_path: Path) -> sqlite3.Connection` (creates the parent dir and runs `init_schema`).
  Schema:
  `supplier_settings(supplier TEXT PRIMARY KEY, reorder_days INTEGER NOT NULL, target_days INTEGER NOT NULL, is_default INTEGER NOT NULL, updated_at TEXT NOT NULL)`
  `runs(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, file_name TEXT NOT NULL, plan_date TEXT NOT NULL, parsed_json TEXT NOT NULL, result_json TEXT NOT NULL)`
- Produces (`repository.py`): `class Repository(db_path: Path)` with:
  - `get_settings() -> dict[str, SupplierSetting]`
  - `save_settings(items: list[SupplierSetting]) -> None`: upsert. A setting saved through this method has `is_default` stored as given.
  - `add_default_settings(items: list[SupplierSetting]) -> None`: inserts only suppliers not yet present.
  - `create_run(file_name: str, parsed: ParsedInput, result: PlanResult) -> int`
  - `update_run_result(run_id: int, result: PlanResult) -> None`
  - `get_run(run_id: int) -> RunRecord | None`
  - `list_runs() -> list[RunListItem]` (newest first)
  - `latest_run_id() -> int | None`

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from app.repository import Repository
from app.models import SupplierSetting
from app.engine import plan_all
from app.parsing import parse_input
from tests.helpers import make_workbook

def test_settings_round_trip_and_defaults_do_not_overwrite(tmp_path):
    repo = Repository(tmp_path / "t.db")
    repo.save_settings([SupplierSetting(supplier="A", reorder_days=40, target_days=60)])
    repo.add_default_settings([SupplierSetting(supplier="A", reorder_days=20, target_days=30, is_default=True),
                               SupplierSetting(supplier="B", reorder_days=20, target_days=30, is_default=True)])
    s = repo.get_settings()
    assert s["A"].reorder_days == 40 and not s["A"].is_default
    assert s["B"].is_default

def test_run_round_trip(tmp_path):
    repo = Repository(tmp_path / "t.db")
    parsed = parse_input(make_workbook([["1","A","x",12,0,6,7,5,0,0,0] + [300]*12]))
    result = plan_all(parsed, {}, parsed.default_plan_date)
    run_id = repo.create_run("in.xlsx", parsed, result)
    rec = repo.get_run(run_id)
    assert rec.file_name == "in.xlsx" and rec.result == result and rec.parsed == parsed
    assert [r.id for r in repo.list_runs()] == [run_id] and repo.latest_run_id() == run_id
    assert repo.get_run(999) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_repository.py -v`
Expected: FAIL (`ModuleNotFoundError: app.repository`).

- [ ] **Step 3: Implement `db.py` and `Repository`**

Store `parsed` and `result` as `model_dump_json()` and load them with `model_validate_json`. Open one connection per method call (`with connect(...)`), so the repository is safe to use across FastAPI threads. Timestamps are ISO-8601 local time.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_repository.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: SQLite storage for settings and runs"
```

---

### Task 6: HTTP API

**Files:**
- Create: `backend/app/main.py`, `backend/tests/test_api.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `create_app(db_path: Path = config.DB_PATH) -> FastAPI` and module-level `app = create_app()`. Routes (all JSON, snake_case):

| Method & path | Body / params | Returns |
|---|---|---|
| `GET /api/health` | | `{"status": "ok"}` |
| `POST /api/inspect` | multipart `file` | `InspectResponse`: `file_name`, `sku_count`, `supplier_count`, `forecast_months`, `mtd_label`, `default_plan_date`, `min_plan_date`, `max_plan_date`, `warnings` |
| `POST /api/runs` | multipart `file`, optional form `plan_date` (ISO) | `RunRecord` |
| `GET /api/runs` | | `list[RunListItem]` |
| `GET /api/runs/{id}` | | `RunRecord` (404 if missing) |
| `POST /api/runs/{id}/recalculate` | | `RunRecord` recalculated with the current settings and the same plan date, updated in place |
| `GET /api/runs/{id}/suppliers` | query `window_weeks` (int 1–52, default 4) | `list[SupplierSummary]` |
| `GET /api/settings` | | `list[SupplierSettingView]` |
| `PUT /api/settings` | `list[SupplierSetting]` | `list[SupplierSettingView]` |

- `SupplierSettingView(SupplierSetting)` adds `max_lead_time_days: int | None` (from the latest run's SKUs for that supplier) and `sku_count: int`. Sorted by supplier name.
- `POST /api/runs`: parse, then `validate_plan_date`, then `plan_all` with saved settings, then `add_default_settings` for `new_suppliers`, then `create_run`.
- `PUT /api/settings` validation: each value is an int from 1 to 365, and `target_days > reorder_days`. Otherwise 422 with a message naming the supplier. Saved items get `is_default = False`.
- `InputFileError` gives 400 `{"detail": message}`. An invalid plan date gives 422 `{"detail": message}`.
- CORS allows `http://localhost:5173`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from tests.test_parsing import SAMPLE

@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "t.db"))

def upload(client, path="/api/runs", **form):
    return client.post(path, files={"file": ("sample.xlsx", SAMPLE.read_bytes())}, data=form)

def test_inspect_reports_counts_and_dates(client):
    r = upload(client, "/api/inspect").json()
    assert r["sku_count"] == 212 and r["supplier_count"] == 17
    assert r["default_plan_date"] == "2026-10-12" and r["min_plan_date"] == "2026-10-12"
    assert r["max_plan_date"] == "2027-09-30"

def test_create_run_then_fetch_and_list(client):
    run = upload(client).json()
    assert len(run["result"]["skus"]) == 212 and len(run["result"]["new_suppliers"]) == 17
    assert client.get(f"/api/runs/{run['id']}").json()["id"] == run["id"]
    assert client.get("/api/runs").json()[0]["id"] == run["id"]
    assert client.get("/api/runs/999").status_code == 404

def test_settings_change_and_recalculate(client):
    run = upload(client).json()
    s = client.get("/api/settings").json()
    assert len(s) == 17 and all(x["is_default"] for x in s)
    honesty = next(x for x in s if x["supplier"] == "Honesty")
    assert honesty["max_lead_time_days"] is not None
    r = client.put("/api/settings", json=[{"supplier": "Honesty", "reorder_days": 45, "target_days": 60}])
    assert r.status_code == 200
    rec = client.post(f"/api/runs/{run['id']}/recalculate").json()
    used = next(x for x in rec["result"]["settings_used"] if x["supplier"] == "Honesty")
    assert used["reorder_days"] == 45 and not used["is_default"]

def test_settings_validation(client):
    r = client.put("/api/settings", json=[{"supplier": "A", "reorder_days": 30, "target_days": 30}])
    assert r.status_code == 422 and "A" in r.text

def test_supplier_summary_window(client):
    run = upload(client).json()
    s = client.get(f"/api/runs/{run['id']}/suppliers?window_weeks=4").json()
    assert len(s) == 17
    assert client.get(f"/api/runs/{run['id']}/suppliers?window_weeks=0").status_code == 422

def test_upload_wrong_file_returns_400(client):
    r = client.post("/api/runs", files={"file": ("old.xlsb", b"not a workbook")})
    assert r.status_code == 400 and "xlsx" in r.json()["detail"]

def test_plan_date_outside_allowed_range_returns_422(client):
    assert upload(client, plan_date="2026-10-05").status_code == 422
    assert upload(client, plan_date="2027-10-01").status_code == 422
    assert upload(client, plan_date="2026-11-02").status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_api.py -v`
Expected: FAIL (`ModuleNotFoundError: app.main`).

- [ ] **Step 3: Implement `create_app` and the routes** as specified in the table above.

- [ ] **Step 4: Run all backend tests**

Run: `cd backend && .venv/Scripts/python -m pytest -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: HTTP API for inspect, runs, settings and supplier summary"
```

---

### Task 7: Excel export

**Files:**
- Create: `backend/app/export.py`, `backend/tests/test_export.py`
- Modify: `backend/app/main.py` (add route)

**Interfaces:**
- Consumes: `RunRecord`, `summarize_suppliers`.
- Produces: `build_export(run: RunRecord, window_weeks: int = 4) -> bytes`, and the route `GET /api/runs/{id}/export?window_weeks=4`. The route returns the xlsx with `Content-Disposition: attachment; filename="order-plan-<plan_date>-run<id>.xlsx"`.
- Sheets and columns (exact order):
  - `SKU Plan`: Supplier, SAP Code, Description, Sellable, SIT, Non-Sellable, Days of Cover, Lead Time, Next Order Date, Next Order Qty, Next Arrival, Orders in Window (cartons), Flags (codes joined with `, `)
  - `Orders`: Supplier, SAP Code, Description, Order Date, Arrival Date, Qty, Inventory Position, Reorder Qty, Target Qty, MOQ Applied, Shelf-Life Cap
  - `Supplier Summary`: Supplier, Reorder Days, Target Days, Default Settings, SKUs, SKUs to Order, Cartons in Window, Earliest Order Date
  - `Settings Used`: Supplier, Reorder Days, Target Days, Default
  - `Warnings`: SAP Code, Column, Message
  - Dates are written as Excel dates, and the header row is bold and frozen.

- [ ] **Step 1: Write the failing test**

```python
from io import BytesIO
import openpyxl
from fastapi.testclient import TestClient
from app.main import create_app
from tests.test_parsing import SAMPLE

def test_export_has_expected_sheets_and_rows(tmp_path):
    c = TestClient(create_app(tmp_path / "t.db"))
    run = c.post("/api/runs", files={"file": ("s.xlsx", SAMPLE.read_bytes())}).json()
    r = c.get(f"/api/runs/{run['id']}/export")
    assert r.status_code == 200 and "order-plan-2026-10-12" in r.headers["content-disposition"]
    wb = openpyxl.load_workbook(BytesIO(r.content))
    assert wb.sheetnames == ["SKU Plan", "Orders", "Supplier Summary", "Settings Used", "Warnings"]
    assert wb["SKU Plan"].max_row == 213
    assert wb["SKU Plan"]["A1"].value == "Supplier"
    n_orders = sum(len(s["orders"]) for s in run["result"]["skus"])
    assert wb["Orders"].max_row == n_orders + 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_export.py -v`
Expected: FAIL (404 or import error).

- [ ] **Step 3: Implement `build_export` and the route** using openpyxl (write-only is not needed at this size).

- [ ] **Step 4: Run all backend tests**

Run: `cd backend && .venv/Scripts/python -m pytest -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat: Excel export of order plan"
```

---

### Task 8: Frontend scaffold, API client and Upload page

**Files:**
- Create: `frontend/` (Vite react-ts scaffold), `frontend/vite.config.ts`, `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/lib/format.ts`, `frontend/src/App.tsx`, `frontend/src/pages/UploadPage.tsx`, `frontend/src/index.css`

**Interfaces:**
- Consumes: the API from Tasks 6–7.
- Produces:
  - `types.ts`: `SkuInput`, `ParseWarning`, `ParsedInput`, `SupplierSetting`, `SupplierSettingView`, `FlagCode` (string union of the 9 codes), `Flag`, `OrderReason`, `PlannedOrder`, `WeekProjection`, `SkuPlan`, `PlanResult`, `SupplierSummary`, `RunListItem`, `RunRecord`, `InspectResponse`. Dates are ISO strings.
  - `api.ts`: `inspectFile(file: File): Promise<InspectResponse>`, `createRun(file: File, planDate?: string): Promise<RunRecord>`, `getRun(id: number): Promise<RunRecord>`, `listRuns(): Promise<RunListItem[]>`, `recalculate(id: number): Promise<RunRecord>`, `getSupplierSummary(id: number, windowWeeks: number): Promise<SupplierSummary[]>`, `getSettings(): Promise<SupplierSettingView[]>`, `saveSettings(items: SupplierSetting[]): Promise<SupplierSettingView[]>`, `exportUrl(id: number, windowWeeks: number): string`. Non-2xx responses throw `ApiError` (with `status` and the `detail` text).
  - `format.ts`: `fmtQty(n: number): string` (whole numbers with thousands separators; one decimal if under 10 and not whole), `fmtDate(iso: string): string` (`"12 Oct 2026"`), `flagLabel(code: FlagCode): string` with labels: Order now, Stock-out risk, Excess stock, Expiry risk, No forecast, holding stock, MTD above forecast, Lead time ≥ reorder level, MOQ exceeds shelf life, Missing lead time.
  - Routes in `App.tsx`: `/` UploadPage, `/runs/:id` PlanPage, `/runs/:id/suppliers` SupplierPage, `/settings` SettingsPage, `/history` HistoryPage, plus a top nav with links New plan, History, Supplier settings. Pages not built yet render a placeholder.

- [ ] **Step 1: Scaffold**

```bash
cd C:/projects/DemandForecasting
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install && npm install react-router-dom@6 recharts@2 && npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```
`vite.config.ts`: `server.proxy['/api'] = 'http://127.0.0.1:8000'`, `test.environment = 'jsdom'`. Add the `"test": "vitest run"` script.
Expected: `npm run build` succeeds.

- [ ] **Step 2: Implement `types.ts`, `api.ts`, `format.ts`, `App.tsx`**

- [ ] **Step 3: Implement `UploadPage`**

Behavior (spec §10.1):
- A file picker accepts `.xlsx`. On select, call `inspectFile`.
- Show SKU count, supplier count, the MTD label and the forecast months range.
- Show a date input pre-filled with `default_plan_date`, with `min`/`max` set from the response.
- Show warnings in a collapsible list with a count badge.
- A Calculate button calls `createRun(file, planDate)` and navigates to `/runs/{id}`.
- API errors are shown inline, using the `detail` text.

- [ ] **Step 4: Verify manually**

Run the backend: `cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000`. Run the frontend: `cd frontend && npm run dev`.
Open `http://localhost:5173`, choose `backend/tests/fixtures/sample_input.xlsx`. Expected: 212 SKUs, 17 suppliers, plan date 12 Oct 2026, warnings listed. Calculate goes to `/runs/1` (placeholder).

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: frontend scaffold and upload page"
```

---

### Task 9: Order plan page and SKU detail

**Files:**
- Create: `frontend/src/lib/filters.ts`, `frontend/src/lib/filters.test.ts`, `frontend/src/pages/PlanPage.tsx`, `frontend/src/components/SkuDetail.tsx`, `frontend/src/components/FlagChips.tsx`

**Interfaces:**
- Consumes: `types.ts`, `api.ts`, `format.ts` (Task 8).
- Produces (`filters.ts`):
  - `interface SkuFilter { supplier: string | null; flag: FlagCode | null; dueWithinWeeks: number | null; search: string }`
  - `nextOrder(sku: SkuPlan): PlannedOrder | null` (the earliest order)
  - `ordersInWindow(sku: SkuPlan, planDate: string, weeks: number): PlannedOrder[]` (order date earlier than planDate + 7×weeks days)
  - `filterSkus(skus: SkuPlan[], f: SkuFilter, planDate: string): SkuPlan[]`. The result is sorted by next order date ascending (SKUs without orders last), then supplier, then description. `search` matches SAP code or description, case-insensitively.

- [ ] **Step 1: Write the failing tests** in `filters.test.ts`

```ts
import { describe, it, expect } from 'vitest'
import { filterSkus, ordersInWindow } from './filters'
import type { SkuPlan } from '../types'

const order = (d: string) => ({ order_date: d, arrival_date: d, qty: 10, reason: {} as any })
const sku = (code: string, supplier: string, orders: string[], flags: string[] = []): SkuPlan =>
  ({ sap_code: code, supplier, description: `item ${code}`, orders: orders.map(order),
     flags: flags.map(c => ({ code: c, message: '' })) } as unknown as SkuPlan)

const skus = [sku('1', 'A', ['2026-11-20']), sku('2', 'B', ['2026-10-12'], ['ORDER_NOW']), sku('3', 'A', [])]
const none = { supplier: null, flag: null, dueWithinWeeks: null, search: '' }

describe('filterSkus', () => {
  it('sorts by next order date, SKUs without orders last', () => {
    expect(filterSkus(skus, none, '2026-10-12').map(s => s.sap_code)).toEqual(['2', '1', '3'])
  })
  it('filters by supplier, flag, window and search', () => {
    expect(filterSkus(skus, { ...none, supplier: 'A' }, '2026-10-12').map(s => s.sap_code)).toEqual(['1', '3'])
    expect(filterSkus(skus, { ...none, flag: 'ORDER_NOW' }, '2026-10-12').map(s => s.sap_code)).toEqual(['2'])
    expect(filterSkus(skus, { ...none, dueWithinWeeks: 4 }, '2026-10-12').map(s => s.sap_code)).toEqual(['2'])
    expect(filterSkus(skus, { ...none, search: 'ITEM 3' }, '2026-10-12').map(s => s.sap_code)).toEqual(['3'])
  })
  it('window is exclusive of planDate + 7*weeks', () => {
    expect(ordersInWindow(sku('9', 'A', ['2026-11-09']), '2026-10-12', 4)).toHaveLength(0)
    expect(ordersInWindow(sku('9', 'A', ['2026-11-08']), '2026-10-12', 4)).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL (cannot resolve `./filters`).

- [ ] **Step 3: Implement `filters.ts`**

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS.

- [ ] **Step 5: Implement `PlanPage`, `SkuDetail`, `FlagChips`** (spec §10.2)

- **Header:** plan date, file name, run date. Buttons: Supplier summary (link), Recalculate with current settings (calls `recalculate` and replaces state), Export to Excel (`<a href={exportUrl(id, weeks)}>`).
- **Count cards:** Order now, Stock-out risk, Excess stock, No forecast, holding stock (from `result.flag_counts`). Clicking a card sets the flag filter.
- **Banner:** if `new_suppliers` is non-empty, show "N suppliers are using default levels (20/30 days)" with a link to `/settings`.
- **Filters:** supplier select, flag select, "Orders due within [N] weeks" checkbox plus number (default checked, 4), search box.
- **Table columns:** Supplier, SAP Code, Description, Sellable, SIT, Days of cover, Next order date, Qty, Arrival, Flags. Show "–" for no order.
- **Assumption note** under the table: "Stock in transit is counted as available from the plan date."
- **SkuDetail:** a side panel opened by clicking a row.
  - A recharts `ComposedChart` over `weeks`: line for `closing_stock`, step lines for `reorder_qty` and `target_qty`, bars for `arrivals`.
  - A weekly table (Week, Start, Demand, Arrivals, Closing stock, Lost).
  - An orders list where each order shows its reason as one sentence: "On {order_date} stock + on order = {inventory_position}, below reorder level {reorder_qty}. Ordering {qty} to reach target {target_qty}." Append "(raised to MOQ)" and/or "(capped by shelf life at {shelf_life_cap})" when applicable.
  - Flag messages in full.

- [ ] **Step 6: Verify manually**

With both servers running, open `/runs/1`. Expected:
- 212 rows when unfiltered.
- The 4-week filter shows only SKUs with orders due by 9 Nov 2026.
- Clicking a SKU with orders shows the chart and reason sentences.
- Export downloads an xlsx.

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "feat: order plan page with filters and SKU detail"
```

---

### Task 10: Supplier summary, settings and history pages

**Files:**
- Create: `frontend/src/lib/settings.ts`, `frontend/src/lib/settings.test.ts`, `frontend/src/pages/SupplierPage.tsx`, `frontend/src/pages/SettingsPage.tsx`, `frontend/src/pages/HistoryPage.tsx`

**Interfaces:**
- Produces (`settings.ts`): `validateSetting(s: { reorder_days: number; target_days: number }, maxLeadTime: number | null): { errors: string[]; warnings: string[] }`
  - Errors: `"Reorder level must be a whole number from 1 to 365."`, `"Target level must be a whole number from 1 to 365."`, `"Target level must be higher than reorder level."`
  - Warning when `maxLeadTime !== null && maxLeadTime >= reorder_days`: `"Some SKUs have a lead time of {maxLeadTime} days, at or above this reorder level, so they will run out before orders arrive."`

- [ ] **Step 1: Write the failing tests** in `settings.test.ts`

```ts
import { it, expect } from 'vitest'
import { validateSetting } from './settings'

it('accepts valid levels', () => {
  expect(validateSetting({ reorder_days: 45, target_days: 60 }, 30)).toEqual({ errors: [], warnings: [] })
})
it('rejects target not above reorder and out-of-range values', () => {
  expect(validateSetting({ reorder_days: 30, target_days: 30 }, null).errors)
    .toContain('Target level must be higher than reorder level.')
  expect(validateSetting({ reorder_days: 0, target_days: 30 }, null).errors).toHaveLength(1)
  expect(validateSetting({ reorder_days: 10.5, target_days: 30 }, null).errors).toHaveLength(1)
})
it('warns when lead time reaches the reorder level', () => {
  expect(validateSetting({ reorder_days: 20, target_days: 30 }, 30).warnings).toHaveLength(1)
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL (cannot resolve `./settings`).

- [ ] **Step 3: Implement `validateSetting`.** Run `npm test`; expected PASS.

- [ ] **Step 4: Implement the three pages**

- **SupplierPage** (`/runs/:id/suppliers`), spec §10.3:
  - A window-weeks number input (default 4) refetches `getSupplierSummary`.
  - Table: Supplier, Reorder/Target days (with a "default" tag when `is_default`), SKUs, SKUs to order, Cartons in window, Earliest order date, flag count chips.
  - Expanding a row lists that supplier's SKUs with orders in the window (SAP code, description, order date, qty, arrival), using `ordersInWindow` on the run's SKUs. This is the list the planner puts on one purchase order.
- **SettingsPage** (`/settings`), spec §10.4:
  - An editable table: Supplier, SKUs, Max lead time, Reorder days, Target days.
  - Inline errors and warnings from `validateSetting`. Rows with `is_default` are highlighted with the note "Using default — please review".
  - The Save button is disabled while any error exists. Save calls `saveSettings`; then, if `listRuns()` is non-empty, it calls `recalculate(latest.id)` and shows "Saved. Plan for {file} recalculated." with a link to it.
- **HistoryPage** (`/history`), spec §10.5: table of runs (Run #, Created, File, Plan date, SKUs), with each row linking to `/runs/{id}`.

- [ ] **Step 5: Verify manually**

- Set Honesty to 45/60 and save. Expected: confirmation, and the plan shows Honesty with the new levels in the supplier summary.
- Set 30/30. Expected: Save is disabled with the error shown.
- History lists the run.

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat: supplier summary, settings and history pages"
```

---

### Task 11: Launch configuration, README and end-to-end check

**Files:**
- Create: `README.md`, `.claude/launch.json`

**Interfaces:** none new.

- [ ] **Step 1: Write `.claude/launch.json`**

```json
{
  "version": "0.0.1",
  "configurations": [
    { "name": "backend", "runtimeExecutable": "backend/.venv/Scripts/python.exe",
      "runtimeArgs": ["-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--port", "8000"], "port": 8000 },
    { "name": "frontend", "runtimeExecutable": "npm",
      "runtimeArgs": ["--prefix", "frontend", "run", "dev"], "port": 5173 }
  ]
}
```

- [ ] **Step 2: Write `README.md`**

Cover: what the tool does (one paragraph), first-time setup (the venv and npm install commands from Tasks 1 and 8), how to start both servers, where the database lives (`backend/data/orderplan.db`, override with `ORDERPLAN_DB`), how to run the tests (`pytest`, `npm test`), and the known limitations copied from spec §13.

- [ ] **Step 3: End-to-end check**

Run all tests: `cd backend && .venv/Scripts/python -m pytest` and `cd frontend && npm test && npm run build`. Expected: all pass and the build succeeds.
Start both servers, upload the sample file, and check:
- The plan page loads in under 3 seconds.
- Export opens in Excel with 5 sheets.
- Settings changes trigger recalculation.
- History reopens the run.

- [ ] **Step 4: Commit**

```bash
git add README.md .claude/launch.json
git commit -m "docs: README and launch configuration"
```
