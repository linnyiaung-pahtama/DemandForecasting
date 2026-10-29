# Order Cycle and Order Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-principal order cycle setting and a 12-month **order plan** that orders only every *cycle* months, with a switch (Order plan | Order demand forecast) that drives every "order" figure on the plan page, Principal summary and SKU detail.

**Architecture:**
- `supplier_settings` gains `order_cycle_months` (schema v5). Validation, repository, change log and settings view carry it like MOQ and lead time.
- `holding.roll_forward` gains a `cycle` parameter. Cycle 1 is today's order demand forecast; `plan_all` runs it twice and stores the order plan plus its this-month values (order, required, order-up-to, status) next to the existing forecast-mode values, and order-plan counts next to `counts`.
- The summary and export add the order-plan figures.
- The frontend reads the mode from a `?mode=` URL parameter (default the order plan). Pure helpers in `lib/mode.ts` pick each mode's values, so pages only switch on them.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, sqlite3, openpyxl, pytest; React 19 + TypeScript, Vite 6, vitest.

**Spec:** `docs/superpowers/specs/2026-10-29-order-cycle-design.md`. It builds on the 12-month plan and supplier MOQ/lead time specs in the same folder.

## Global Constraints

- **Order cycle:** a whole number from 1 to 12 months, default 1, never blank. API error text: `Principal '<name>': order cycle must be a whole number of months from 1 to 12.`
- **Order months:** plan month index `i` (0-based) is an order month when `i % cycle == 0`.
- **Order-up-to** = `(buffer or 0) × (holding + cycle − 1)`; None when holding is not set.
- **In an order month:** required = max(ceil(order-up-to − opening − 1e-9), 0); order = ceil(MOQ − 1e-9) when 0 < required < MOQ, else required. **In any other month:** order 0. **Holding not set:** every order is None. **No demand data:** every order is 0.
- **Cycle 1 must give exactly today's `monthly`** (same orders, MOQ flags, stock path).
- **Forecast-mode fields stay unchanged:** `status`, `order_qty`, `required`, `target`, `moq_applied`, `monthly`, `counts`.
- **Order-plan status** uses the same four statuses: Holding not set and No demand data as today; To order when the order plan's month-1 order > 0; otherwise No order needed.
- **Mode:** URL parameter `mode`, values `plan` (default when absent or unknown) and `forecast`. Switch labels: **Order plan** | **Order demand forecast**, with Order plan first.
- **Older runs** (no `order_plan`) load. In plan mode the UI shows `Recalculate to see the order plan.`; exports and summaries leave order-plan cells blank.
- **Never touch `backend/data/orderplan.db` or its backups.** Tests use `tmp_path` / `conftest.py`. End-to-end checks use a copy in the scratchpad and a temporary `ORDERPLAN_DB`.
- **Stop only processes you started, by PID.** The planner's app runs on 8000/5173; use the `backend-test` / `frontend-test` launch configs (8001/5174) for browser checks.
- **Do not commit `requests/` or `.superpowers/`.** Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Avoid double quotes inside PowerShell here-string commit messages.
- **Commands:**
  - Backend: `backend\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider`.
  - Frontend: `npm --prefix frontend test -- --run`, `npm --prefix frontend run build`, `npm --prefix frontend run lint`.

## Review Focus

1. **Cycle 1 everywhere** (every principal after the v5 upgrade) must show identical numbers in both modes: same counts, statuses, orders and totals. Covered by Task 2 `test_cycle_one_order_plan_equals_forecast_on_fixture` and Task 4 `modeCounts` tests.
2. **A SKU that is "No order needed" in the forecast but "To order" in the order plan** (available between holding and holding + cycle − 1 months) must appear in plan mode's To order card, status filter and Principal summary purchase-order lines. Covered by Task 2 `test_plan_status_can_differ_from_forecast_status`, Task 3 `test_summary_order_plan_this_month`, and Task 4 `poLines` tests.
3. **A blocked principal (holding not set)** must show "—" in every order-plan month and total, never 0 or a dot. Covered by Task 2 `test_order_plan_holding_not_set_has_no_orders`, Task 3 `test_summary_order_plan_blank_for_blocked`, and Task 4 `orderCell` tests.
4. **An older run** (no `order_plan`, and settings_used without `order_cycle_months`) must load, export, and summarize without errors; plan mode shows the recalculate message. Covered by Task 3 `test_export_old_run_has_blank_order_plan` and `test_summary_old_run_has_blank_order_plan`, and Task 4 `hasOrderPlan` tests.
5. **A v4 database** must upgrade to v5 with every principal at cycle 1, no change-log lines, and a second start must not change anything. Covered by Task 1 `test_v4_database_upgrades_to_v5`.

