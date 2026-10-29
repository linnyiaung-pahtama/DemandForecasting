# 12-Month Order Plan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For every SKU, show how much to order in each of the next 12 months. Month 1 is today's order; each later month rolls stock forward with demand equal to the buffer.

**Architecture:**
- A pure roll-forward function in `holding.py` turns a planned `SkuResult` into 12 `MonthPlan` entries. `plan_all` attaches them and sets `plan_months`.
- Monthly demand comes from one function (`monthly_demand`) so database forecasts can replace it later.
- The supplier summary sums orders per month; the export gets a "12-Month Plan" sheet.
- The frontend adds a This cycle / 12 months switch on the Plan page, a 12-month table in the SKU detail, and a monthly table on the Supplier summary.
- No schema change: everything lives in the stored result JSON.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest; React 19 + TypeScript, Vite 6, vitest.

**Spec:** `docs/superpowers/specs/2026-10-29-twelve-month-plan-design.md`. Read it with the v2, stock-files and supplier MOQ/lead-time specs in the same folder.

## Global Constraints

- **Months:** `next_months(parsed.mtd_month, 12)`, Oct 2026 – Sep 2027 for the fixture.
- **Demand** in every month = the SKU's buffer, or 0 when the buffer is None. Target = buffer × holding, as today.
- **Month 1:** opening = available; order = today's `order_qty` and `moq_applied`, unchanged.
- **Later months:**
  - required = max(ceil(target − opening − 1e-9), 0);
  - order = MOQ if 0 < required < MOQ, else required;
  - closing = opening + order − demand.
- **Holding not set:** every order is None, and stock rolls with 0 orders. **No demand data:** every order is 0.
- **Opening, demand and closing are stored unrounded; orders are whole cartons.**
- **Old runs** (no `monthly`, empty `plan_months`) load. The UI shows `Recalculate to see the 12-month plan.` Exports and summaries leave the monthly cells blank.
- **Never touch `backend/data/orderplan.db` or its backups.** Tests use `tmp_path` / `conftest.py`. The end-to-end check uses a copy in the scratchpad.
- **Stop only processes you started, by PID.** The planner's app is running on 8000/5173.
- **Do not commit `requests/` or `.superpowers/`.** Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Commands:**
  - Backend: from `backend/`, `.venv/Scripts/python -m pytest -q`.
  - Frontend: `npm --prefix frontend test`, `npm --prefix frontend run build`, `npm --prefix frontend run lint`.

## Review Focus

1. **A large MOQ against small demand** (Constellation-style: buffer 49, MOQ 8,000) must order once and then 0 for the following months, never 8,000 every month. Covered by Task 1 `test_large_moq_orders_once_then_waits`.
2. **Negative available stock** must bring stock up to target in month 1 and then order the buffer each month, with no negative orders. Covered by Task 1 `test_negative_available_rolls_forward`.
3. **A blocked supplier** must show "—" for every month and for the total, never 0. Covered by Task 1 `test_holding_not_set_has_no_orders` and Task 3 `monthlyTotal` tests.
4. **An old saved plan without monthly data** must open on the 12-month view without crashing, showing the recalculate message. The summary and export must leave the cells blank. Covered by Task 2 `test_old_run_has_blank_monthly_totals` and Task 3 `hasMonthly` tests.
5. **Recalculating after a settings change** must update the 12 months too, for example MOQ changed to 0. Covered by Task 2 `test_recalculate_refreshes_monthly_plan`.

---

### Task 1: Roll-forward calculation

**Files:**
- Modify: `backend/app/models.py`, `backend/app/holding.py`
- Test: `backend/tests/test_holding.py`

**Interfaces:**
- Produces, in `models.py`:
  ```python
  class MonthPlan(BaseModel):
      month: str              # "YYYY-MM"
      opening: float
      demand: float
      order: int | None       # None when holding is not set
      moq_applied: bool = False
      closing: float
  ```
  - `SkuResult.monthly: list[MonthPlan] | None = None`. It is None for runs saved before this change.
  - `HoldingPlan.plan_months: list[str] = []`, empty for old runs.
