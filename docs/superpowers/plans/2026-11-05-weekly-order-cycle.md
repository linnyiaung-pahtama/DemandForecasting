# Weekly Order Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The principal order cycle is set in weeks (1–52, default 4). The order plan places an order on the plan date and then every `7 × cycle` days. Stock is followed day by day, and the plan is shown as the existing 12 month columns with each order listed by date.

**Architecture:**
- **Settings:** `order_cycle_months` is renamed `order_cycle_weeks` in every model, API and TypeScript type. Storage moves to a new v6 column; the old column is left in the table unread. Old `order_cycle_months` change-log lines stay readable as history.
- **Calculation (`holding.py`):** a day-by-day roll-forward replaces the cycle parameter of `roll_forward`, which goes back to being the forecast-mode monthly plan only. `MonthPlan` gains its `orders` (date, qty, MOQ applied).
- **Older runs:** a run saved with a months cycle has its order plan stripped when it is loaded, so the existing "Recalculate to see the order plan" paths take over unchanged.
- **Export:** gains an "Order Dates" sheet.
- **Frontend:** renames the field, validates weeks, explains the weekly order-up-to, marks months with more than one order, and lists the orders in the SKU detail.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, sqlite3, openpyxl, pytest; React 19 + TypeScript, Vite, vitest.

**Spec:** `docs/superpowers/specs/2026-11-05-weekly-order-cycle-design.md`. It builds on `2026-10-29-order-cycle-design.md`.

## Global Constraints

- **Order cycle:** a whole number of weeks from 1 to 52, default **4** (`DEFAULT_ORDER_CYCLE_WEEKS = 4` in `app/models.py`), never blank. API error text: `Principal '<name>': order cycle must be a whole number of weeks from 1 to 52.` Frontend error text: `Order cycle must be a whole number of weeks from 1 to 52.`
- **Order-up-to** = `b × max(holding − 1 + w × 12 / 52, w × 12 / 52)`, where `b = buffer or 0` and `w` = cycle weeks. None when holding is not set.
- **Order dates:** `plan_date + k × 7 × w` days for k = 0, 1, … while the date is ≤ the last day of plan month 12.
- **Daily demand:** a day in month `m` uses `monthly_demand(sku, months)[m] / days_in_month(m)`. Days before the plan date are not planned.
- **On an order date,** before that day's demand: `order, moq = _raise_to_moq(_required(level, stock, valid_count), sku.moq)`; then `stock += order`. Holding not set: no order lines, and month orders are None.
- **Month values:**
  - opening = stock before the month's first planned day (available for a month with no planned days, or for month 1);
  - demand = the sum of its planned days;
  - order = the sum of its lines' qty (0 when none; None when holding is not set);
  - `moq_applied` = any line raised;
  - closing = opening + (order or 0) − demand;
  - `order_month` = at least one order date in the month;
  - `orders` = its lines, in date order.
- **This month's order-plan values** (`plan_order_qty`, `plan_moq_applied`, `plan_status`) come from the **plan-date order** (the first line of the plan).
- **Forecast-mode fields and `roll_forward(sku, months)` keep today's values** (orders, MOQ flags, stock path, status, counts). Their `orders` is `[]` and `order_month` is True.
- **Never touch `backend/data/orderplan.db` or its backups.** Tests use `tmp_path`. End-to-end checks use a copy in the scratchpad and a temporary `ORDERPLAN_DB`.
- **Process hygiene:** stop only processes you started, by PID or serverId. Do not restart the planner's servers (8000/5173) without asking.
- **Commits:**
  - Do not commit `requests/` or `.superpowers/`.
  - The working tree already has uncommitted planner-approved changes (the warning removal and the Order-up-to column). Ask the planner before the first commit whether to commit those first. Never sweep them into a task commit unasked.
  - Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Commands:**
  - Backend: `backend\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider`.
  - Frontend: `npm --prefix frontend test -- --run`, `npm --prefix frontend run build`, `npm --prefix frontend run lint`.

## Review Focus