---

### Task 1: Order cycle setting (backend)

**Files:**
- Modify: `backend/app/models.py`, `backend/app/db.py`, `backend/app/repository.py`, `backend/app/main.py`, `backend/app/holding.py` (settings used only), `backend/tests/helpers.py`
- Test: `backend/tests/test_repository.py`, `backend/tests/test_api.py`

**Interfaces:**
- Produces in `models.py`:
  - `SupplierSettings.order_cycle_months: int | None = None` (None only in runs saved before this change).
  - `SettingField = Literal["holding_months", "moq", "lead_time_days", "order_cycle_months"]`.
  - `SupplierSettingView.order_cycle_months: int`.
- Produces in `db.py`: `SCHEMA_VERSION = 5`; the `supplier_settings` CREATE statement gains `order_cycle_months INTEGER NOT NULL DEFAULT 1`; `V5_COLUMNS = (("supplier_settings", "order_cycle_months", "INTEGER NOT NULL DEFAULT 1"),)`; `_upgrade_to_v5(conn)` adds it in one BEGIN/COMMIT with ROLLBACK on error (same shape as `_upgrade_to_v4`), called after `_upgrade_to_v4`. No change-log lines.
- Produces in `repository.py`: `SETTING_FIELDS` gains `"order_cycle_months"`; `get_settings`, `save_settings` (upsert + per-field log) and `_settings` carry it; a principal with no stored row counts as cycle 1.
- Produces in `main.py`: `MIN_ORDER_CYCLE = 1`, `MAX_ORDER_CYCLE = 12`; `_parse_settings` requires the `order_cycle_months` key (missing-key message lists it) and validates it with `_is_whole`; `settings_views` returns it (1 for a principal with no stored row).
- Produces in `holding.plan_all`: each `settings_used` entry carries `order_cycle_months` (stored value, or 1).
- Produces in `helpers.py`: `holding_settings(holdings, moq=0, lead=None, cycle=1)`.

- [ ] **Step 1: Write the failing tests.**

```python
# test_repository.py
def test_order_cycle_saved_and_logged(tmp_path):
    repo = Repository(tmp_path / "t.db")
    repo.save_settings([SupplierSettings(supplier="A", holding_months=2, moq=0, lead_time_days=None,
                                         order_cycle_months=3)])
    assert repo.get_settings()["A"].order_cycle_months == 3
    log = repo.get_settings_log()
    assert {(e.field, e.old_value, e.new_value) for e in log} >= {("order_cycle_months", 1, 3)}

def test_v4_database_upgrades_to_v5(tmp_path):
    # build a v4 file by hand: supplier_settings without order_cycle_months, user_version 4, one row and one log line
    ...
    repo = Repository(path)
    assert repo.get_settings()["A"].order_cycle_months == 1
    assert len(repo.get_settings_log()) == 1                     # no new lines
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == 5
    Repository(path)                                              # second start: no error, nothing changes
    assert len(repo.get_settings_log()) == 1

# test_api.py
CYCLE_ERROR = "Principal 'Acme': order cycle must be a whole number of months from 1 to 12."

@pytest.mark.parametrize("bad", [0, 13, 1.5, "3", None, True])
def test_order_cycle_validation(client, bad):
    r = client.put("/api/settings", json=[row("Acme", 2, cycle=bad)])
    assert r.status_code == 422 and r.json()["detail"] == CYCLE_ERROR

def test_order_cycle_default_and_round_trip(client):   # after an upload: every principal at 1, then save 3
    ...
    assert all(v["order_cycle_months"] == 1 for v in client.get("/api/settings").json())
    ...
    assert next(...)["order_cycle_months"] == 3

def test_settings_missing_keys_returns_422(client):     # update the existing test
    assert r.json()["detail"] == ("Each setting needs a supplier name and holding_months, moq, lead_time_days "
                                  "and order_cycle_months values.")
```

  Extend the existing `row(...)` helper in `test_api.py` with `cycle=1` and update every existing PUT body to include `order_cycle_months`.