- Produces, in `holding.py`:
  - `PLAN_MONTHS = 12`
  - `monthly_demand(sku: SkuResult, months: list[str]) -> dict[str, float]`: today `{m: sku.buffer or 0.0 for m in months}`. This is the single place a database forecast plugs in later.
  - `roll_forward(sku: SkuResult, months: list[str]) -> list[MonthPlan]`: applies the rules in Global Constraints. It uses `sku.available`, `sku.order_qty`, `sku.moq_applied`, `sku.target`, `sku.moq`, `sku.holding_months` and `sku.valid_count`.
  - `plan_all` sets `plan_months = next_months(parsed.mtd_month, PLAN_MONTHS)` and each `SkuResult.monthly = roll_forward(result, plan_months)`. `plan_sku`'s signature is unchanged.

- [ ] **Step 1: Write the failing tests** in `test_holding.py`, using the existing `run()` helper (buffer 120, holding 3, available 260, MOQ 150) and `MONTHS = next_months("2026-10", 12)`.

```python
def test_worked_example_rolls_forward():   # spec section 3 table, extended to 12 months
    m = roll_forward(run(), MONTHS)
    assert [p.month for p in m] == MONTHS
    assert [p.order for p in m] == [150, 150, 150, 150, 0, 150, 150, 150, 150, 0, 150, 150]
    assert [p.closing for p in m] == pytest.approx([290, 320, 350, 380, 260, 290, 320, 350, 380, 260, 290, 320])
    assert m[0].opening == 260 and all(p.demand == pytest.approx(120) for p in m)
    assert m[0].moq_applied and m[1].moq_applied and not m[4].moq_applied

def test_moq_zero_orders_the_buffer_after_month_one():
    m = roll_forward(run(moq=0), MONTHS)
    assert [p.order for p in m] == [100] + [120] * 11
    assert all(p.closing == pytest.approx(240) for p in m)

def test_large_moq_orders_once_then_waits():
    # buffer 49/month, holding 2 (target 98), available 0, MOQ 8000
    r = run(actuals=(49, 49, 49), fc=(49, 49, 49), holding=2, moq=8000, sellable=0, sit=0)
    orders = [p.order for p in roll_forward(r, MONTHS)]
    assert orders[0] == 8000 and orders[1:] == [0] * 11

def test_holding_not_set_has_no_orders():
    m = roll_forward(run(holding=None), MONTHS)
    assert all(p.order is None for p in m)
    assert m[-1].closing == pytest.approx(260 - 12 * 120)   # stock runs down

def test_no_demand_orders_zero_and_stock_stays():
    m = roll_forward(run(actuals=(0, 0, 0), fc=(0, 0, 0)), MONTHS)
    assert all(p.order == 0 and p.demand == 0 and p.closing == 260 for p in m)

def test_negative_available_rolls_forward():
    m = roll_forward(run(sellable=-20, sit=0, moq=0), MONTHS)   # target 360
    assert m[0].order == 380 and m[0].closing == pytest.approx(240)
    assert [p.order for p in m[1:]] == [120] * 11 and all(p.order >= 0 for p in m)

def test_plan_all_attaches_twelve_months_matching_todays_order():   # real fixture
    # build parsed (with apply_stock) and actual as test_plan_all_counts_and_zero_forecast does,
    # settings: every supplier holding 2, moq 0, lead 7
    assert result.plan_months == next_months("2026-10", 12)
    assert all(len(s.monthly) == 12 and s.monthly[0].order == s.order_qty for s in result.skus)
```

- [ ] **Step 2: Run the tests and check they fail.**
Run from `backend/`: `.venv/Scripts/python -m pytest tests/test_holding.py -q`
Expected: FAIL (`roll_forward` is not defined).

- [ ] **Step 3: Implement the models, `monthly_demand`, `roll_forward` and the `plan_all` wiring.**

- [ ] **Step 4: Run the backend suite and check it passes.**
Run from `backend/`: `.venv/Scripts/python -m pytest -q`
Expected: all pass. Existing tests that compare whole `HoldingPlan`/`SkuResult` objects may need `monthly`/`plan_months`. Update them, and do not loosen any other assertion.