1. **The plan date after plan month 1** (the MTD ends on a month's last day): month 1 is empty and the plan-date order sits in month 2, but it is still "this month's order". Covered by Task 1 `test_weekly_plan_date_after_month_one`.
2. **An older run** (result JSON with `order_cycle_months` and a monthly `order_plan`) must load, summarize and export with the order plan blank, and must never show month-cycle orders as weekly ones. Covered by Task 2 `test_old_month_cycle_run_loses_its_order_plan` and `test_saved_month_cycle_run_shows_recalculate`.
3. **A holding under 1 month on a short cycle** must still order every cycle (the floor). Covered by Task 1 `test_weekly_order_up_to_floor` and `test_weekly_low_holding_still_orders`.
4. **Month totals must equal the sum of their lines**, with MOQ flags agreeing, across MOQ and multi-order months. Covered by Task 1 `test_weekly_month_totals_match_lines`.
5. **The v5 → v6 upgrade:** everyone gets 4, the old column and old log lines are kept, and a second start changes nothing. Covered by Task 2 `test_v5_database_upgrades_to_v6`.

---

### Task 1: Weekly order plan calculation

**Files:**
- Modify: `backend/app/models.py`, `backend/app/holding.py`
- Test: `backend/tests/test_holding.py`

**Interfaces:**
- Produces in `models.py`:
  - `class OrderLine(BaseModel): date: date; qty: int; moq_applied: bool = False`;
  - `MonthPlan.orders: list[OrderLine] = []`;
  - `DEFAULT_ORDER_CYCLE_WEEKS = 4`.
- Produces in `holding.py`:
  - `order_up_to(sku: SkuResult, cycle_weeks: int) -> float | None`, the weekly rule with the floor, replacing the monthly one;
  - `order_dates(plan_date: date, months: list[str], cycle_weeks: int) -> list[date]`;
  - `weekly_order_plan(sku: SkuResult, months: list[str], plan_date: date, cycle_weeks: int) -> list[MonthPlan]`;
  - `roll_forward(sku, months)` loses its `cycle` parameter (forecast only).
- `_attach_order_plan(result, months, plan_date, cycle_weeks)` switches to `weekly_order_plan` / `order_up_to` in this task:
  - `plan_order_qty` and `plan_moq_applied` come from the first order line (None / False when holding is not set);
  - `plan_all` passes `plan_date` and, for now, `DEFAULT_ORDER_CYCLE_WEEKS`;
  - Task 2 replaces that default with the principal's setting.

- [ ] **Step 1: Write the failing tests.** Delete the monthly order-plan tests (`test_order_plan_small_example`, `test_order_plan_cycle_one_is_the_forecast`, `test_order_plan_cycle_twelve_and_five`, `test_order_plan_moq_and_zero_order_month`, `test_order_plan_holding_not_set_has_no_orders`, `test_order_plan_no_demand_orders_zero`, `test_order_up_to`). Keep `test_plan_status_can_differ_from_forecast_status`, `test_plan_moq_applied_and_blocked_plan_values` and `test_cycle_one_order_plan_equals_forecast_on_fixture` for Task 2 to rewrite. Add:

```python
PD10 = date(2026, 10, 10)

def test_weekly_spec_example():          # spec section 3: buffer 120, holding 3, available 260, cycle 4
    m = weekly_order_plan(run(moq=0), MONTHS, PD10, 4)
    lines = [(o.date, o.qty) for p in m for o in p.orders]
    assert lines == [(date(2026, 10, 10), 91), (date(2026, 11, 7), 109), (date(2026, 12, 5), 112),
                     (date(2027, 1, 2), 108), (date(2027, 1, 30), 109), (date(2027, 2, 27), 119),
                     (date(2027, 3, 27), 109), (date(2027, 4, 24), 111), (date(2027, 5, 22), 110),
                     (date(2027, 6, 19), 110), (date(2027, 7, 17), 110), (date(2027, 8, 14), 109),
                     (date(2027, 9, 11), 109)]
    assert [p.order for p in m] == [91, 109, 112, 217, 119, 109, 111, 110, 110, 110, 109, 109]
    assert m[0].opening == 260 and m[0].demand == pytest.approx(120 * 22 / 31)
    assert [p.closing for p in m] == pytest.approx(
        [265.8387, 254.8387, 246.8387, 343.8387, 342.8387, 331.8387, 322.8387, 312.8387, 302.8387,
         292.8387, 281.8387, 270.8387], abs=1e-3)
    assert all(p.demand == pytest.approx(120) for p in m[1:]) and all(p.order_month for p in m)

def test_weekly_order_up_to_and_floor():
    assert order_up_to(run(), 4) == pytest.approx(120 * (2 + 48 / 52))
    assert order_up_to(run(), 1) == pytest.approx(120 * (2 + 12 / 52))
    assert order_up_to(run(), 52) == pytest.approx(120 * 14)
    assert order_up_to(run(holding=0.5), 2) == pytest.approx(120 * 24 / 52)    # floored at one cycle
    assert order_up_to(run(holding=0.5), 1) == pytest.approx(120 * 12 / 52)
    assert order_up_to(run(holding=2), 4) == pytest.approx(120 * (1 + 48 / 52))  # never floors
    assert order_up_to(run(holding=None), 4) is None
    assert order_up_to(run(actuals=(0, 0, 0), fc=(0, 0, 0)), 4) == 0

def test_weekly_low_holding_still_orders():
    m = weekly_order_plan(run(holding=0.5, moq=0), MONTHS, PD10, 2)
    qtys = [o.qty for p in m for o in p.orders]
    assert len(qtys) == 26 and all(q > 0 for q in qtys[1:])

def test_order_dates_stop_at_month_twelve():
    assert order_dates(PD10, MONTHS, 52) == [PD10]
    d = order_dates(PD10, MONTHS, 4)
    assert d[-1] == date(2027, 9, 11) and len(d) == 13
    assert order_dates(date(2026, 10, 31), MONTHS, 1)[-1] <= date(2027, 9, 30)

def test_weekly_plan_date_after_month_one():   # MTD ended 31 Oct: plan date 1 Nov, plan months still from Oct
    m = weekly_order_plan(run(moq=0), MONTHS, date(2026, 11, 1), 4)
    assert (m[0].demand, m[0].order, m[0].order_month, m[0].orders, m[0].closing) == (0, 0, False, [], 260)
    assert m[1].orders[0].date == date(2026, 11, 1) and m[1].opening == 260

def test_weekly_february_uses_its_own_days():
    m = weekly_order_plan(run(moq=0), MONTHS, PD10, 4)
    feb = m[4]
    assert feb.demand == pytest.approx(120)   # 28 days × 120/28

def test_weekly_month_totals_match_lines():
    for kw, cycle in (({"moq": 0}, 3), ({"moq": 150}, 3), ({"moq": 500}, 2), ({"sellable": -20, "sit": 0}, 4)):
        for p in weekly_order_plan(run(**kw), MONTHS, PD10, cycle):
            assert p.order == sum(o.qty for o in p.orders)
            assert p.moq_applied == any(o.moq_applied for o in p.orders)
            assert p.order_month == bool(p.orders)
            assert p.closing == pytest.approx(p.opening + p.order - p.demand)
    m = weekly_order_plan(run(moq=500), MONTHS, PD10, 4)
    assert m[0].orders[0].qty == 500 and m[0].orders[0].moq_applied

def test_weekly_holding_not_set_and_no_demand():
    blocked = weekly_order_plan(run(holding=None), MONTHS, PD10, 4)
    assert all(p.order is None and p.orders == [] for p in blocked) and all(p.order_month for p in blocked)
    assert blocked[-1].closing == pytest.approx(260 - 120 * (22 / 31 + 11))
    flat = weekly_order_plan(run(actuals=(0, 0, 0), fc=(0, 0, 0)), MONTHS, PD10, 4)
    assert all(p.order == 0 and p.closing == 260 for p in flat)

def test_forecast_roll_forward_has_no_order_lines():
    assert all(p.orders == [] and p.order_month for p in roll_forward(run(), MONTHS))
```

- [ ] **Step 2: Run them.** `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_holding.py -q -p no:cacheprovider`
  Expected: collection fails with an ImportError for `weekly_order_plan` / `order_dates`.

- [ ] **Step 3: Implement** `OrderLine`, `MonthPlan.orders`, `DEFAULT_ORDER_CYCLE_WEEKS`, `order_up_to`, `order_dates` and `weekly_order_plan` per Global Constraints. Strip `cycle` out of `roll_forward`. In a blocked month (holding not set), `order_month` is True when the month holds an order date but `orders` stays `[]`. The month-1-empty case falls out of "opening = available for a month with no planned days".

- [ ] **Step 4: Run them again.** Same command. Expected: the new tests pass. Run the whole backend suite: only the three kept order-plan tests (rewritten in Task 2) and order-plan tests in `test_summary.py` / `test_export.py` / `test_api.py` may fail. Note their names in the ledger.

- [ ] **Step 5: Commit** (after the commit question in Global Constraints is settled).

```bash
git add backend/app/models.py backend/app/holding.py backend/tests/test_holding.py
git commit -m "feat: weekly order plan calculation with order dates and the order-up-to floor"
```

### Task 2: Weekly cycle setting, wiring and older runs (backend)

**Files:**
- Modify: `backend/app/models.py`, `db.py`, `repository.py`, `main.py`, `holding.py`, `summary.py`, `export.py` (attribute and header rename only), `backend/tests/helpers.py`
- Test: `backend/tests/test_holding.py`, `test_repository.py`, `test_api.py`, `test_summary.py`, `test_export.py`

**Interfaces:**
- **Consumes:** Task 1's `weekly_order_plan`, `order_up_to`, `OrderLine`, `DEFAULT_ORDER_CYCLE_WEEKS`.
- **Produces in `models.py`:**
  - `order_cycle_months` is renamed `order_cycle_weeks` on `SkuResult`, `SupplierSettings`, `SupplierSummary` and `SupplierSettingView` (`int` on the view);
  - `SettingField = Literal["holding_months", "moq", "lead_time_days", "order_cycle_weeks", "order_cycle_months"]`. The last value is kept for old log lines only.
- **Produces in `db.py`:**
  - `SCHEMA_VERSION = 6`;
  - CREATE gains `order_cycle_weeks INTEGER NOT NULL DEFAULT 4` (keep `order_cycle_months` in it so fresh and upgraded tables match);
  - `V6_COLUMNS` and `_upgrade_to_v6(conn)` in the v5 shape, called after `_upgrade_to_v5`. No log lines.
- **Produces in `repository.py`:** `SETTING_FIELDS = ("holding_months", "moq", "lead_time_days", "order_cycle_weeks")`. Selects, upserts and `_settings` use `order_cycle_weeks`. A principal with no row counts as `DEFAULT_ORDER_CYCLE_WEEKS`.
- **Produces in `main.py`:**
  - `MIN_ORDER_CYCLE = 1`, `MAX_ORDER_CYCLE = 52`;
  - `_parse_settings` requires `order_cycle_weeks`, and the missing-key message names it;
  - `settings_views` defaults to 4;
  - `get_run_or_404` also applies `drop_monthly_order_plan`.
- **Produces in `holding.py`:**
  - `_attach_order_plan` (from Task 1) also sets `result.order_cycle_weeks`.
  - `plan_all` reads `order_cycle_weeks` (or the default) into `settings_used` and the attach call.
  - `drop_monthly_order_plan(result: HoldingPlan) -> HoldingPlan`: when any SKU has an `order_plan` and `order_cycle_weeks is None`, it returns a copy where every SKU has:
    - `order_plan`, `plan_order_up_to`, `plan_required`, `plan_order_qty` and `plan_status` set to None;
    - `plan_moq_applied` set to False.
    It also sets `plan_counts` to None. Otherwise it returns `result` unchanged.
- **Produces in `summary.py`:** `order_cycle_weeks` replaces `order_cycle_months`. The logic is unchanged (a month without an order date is None).
- **Produces in `export.py`:**
  - "Order Cycle (weeks)" replaces "Order Cycle (months)" in every sheet;
  - the values come from `order_cycle_weeks`.
- **Produces in `helpers.py`:** `holding_settings(holdings, moq=0, lead=None, cycle=4)`.

- [ ] **Step 1: Write the failing tests.**
  - **`test_holding.py`:**
    - Rewrite `test_plan_status_can_differ_from_forecast_status` with holding 3, MOQ 0, **cycle 26** and `sellable=400, sit=0`:
      - target 360, so the forecast is No order needed;
      - order-up-to = 120 × (2 + 6) = 960, so the order plan is To order;
      - assert `plan_order_qty == plan_required == 560`, `plan_order_up_to ≈ 960`, `order_cycle_weeks == 26` and `order_plan[0].orders[0].date == PD`;
      - assert the plan counts move one SKU from No order needed to To order.
    - Rewrite `test_plan_moq_applied_and_blocked_plan_values` with S at holding 3, MOQ 500, cycle 4, and B with holding not set, cycle 2:
      - for S: `a.plan_required == 91` (ceil(350.769 − 260)), `a.plan_order_qty == 500` and `a.plan_moq_applied`;
      - for B: status Holding not set, everything None, `z.order_cycle_weeks == 2`, and every month's order None.
    - Replace `test_cycle_one_order_plan_equals_forecast_on_fixture` with `test_fixture_plan_order_is_the_plan_date_order`: for every SKU of the fixture (holding 2, MOQ 8000, cycle 4),
      - `s.plan_order_qty == (s.order_plan[0].orders[0].qty if s.order_plan[0].orders else None)`;
      - `s.order_plan[0].orders[0].date == parsed.default_plan_date`;
      - `s.monthly` is unchanged from `roll_forward(s, months)`.
    - Add `test_old_month_cycle_run_loses_its_order_plan`:
      - build a plan, then set every SKU's `order_cycle_weeks = None` to simulate old JSON;
      - after `drop_monthly_order_plan`, `order_plan` is None everywhere, `plan_counts` is None, and `monthly` is untouched;
      - a current plan passes through unchanged (`is` the same object).
  - **`test_repository.py`:**
    - rename the cycle test to weeks: save 3 and log `("order_cycle_weeks", 4, 3)`;
    - add `test_v5_database_upgrades_to_v6`: build a v5 file by hand with one row at `order_cycle_months = 3` and one log line. After opening it:
      - `get_settings()["A"].order_cycle_weeks == 4`;
      - `PRAGMA user_version == 6`;
      - still one log line;
      - the `order_cycle_months` column still holds 3;
      - opening it again changes nothing.
    - add a check that an old `order_cycle_months` log line still reads back with that field.
  - **`test_api.py`:**
    - parametrize the cycle validation over `0, 53, 1.5, "4", None` and a missing key, with the weeks error text;
    - the default and round-trip test expects 4, then 3 after a PUT;
    - add `test_saved_month_cycle_run_shows_recalculate`:
      - inject into a tmp DB a run whose `result_json` has its SKUs' `order_cycle_weeks` key replaced by `order_cycle_months: 3` (the same sqlite approach as `test_saved_run_hides_shelf_life_and_mtd_warnings_stored_earlier`);
      - GET returns `order_plan` null and `plan_counts` null;
      - `/suppliers` gives `order_cycle_weeks` null;
      - `/export` returns 200;
      - `/recalculate` returns a weekly order plan.
  - **`test_summary.py`:**
    - `_cycle_three_cfc` becomes a 3-week cycle;
    - assert `months[i] is None` exactly where no SKU's month has an order date;
    - `months[0] >= cfc.plan_total_order_qty`;
    - blocked `order_cycle_weeks == 4`;
    - the old-run test sets `order_cycle_weeks`.
  - **`test_export.py`:** expected headers say "Order Cycle (weeks)", and the values are the weeks.

- [ ] **Step 2: Run the backend suite.** Expected: the new and renamed tests fail, on attribute errors for `order_cycle_weeks`, `drop_monthly_order_plan` imports, and the 422 text.

- [ ] **Step 3: Implement** the Interfaces above.

- [ ] **Step 4: Run the backend suite.** Expected: everything passes.

- [ ] **Step 5: Commit.**

```bash
git add backend/app backend/tests
git commit -m "feat: order cycle in weeks (schema v6) driving the weekly order plan; older runs ask to recalculate"
```

### Task 3: Order Dates export sheet

**Files:**
- Modify: `backend/app/export.py`
- Test: `backend/tests/test_export.py`

**Interfaces:**
- **Consumes:** `MonthPlan.orders` from Task 1.
- **Produces:** a sheet "Order Dates", placed right after "Order Plan".
  - Headers: `["Principal", "SAP Code", "Description", "Order Date", "Order Qty", "MOQ Applied"]`.
  - Rows: one per order line with qty > 0, sorted by (principal, date, description, SAP code).
  - Dates use the existing `DATE_FORMAT`; MOQ Applied is `_yes_no`.
  - An older run (no order plan) gets the headers only.

- [ ] **Step 1: Write the failing tests.**
  - `test_order_dates_sheet`:
    - the sheet order is `[..., "Order Plan", "Order Dates", "Principal Summary", ...]`;
    - the rows equal the expected list built from `run.result.skus` lines with qty > 0, sorted;
    - the date cells have number_format `yyyy-mm-dd`.
  - `test_order_dates_sheet_empty_for_old_run`: only the header row.

- [ ] **Step 2: Run** `pytest backend/tests/test_export.py`. Expected: a KeyError for the "Order Dates" sheet.

- [ ] **Step 3: Implement it** with `_write_sheet`.

- [ ] **Step 4: Run the backend suite.** Expected: everything passes.

- [ ] **Step 5: Commit.**

```bash
git add backend/app/export.py backend/tests/test_export.py
git commit -m "feat: Order Dates sheet with one row per planned order"
```

### Task 4: Frontend types, helpers and the weeks rename

**Files:**
- Modify:
  - `frontend/src/types.ts`;
  - `lib/settings.ts`, `lib/format.ts`, `lib/mode.ts`;
  - `pages/SettingsPage.tsx`, `pages/SupplierPage.tsx`, `pages/PlanPage.tsx`;
  - `components/SkuDetail.tsx` (rename only).
- Test: `lib/settings.test.ts`, `lib/format.test.ts`, `lib/mode.test.ts`

**Interfaces:**
- **Produces in `types.ts`:**
  - `export interface OrderLine { date: string; qty: number; moq_applied: boolean }`;
  - `MonthPlan.orders: OrderLine[]`;
  - `order_cycle_months` is renamed `order_cycle_weeks` on `SkuResult`, `SupplierSettings`, `SupplierSummary` and `SupplierSettingView`;
  - `SettingField` gains `'order_cycle_weeks'` and keeps `'order_cycle_months'` for history.
- **Produces in `settings.ts`:**
  - `ORDER_CYCLE_MAX = 52`;
  - `validateOrderCycle` takes whole weeks from 1 to 52 and returns the weeks error text;
  - `logValue('order_cycle_weeks', 4) === '4 weeks'` and `'1 week'`, while `'order_cycle_months'` keeps its months text;
  - `EditedSettings` and `changedSettings` use `order_cycle_weeks`.
- **Produces in `format.ts`:**
  - `fmtCycle(weeks: number | null): string`: `'—'`, `'every week'` or `'every 4 weeks'`;
  - `fmtCycleShort(weeks: number | null): string`: `'—'` or `'4 wk'`.
  - In plan mode, `orderExplanation` gives the level line as `Order-up-to = 120 × (3 − 1 + 4 × 12 ÷ 52) months = 350.7692`. When the holding is below 1 month it gives `Order-up-to = 120 × 2 × 12 ÷ 52 months = 55.3846 (one cycle's demand; the holding is under 1 month)`. In plan mode it also adds, right after the required/MOQ lines, `This is the order on <plan date>; the next orders are listed under Orders.`
- **Produces in `mode.ts`:**
  - `placedOrders(m: MonthPlan): OrderLine[]`: the lines with qty > 0;
  - `ordersTitle(m: MonthPlan): string`: for example `"2 Jan: 108\n30 Jan: 109"` (day and short month via the existing date formatting).
- **Pages:**
  - Settings: the column header is "Order cycle (weeks)"; aria `Order cycle weeks for <name>`; field labels map both `order_cycle_weeks` → "Order cycle (weeks)" and `order_cycle_months` → "Order cycle (months)"; the intro sentence says weeks.
  - Supplier page: "Order cycle (weeks)".
  - Plan page: the column shows `fmtCycleShort`.
  - SkuDetail: the facts show `fmtCycle`.

- [ ] **Step 1: Write the failing tests.**
  - `settings.test.ts`: the weeks validation table (`'0'`, `'53'`, `'1.5'`, `''`, `'abc'` are errors; `'1'`, `'4'`, `'52'` are OK); `logValue` for weeks and months; fixtures renamed.
  - `format.test.ts`:
    - the plan-mode explanation for the spec example (holding 3, cycle 4, buffer 120) gives the level line above;
    - a holding of 0.5 on cycle 2 gives the floored line;
    - the plan-date line is present in plan mode only;
    - `fmtCycle` / `fmtCycleShort` cases;
    - fixtures renamed and given `orders: []`.
  - `mode.test.ts`: `placedOrders` drops 0-qty lines; `ordersTitle` formats two lines; fixtures renamed.

- [ ] **Step 2: Run** `npm --prefix frontend test -- --run`. Expected: failures on the new names and helpers.

- [ ] **Step 3: Implement** the Interfaces.

- [ ] **Step 4: Run** the tests, `npm --prefix frontend run build` and `npm --prefix frontend run lint`. Expected: all pass with a clean build.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src
git commit -m "feat: order cycle in weeks on the settings, plan and principal pages; weekly order-up-to explained"
```

### Task 5: Month order marker, SKU detail orders list, README

**Files:**
- Modify: `frontend/src/pages/PlanPage.tsx`, `frontend/src/components/SkuDetail.tsx`, `frontend/src/index.css` (only if a style is needed), `README.md`

**Interfaces:**
- **Consumes:** `placedOrders` and `ordersTitle` (Task 4); `fmtDate` and `fmtQty`.
- **Plan page `MonthCell`:** in plan mode, an order month with `placedOrders(m).length > 1` adds `<span className="chip chip-grey tag" title={ordersTitle(m)}>{n} orders</span>` after the quantity.
- **Plan page footnote (plan mode):** `Each principal is ordered from every order cycle (in weeks), starting on the plan date: each order brings stock (sellable plus SIT) up to the order-up-to level, buffer × (holding − 1 + cycle weeks × 12 ÷ 52), never less than one cycle's demand. A month cell is that month's total; · marks months without an order.`
- **SkuDetail:**
  - The plan-mode note reads `Orders are placed every N weeks from the plan date; each month is the total of its orders, and · marks months without one.`
  - After the 12-month table in plan mode, add an `<h3>Orders</h3>` table with columns Date, Quantity and MOQ. It lists every line of `view.months`, including 0-qty lines (shown as 0). It is hidden when holding is not set.
- **README:** in the order plan section,
  - describe the cycle in weeks (default 4, re-enter per principal);
  - describe order dates, the daily demand, the order-up-to formula with the floor, and the worked example table (section 3 of the spec);
  - describe the "2 orders" marker, the Orders list and the Order Dates sheet;
  - describe the v6 upgrade and that older runs ask to recalculate.

- [ ] **Step 1: Implement** the marker, the footnote, the note, the Orders table and the README.

- [ ] **Step 2: Run** the frontend tests, build and lint, and the backend suite. Expected: all green.

- [ ] **Step 3: Check it in the browser against a copy of the planner's database.**
  - Copy `backend/data/orderplan.db` to the scratchpad.
  - Start the `backend-test` / `frontend-test` launch configs (8001/5174) with `ORDERPLAN_DB` pointed at the copy.
  - Open the latest run: plan mode shows "Recalculate to see the order plan." Recalculate the copy.
  - Fish Sauce 3202111003 (holding 2, cycle 4) shows Order-up-to ≈ 4,668.
  - A month with two orders shows the marker, and hovering lists both dates.
  - The SKU detail lists the orders.
  - The Settings page shows "Order cycle (weeks)" with 4 for everyone.
  - The export opens with the Order Dates sheet.
  - Stop only the servers you started.

- [ ] **Step 4: Commit.**

```bash
git add frontend/src README.md
git commit -m "feat: mark months with several orders and list each order in the SKU detail; README for the weekly cycle"
```