- [ ] **Step 2: Run them and watch them fail** (missing field / 200 instead of 422).
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run the backend suite.** Expected: all pass.
- [ ] **Step 5: Commit** `feat: order cycle principal setting (schema v5)`.

### Task 2: Order plan calculation

**Files:**
- Modify: `backend/app/models.py`, `backend/app/holding.py`
- Test: `backend/tests/test_holding.py`

**Interfaces:**
- Consumes: `SupplierSettings.order_cycle_months` (Task 1).
- Produces in `models.py`:
  - `MonthPlan.order_month: bool = True` (False only for order-plan months that are not order months).
  - `SkuResult` gains, all defaulting to None / False for older runs: `order_cycle_months: int | None`, `order_plan: list[MonthPlan] | None`, `plan_order_up_to: float | None`, `plan_required: int | None`, `plan_order_qty: int | None`, `plan_moq_applied: bool = False`, `plan_status: SkuStatus | None`.
  - `HoldingPlan.plan_counts: dict[str, int] | None = None` (same five keys as `counts`).
- Produces in `holding.py`:
  - `order_up_to(sku: SkuResult, cycle: int) -> float | None`.
  - `roll_forward(sku: SkuResult, months: list[str], cycle: int = 1) -> list[MonthPlan]`: one loop for both plans, applying Global Constraints. With `cycle=1` the result equals today's.
  - `plan_all` sets, per SKU: `monthly = roll_forward(r, plan_months)`, `order_cycle_months`, `order_plan = roll_forward(r, plan_months, cycle)`, `plan_order_up_to`, `plan_required` (the month-1 required before MOQ; None when holding not set), `plan_order_qty = order_plan[0].order`, `plan_moq_applied = order_plan[0].moq_applied`, `plan_status`; and `plan_counts`.

- [ ] **Step 1: Write the failing tests** (use `run(..., moq=0)` from the existing helpers: buffer 120, holding 3, available 260).