- [ ] **Step 5: Commit.** `feat: roll each SKU's order forward for 12 months`

---

### Task 2: Supplier monthly totals, export and recalculate

**Files:**
- Modify: `backend/app/models.py`, `backend/app/summary.py`, `backend/app/export.py`
- Test: `backend/tests/test_summary.py`, `backend/tests/test_export.py`, `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `MonthPlan`, `SkuResult.monthly` and `HoldingPlan.plan_months` (Task 1).
- `SupplierSummary` gains:
  - `monthly_order_qty: list[int] | None = None`: per `plan_months`, the sum of orders, with None counted as 0;
  - `twelve_month_total: int | None = None`.
  Both are None when any of the supplier's SKUs has `monthly` None (old run).
- **Export:**
  - New sheet `"12-Month Plan"`, placed after "SKU Plan". Columns: `Supplier`, `SAP Code`, `Description`, `Status`, one column per plan month labelled with `month_label` (e.g. `Oct 2026`), then `Total`. Order cells are blank when None. Total is blank when holding is not set, else the sum.
  - Old runs: the sheet has only the four fixed headers plus `Total`, and the month columns are absent.
  - The "Supplier Summary" sheet appends the month columns and `12-Month Total`, blank for old runs.

- [ ] **Step 1: Write the failing tests.**
  - `test_summary.py::test_supplier_monthly_totals`: on the fixture with CFC holding 3, MOQ 0, lead 7:
    - the CFC summary's `monthly_order_qty` has 12 entries;
    - each entry equals the sum over CFC SKUs of that month's order;
    - `twelve_month_total` equals their sum;
    - a blocked supplier gets 12 zeros and total 0.
  - `test_summary.py::test_old_run_has_blank_monthly_totals`: SKUs with `monthly=None` give `monthly_order_qty is None` and `twelve_month_total is None`.
  - `test_export.py::test_twelve_month_sheet`:
    - the sheet order is `["SKU Plan", "12-Month Plan", "Supplier Summary", "Settings Used", "Warnings"]` (update `test_export_v2_sheets_and_values` accordingly);
    - the header is `["Supplier", "SAP Code", "Description", "Status", "Oct 2026", …, "Sep 2027", "Total"]`;
    - the CFC SKU 3102111001 row's months equal its `monthly` orders, and Total is their sum;
    - a blocked SKU's month cells and Total are None.
  - `test_api.py::test_recalculate_refreshes_monthly_plan`:
    1. Create a run and set CFC (holding 3, MOQ 500, lead 7). Recalculate. 3102111001's monthly orders contain 500 and at least one 0.
    2. Set MOQ 0 and recalculate. The monthly orders no longer contain 500.

- [ ] **Step 2: Run the tests and check they fail.**
Run from `backend/`: `.venv/Scripts/python -m pytest tests/test_summary.py tests/test_export.py tests/test_api.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the summary totals and export sheets.**

- [ ] **Step 4: Run the full backend suite and check it passes.**

- [ ] **Step 5: Commit.** `feat: supplier monthly order totals and a 12-Month Plan export sheet`

---