```python
def test_order_plan_small_example():          # spec section 3: cycle 3, order-up-to 600
    m = roll_forward(run(moq=0), MONTHS, cycle=3)
    assert [p.order for p in m] == [340, 0, 0, 360, 0, 0, 360, 0, 0, 360, 0, 0]
    assert [p.order_month for p in m] == [True, False, False] * 4
    assert m[3].opening == pytest.approx(240)

def test_order_plan_cycle_one_is_the_forecast():
    for kw in ({}, {"moq": 0}, {"holding": None}, {"actuals": (0, 0, 0), "fc": (0, 0, 0)}, {"sellable": -20, "sit": 0}):
        r = run(**kw)
        assert roll_forward(r, MONTHS, cycle=1) == roll_forward(r, MONTHS)

def test_order_plan_cycle_twelve_and_five():
    assert [p.order_month for p in roll_forward(run(moq=0), MONTHS, cycle=12)] == [True] + [False] * 11
    assert [i for i, p in enumerate(roll_forward(run(moq=0), MONTHS, cycle=5)) if p.order_month] == [0, 5, 10]

def test_order_plan_moq_and_zero_order_month():
    # MOQ raises an order-month order; an order month with enough stock orders 0 (still an order month)
    m = roll_forward(run(moq=500), MONTHS, cycle=3)
    assert m[0].order == 500 and m[0].moq_applied
    big = roll_forward(run(sellable=1000, sit=0, moq=0), MONTHS, cycle=3)   # 1000 > 600
    assert big[0].order == 0 and big[0].order_month

def test_order_plan_holding_not_set_has_no_orders():
    m = roll_forward(run(holding=None), MONTHS, cycle=3)
    assert all(p.order is None for p in m)

def test_order_plan_no_demand_orders_zero():
    assert all(p.order == 0 for p in roll_forward(run(actuals=(0, 0, 0), fc=(0, 0, 0)), MONTHS, cycle=3))

def test_order_up_to():
    assert order_up_to(run(), 3) == pytest.approx(600) and order_up_to(run(holding=None), 3) is None

def test_plan_status_can_differ_from_forecast_status():
    # available 400 > target 360 (forecast: No order needed) but < order-up-to 600 (order plan: To order 200)
    ...plan_all with cycle 3 for the SKU's principal...
    assert r.status == SkuStatus.NO_ORDER_NEEDED and r.plan_status == SkuStatus.TO_ORDER
    assert r.plan_order_qty == 200 and r.plan_required == 200 and r.plan_order_up_to == pytest.approx(600)
    assert result.plan_counts["TO_ORDER"] == result.counts["TO_ORDER"] + 1

def test_cycle_one_order_plan_equals_forecast_on_fixture():
    # the existing fixture plan_all test, with cycle 1: order_plan == monthly, plan_status == status,
    # plan_order_qty == order_qty for every SKU, plan_counts == counts
```

- [ ] **Step 2: Run them and watch them fail** (`roll_forward` has no `cycle`, `order_up_to` missing).
- [ ] **Step 3: Implement.** Replace `roll_forward`'s month-1 special case with the general rule (it gives `order_qty` for cycle 1: same formula as `plan_sku`); the existing 12-month tests must still pass unchanged.
- [ ] **Step 4: Run the backend suite.** Expected: all pass.
- [ ] **Step 5: Commit** `feat: 12-month order plan following the principal's order cycle`.

### Task 3: Principal summary and Excel export

**Files:**
- Modify: `backend/app/models.py` (`SupplierSummary`), `backend/app/summary.py`, `backend/app/export.py`
- Test: `backend/tests/test_summary.py`, `backend/tests/test_export.py`

**Interfaces:**
- Consumes: Task 2 fields.
- Produces in `SupplierSummary` (None for older runs; the order-plan totals also None for a blocked principal):
  `order_cycle_months: int | None`, `plan_skus_to_order: int | None`, `plan_total_order_qty: int | None`,
  `plan_monthly_order_qty: list[int | None] | None` (None in months that are not order months),
  `plan_twelve_month_total: int | None`.
- Produces in the export (spec section 6.5), header names exactly:
  - "Order Cycle (months)" after "Lead Time (days)" in SKU Plan, 12-Month Plan, Order Plan and Settings Used; after "Holding (months)" in Principal Summary.
  - New sheet "Order Plan" after "12-Month Plan": the 12-Month Plan columns with "<month> Order Plan" month columns (blank when not an order month), "12-Month Total", and "Status" = `plan_status`.
  - Principal Summary: "Order Plan SKUs to Order" and "Order Plan Total Order Qty" right after "Total Order Qty"; month columns "<month> Order Demand Forecast", then "12-Month Total", then "<month> Order Plan" columns and "12-Month Order Plan Total".
  - Sheet order: SKU Plan, 12-Month Plan, Order Plan, Principal Summary, Settings Used, Warnings.