### Task 3: Plan page 12-month view and SKU detail

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/lib/format.ts`, `frontend/src/lib/format.test.ts`, `frontend/src/pages/PlanPage.tsx`, `frontend/src/components/SkuDetail.tsx`

**Interfaces:**
- Consumes: the API shapes from Tasks 1–2.
- **`types.ts`:** `MonthPlan { month: string; opening: number; demand: number; order: number | null; moq_applied: boolean; closing: number }`.
  - `SkuResult.monthly: MonthPlan[] | null`
  - `HoldingPlan.plan_months: string[]`
  - `SupplierSummary.monthly_order_qty: number[] | null`
  - `SupplierSummary.twelve_month_total: number | null`
- **`format.ts`:**
  - `hasMonthly(plan: HoldingPlan): boolean` is true when `plan_months.length > 0` and every SKU's `monthly !== null`.
  - `monthlyTotal(r: SkuResult): number | null` is null when `monthly` is null or `holding_months` is null; otherwise the sum of orders.
- **`PlanPage`:**
  - A two-button switch above the table: `This cycle` and `12 months`, with `aria-pressed`. It defaults to This cycle and is kept in component state.
  - The 12-months table:
    - Columns are Supplier, SAP Code, Description, one column per `plan_months` labelled with `monthLabel`, then Total.
    - Each cell is `fmtQty(order)`, with an `MOQ` tag when `moq_applied`, or `—` when null.
    - It uses the same filtered SKU list, and a row click opens the SKU detail.
  - When `!hasMonthly(result)`, show `Recalculate to see the 12-month plan.` instead of the table.
  - The table sits in the existing `table-wrap`, so 12 columns scroll horizontally.
- **`SkuDetail`:**
  - When `sku.monthly` is non-null, a section `12-month plan` shows the line `Demand each month = buffer (average of the valid values above)`.
  - Under it, a table: Month, Opening, Demand, Order, Closing. Opening, Demand and Closing use `fmtExact`. Order uses `fmtQty` with an `MOQ` tag, or `—` when null.

- [ ] **Step 1: Write the failing tests** in `format.test.ts`.
  - `hasMonthly`:
    - true for a plan with `plan_months` and SKUs carrying `monthly`;
    - false when `plan_months` is empty;
    - false when any SKU has `monthly: null`.
  - `monthlyTotal`:
    - the sum for orders `[150, 0, 150]`;
    - null when `holding_months` is null;
    - null when `monthly` is null.
  - Add `monthly: null` to the shared `worked` fixture, and `plan_months: []` to the plan fixtures.

- [ ] **Step 2: Run the tests and check they fail.**
Run: `npm --prefix frontend test`
Expected: FAIL on the new cases.

- [ ] **Step 3: Implement the types, helpers, Plan page switch and SKU detail section.**

- [ ] **Step 4: Run the tests, build and lint, and check they pass.**

- [ ] **Step 5: Commit.** `feat: 12-month view on the plan page and in the SKU detail`

---

### Task 4: Supplier summary page, README and checks

**Files:**
- Modify: `frontend/src/pages/SupplierPage.tsx`, `README.md`

- [ ] **Step 1: Add the 12-month table to the Supplier summary page.**
  - Below the existing table, add a heading `12-month orders` and a table with columns Supplier, the 12 month labels (from the run's `plan_months`) and Total.
  - Show `fmtQty` values; when `monthly_order_qty` is null, show `Recalculate to see the 12-month plan.` instead.
  - The page already loads the run for its SKU lines; reuse it for `plan_months`.
  - Then run: `npm --prefix frontend test`, `npm --prefix frontend run build` and `npm --prefix frontend run lint`. Expected: pass.

- [ ] **Step 2: Update `README.md`.** Add a "12-month plan" section:
  - the months covered;
  - demand = buffer for now;
  - the roll-forward rules with the worked example (orders 150, 150, 150, 150, 0, 150 …);
  - that orders arrive within the month and lead time doesn't shift them;
  - where it shows (switch, SKU detail, supplier summary, export sheet);
  - that older plans need a Recalculate.

- [ ] **Step 3: Run the end-to-end check on a copy of the real database.**
Use a scratch script with `TestClient(create_app(<copy>))`. Copy `backend/data/orderplan.db` to the scratchpad first; never open the original. Then recalculate the latest run and check:
  - `plan_months` is Oct 2026 – Sep 2027;
  - every SKU has 12 months, and month 1's order equals `order_qty`;
  - no negative orders;
  - for every SKU with holding set, the stock balance holds exactly (within 1e-6): Σ orders = Σ demand + month-12 closing − month-1 opening.
  Report Phwer Htwe's 12 orders and the total cartons per month across all suppliers.

- [ ] **Step 4: Run the full verification.**
Run: backend suite, frontend tests and build.
Expected: green, and the real database's size and modification time unchanged.

- [ ] **Step 5: Commit.** `docs: README for the 12-month plan; supplier monthly table`

- [ ] **Step 6: Controller-only step.**
  - Browser check on the test servers with a copied database: the switch, the table, the SKU detail section, the supplier monthly table and an old plan's message.
  - Then tell the planner the running backend needs a restart. No database upgrade is needed this time.