- [ ] **Step 1: Write the failing tests:** `test_summary_order_plan_this_month` (a cycle-3 principal: plan SKUs to order / total from `plan_order_qty`, monthly totals None in non-order months, total = sum of order months); `test_summary_order_plan_blank_for_blocked`; `test_summary_old_run_has_blank_order_plan`; `test_order_plan_sheet` (headers, a cycle-3 SKU's row: blank non-order months, order months equal `order_plan`, Status = plan status); `test_export_old_run_has_blank_order_plan`; update the existing header assertions (sheet list, Order Cycle columns, Principal Summary month headers).
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the backend suite.** Expected: all pass.
- [ ] **Step 5: Commit** `feat: order plan in the principal summary and Excel export`.

### Task 4: Frontend data layer

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/lib/filters.ts`, `frontend/src/lib/format.ts`, `frontend/src/lib/settings.ts`
- Create: `frontend/src/lib/mode.ts`, `frontend/src/lib/mode.test.ts`
- Test: `frontend/src/lib/filters.test.ts`, `frontend/src/lib/format.test.ts`, `frontend/src/lib/settings.test.ts`

**Interfaces:**
- Consumes: Tasks 1–3 field names (mirror them in `types.ts`).
- Produces in `lib/mode.ts`:
  - `type PlanMode = 'plan' | 'forecast'`; `readMode(params: URLSearchParams): PlanMode` (`plan` unless `mode=forecast`); `MODE_LABEL: Record<PlanMode, string>` = Order plan / Order demand forecast.
  - `hasOrderPlan(plan: HoldingPlan): boolean` (every SKU has `order_plan`).
  - `skuView(s: SkuResult, mode)`: `{ status, orderQty, moqApplied, months: MonthPlan[] | null, total: number | null }` from the mode's fields (total null when holding not set or no months).
  - `modeCounts(plan, mode): Record<string, number> | null`.
  - `summaryView(s: SupplierSummary, mode)`: `{ skusToOrder, totalOrderQty, monthly, twelveMonthTotal }`.
  - `poLines(skus: SkuResult[], mode): Map<string, SkuResult[]>`: SKUs whose mode order > 0, grouped by principal, sorted as today.
  - `orderCell(m: MonthPlan): 'blocked' | 'not-order-month' | 'order'` for the table cells.
- Produces: `filterSkus(skus, f, mode = 'forecast')` filters and sorts on the mode's status / order qty; `orderExplanation(r, planDate, mode = 'forecast')` in plan mode prints `Order-up-to = <buffer> × (<holding> + <cycle> − 1) months = <value>` and uses `plan_required` / `plan_order_qty` / `plan_moq_applied` for the required and MOQ lines.
- Produces in `lib/settings.ts`: `ORDER_CYCLE_MIN = 1`, `ORDER_CYCLE_MAX = 12`; `validateOrderCycle(text): Parsed` (whole number 1–12, blank is an error: `Order cycle must be a whole number of months from 1 to 12.`); `changedSettings` compares and sends `order_cycle_months`; `logValue('order_cycle_months', 3)` → `3 months` (`1 month` for 1).

- [ ] **Step 1: Write the failing tests** for every function above, including: `readMode` default and unknown values; `modeCounts` equal in both modes for a cycle-1 plan; `poLines` including a SKU with forecast order 0 but plan order > 0 only in plan mode; `orderCell` for a blocked month (order null), a non-order month, and an order month with 0; `filterSkus` status filter in plan mode; the plan-mode `orderExplanation` lines for the small example (buffer 120, holding 3, cycle 3, available 260 → `Order-up-to = 120 × (3 + 3 − 1) months = 600`, `Required = 600 − 260 = 340`); `validateOrderCycle` for "", "0", "13", "1.5", "3".
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm --prefix frontend test -- --run` and `npm --prefix frontend run build`. Expected: pass.
- [ ] **Step 5: Commit** `feat: frontend helpers for the order plan mode and order cycle`.

### Task 5: Screens

**Files:**
- Modify: `frontend/src/pages/PlanPage.tsx`, `frontend/src/pages/SupplierPage.tsx`, `frontend/src/pages/SettingsPage.tsx`, `frontend/src/components/SkuDetail.tsx`, `frontend/src/index.css`
- Create: `frontend/src/components/ModeSwitch.tsx`

**Interfaces:**
- Consumes: Task 4 helpers. `ModeSwitch({ mode, onChange })` renders the two buttons (Order plan first) with `aria-pressed`, styled like the earlier `.view-switch` (restore that CSS under a new `.mode-switch` class).

- [ ] **Step 1: Plan page.** Read the mode with `useSearchParams` (`readMode`); `ModeSwitch` above the count cards updates `?mode=` (replace, keep other params). Count cards from `modeCounts` (show "—" when null). Status column, status filter and sort via `skuView` / `filterSkus(..., mode)`. Principal settings group gains **Order cycle** (`3 mo`) after Lead time. Month group heading = `MODE_LABEL[mode]`; month cells from `skuView(...).months` with `orderCell`: order → existing `OrderCell`; not-order-month → muted `·` with title `Not an order month`; blocked → `—`. Total from `skuView(...).total`. In plan mode without `hasOrderPlan`, show `Recalculate to see the order plan.` instead of the table. The "Principal summary" link carries `?mode=`. Update `columnCount`.
- [ ] **Step 2: SKU detail.** Takes `mode`. Facts: Order cycle (`3 months`), Order qty and status chip from `skuView`. "How this is worked out" = `orderExplanation(sku, planDate, mode)`. The 12-month table shows `skuView(...).months`; a month that is not an order month gets a muted row and `·` in the Order column (not 0, not "—"). Heading `12-month plan` → `MODE_LABEL[mode]`.
- [ ] **Step 3: Principal summary.** Mode from the URL; `ModeSwitch` under the heading; top table uses `summaryView` (SKUs to order, Total order qty) and adds an **Order cycle** column after Lead time; rows sorted by the mode's total order qty descending, then name; expanded lines from `poLines(..., mode)` with the mode's order and MOQ tag; 12-month table heading `12-month ` + mode label (lowercase), cells from `summaryView(...).monthly` (`·` for null in plan mode when the principal is not blocked, `—` when blocked); "Back to order plan" carries `?mode=`; for an older run in plan mode (no order plan), the top table's SKUs to order and Total order qty show "—", the expanded lines say `Recalculate to see the order plan.`, and so does the 12-month table.
- [ ] **Step 4: Principal settings.** Add an **Order cycle (months)** input after Lead time (`inputMode="numeric"`, `aria-label="Order cycle months for <name>"`, width 4.5rem), validated by `validateOrderCycle`, included in `changedSettings`. `FIELD_LABEL.order_cycle_months = 'Order cycle'`. Add one sentence to the intro: `Order cycle is how often each principal is ordered from: 3 means one order every three months, each covering the months until the next order (1 = every month).`
- [ ] **Step 5: Verify in the browser** on `backend-test` / `frontend-test` with a copy of the planner's DB: switch modes on run 7 (cycle 1 everywhere: identical numbers), set Constellation to cycle 3 on the copy, Recalculate, and check Phwer Htwe (4201111007) in plan mode: Oct ≈ 20,118, Nov/Dec `·`, Jan ≈ 20,927, status To order; the Principal summary's Constellation total and lines follow the mode; the URL keeps the mode across pages; the detail panel shows the order-up-to line. Run lint and build.
- [ ] **Step 6: Commit** `feat: order plan switch on the plan, principal summary and SKU detail; order cycle setting`.

### Task 6: README and end-to-end check

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README.** Document: the Order cycle setting (range, default, change log), the order plan calculation with the small example and the Phwer Htwe example from the spec, the switch and what it drives, the Excel changes, and "Upgrading to v5" (additive, cycle 1 for every principal, no log lines, no run recalculated).
- [ ] **Step 2: End-to-end on a copy** of `backend/data/orderplan.db` in the scratchpad with a Python script (`TestClient(create_app(copy))`): the upgrade sets v5; recalculate the latest run; with cycle 1 everywhere `order_plan == monthly` and `plan_counts == counts` for every SKU; set Constellation to cycle 3 via PUT; Phwer Htwe's order plan orders only in months 1, 4, 7, 10 and its 12-month total equals its forecast total; the export opens with the six sheets.
- [ ] **Step 3: Run both full suites, lint and build.** Expected: all pass.
- [ ] **Step 4: Commit** `docs: README for the order cycle and order plan`.
