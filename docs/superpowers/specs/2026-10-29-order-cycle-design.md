# Order Cycle and Order Plan — Design

Date: 2026-10-29
Status: Draft for review
Builds on: `2026-10-29-twelve-month-plan-design.md`, `2026-10-29-supplier-moq-lead-time-design.md`, and the UI changes since (principal naming, the single 12-month plan table, "Sales forecast" and "Order demand forecast" labels). Everything not mentioned here stays as built.

## 1. Why this change

The 12-month plan today is the **order demand forecast**: every month tops stock back up to buffer × holding, so most SKUs order every month. In practice each principal is ordered from on its own rhythm, for example once every three months. The planner wants an **order plan** that follows that rhythm, while the order demand forecast stays exactly as it is.

## 2. What the planner decided

- **Order cycle** is a new principal setting, in months. Cycle 3 means the principal is ordered from once every three months.
- The **order plan** is a second 12-month plan next to the order demand forecast. The forecast is unchanged.
- In an **order month**, the order is enough to keep stock from starting any month below the holding until the next order month (option A below).
- **For now every principal's cycle starts in the plan's first month** (the MTD month of the Data file; Oct 2026 for the current file). Later, when order history comes from the database, the start can vary per principal (for example Constellation last ordered in September → next order in December). That is not part of this change.
- **Where it shows:** a switch on the plan page between "Order demand forecast" and "Order plan" for the 12 month columns; the planner chose a switch over showing both side by side.
- **The switch controls everything that means "the order".** In order-plan mode, this month's order is the order plan's month 1, and the status, count cards, the Principal summary's totals and purchase-order lines and the SKU detail all follow it. In forecast mode everything is as today. (Without this, a cycle-3 principal would show 6,167 as this month's purchase order next to an order plan of 20,118.)
- The planner agreed to these proposals: default cycle 1; cycle shown in the Principal settings column group; the same switch on the Principal summary page; an "Order Plan" sheet in the Excel export; older runs show "Recalculate to see the order plan".

## 3. The calculation (per SKU)

Inputs are the SKU's buffer, holding, MOQ and available stock as today, plus its principal's **cycle** (whole months, 1–12).

- **Months:** the same 12 plan months as the order demand forecast. Demand per month is the same function (`monthly_demand`, the buffer for now).
- **Order months:** plan month 1, then every `cycle` months: months 1, 1 + cycle, 1 + 2·cycle, … (cycle 3 → Oct, Jan, Apr, Jul; cycle 1 → every month; cycle 12 → Oct only).
- **Order-up-to level** = buffer × (holding + cycle − 1).
- **Each month:**
  - opening = available for month 1, otherwise the previous month's closing;
  - in an order month: required = max(order-up-to − opening, 0), rounded up to whole cartons with the same epsilon as today; order = required, raised to the MOQ when 0 < required < MOQ (today's rule; MOQ 0 = no minimum);
  - in any other month: order = 0;
  - closing = opening + order − demand.
- **Cycle 1 gives exactly the order demand forecast**, month for month. This is a required property (tests).
- **Special cases**, the same as the forecast:
  - **Holding not set:** every month's order is null ("—"); stock still rolls down with orders of 0.
  - **No demand data:** every order is 0 (also in order months), stock stays flat.
  - **Holding below 1 month** (e.g. 0.5) with a cycle above 1: stock can run out before the next order month and closing goes negative. That is what the formula gives; no extra rule.
- **Worked example** (Phwer Htwe, 4201111007 in run 7: buffer ≈ 6,975.6, holding 2, available ≈ 7,784.7, MOQ 0, **cycle 3**; order-up-to = 4 × buffer ≈ 27,902.4):

  | Month | Order | Stock at start of month after the order |
  |---|---|---|
  | Oct 2026 | 20,118 | ≈ 4 months |
  | Nov, Dec | 0 | ≈ 3, then 2 months |
  | Jan 2027 | 20,927 | ≈ 4 months |
  | Feb, Mar | 0 | |
  | Apr 2027 | 20,927 | |
  | Jul 2027 | 20,927 | |

  Total 82,899, the same as the order demand forecast; only the timing differs. With MOQ the totals can differ.
- **Small spec example** for tests (buffer 120, holding 3, available 260, MOQ 0, cycle 3 → order-up-to 600): Oct order 340, Nov 0, Dec 0, Jan order 360 (opening 240), and every 3 months after that 360.

## 4. Order cycle setting

- **Order cycle (months)** on the Principal settings page, next to Holding, MOQ and Lead time: a whole number from **1 to 12**. Default **1**. Blank is not allowed (unlike lead time), because there is always a cycle.
- Validation errors name the principal, in the style of the existing ones, e.g. "Principal 'Acme': order cycle must be a whole number of months from 1 to 12."
- Every change is a line in the change log (setting "Order cycle").
- Saving settings recalculates the latest run, as today.
- **Database v5:** `supplier_settings` gains `order_cycle_months INTEGER NOT NULL DEFAULT 1`; the upgrade is additive in one transaction, like v4, and sets the schema version to 5. Existing principals get 1, so nothing changes until the planner sets a cycle. No change-log lines are written for the default.

## 5. Results and storage

- Each SKU result gains the order plan: 12 entries like the forecast's `monthly` (month, opening, demand, order, MOQ applied, closing) plus a flag saying whether the month is an **order month**. Field names are the builder's call; null for runs saved before this change.
- The plan's settings used record each principal's cycle (null in older runs).
- The SKU's existing status, `order_qty`, `moq_applied` and the plan's counts stay as they are: they are the **forecast-mode** values.
- Each SKU result also gains its **order-plan** values for this month: the order plan's month-1 order (with MOQ applied flag), its order-up-to level, and an **order-plan status** using the same four statuses and rules (Holding not set and No demand data as today; To order when the month-1 order is above 0; otherwise No order needed). The zero-forecast flag is the same in both modes. The plan gains order-plan counts next to the existing counts.
- The principal summary gains, per principal, the order-plan "SKUs to order" and "total order qty" for this month, next to the forecast ones, and the order-plan monthly totals, computed like the forecast's: blank (None) for a blocked principal and for older runs.
- Stored runs keep everything in `result_json`. Older runs show "Recalculate to see the order plan" where the order plan would show; Recalculate fills it in with the current settings.

## 6. Screens

0. **The switch** (**Order demand forecast** | **Order plan**) appears on the plan page and the Principal summary page. It defaults to **Order plan**, the one to act on (with cycle 1 everywhere the two are identical). The chosen mode carries over when moving between the plan page, the Principal summary and back (for example as a URL parameter); builder's call how.
1. **Plan page:**
   - The switch sits above the count cards. In each mode, the count cards, the Status column, the status filter, the 12 month columns with their group heading, and the Total use that mode's values. Settings, sales and stock columns are the same in both.
   - The Principal settings column group gains **Order cycle** (e.g. "3 mo") after Lead time.
   - In the order plan, months that are not order months are shown so they read differently from an order month whose order is 0 (for example a muted dot or blank). Order months with an order above 0 use the existing highlighted quantity and MOQ tag.
   - Filters, search and row selection behave the same in both modes; switching keeps them.
2. **SKU detail** follows the page's mode:
   - the facts list shows the order cycle, and its Order qty and status chip are the mode's;
   - "How this is worked out" shows the mode's arithmetic; in order-plan mode the target line reads like "Order-up-to = 6,975.6 × (2 + 3 − 1) months = 27,902.4" and the required / MOQ lines use it;
   - the 12-month table (Month, Opening, Demand, Order, Closing) shows the mode's stock path; in order-plan mode months that are not order months are marked as in the plan table. (Builder-check point, settled in design: one table that follows the switch rather than extra columns.)
3. **Principal summary page:** follows the mode throughout: the top table's SKUs to order and total order qty, the expanded purchase-order lines (the SKUs whose this-month order is above 0, with that order), and the 12-month table. In order-plan mode each month's total is what goes on that month's purchase order. The principal rows show the order cycle with the other settings.
4. **Principal settings page:** the Order cycle column described in section 4, and the intro text explains it in one sentence.
5. **Excel export:**
   - A new sheet **"Order Plan"** after "12-Month Plan", with the same columns as the 12-Month Plan sheet but "<month> Order Plan" month columns, its own 12-Month Total and the order-plan Status. Months that are not order months are blank; order months show their order (0 included).
   - The SKU Plan sheet stays the forecast-mode view, unchanged apart from the added Order Cycle column.
   - "Order Cycle (months)" is added after "Lead Time (days)" in the SKU Plan, 12-Month Plan, Order Plan and Settings Used sheets, and after "Holding (months)" in the Principal Summary sheet.
   - The Principal Summary sheet keeps its forecast columns and adds "Order Plan SKUs to Order" and "Order Plan Total Order Qty"; its month columns become "<month> Order Demand Forecast", followed by "<month> Order Plan" columns (blank in months that are not order months) and a "12-Month Order Plan Total".
6. **README:** document the setting, the calculation with the worked example, and the v5 upgrade.

## 7. Non-goals

- A per-principal start month or last-order date (later, from the database).
- Shifting orders by lead time.
- Changing the order demand forecast or its forecast-mode values (status, counts, `order_qty`).
- Cycles longer than 12 months or in weeks/days.
- Editing individual planned orders.

## 8. Left to the builder

- Model and field names; where the order-plan roll-forward lives (suggestion: `holding.py`, sharing the month loop with `roll_forward` so cycle 1 stays identical by construction).
- The exact look of non-order months and of the switch (reuse the earlier view-switch style if it fits).
- **Tests** must cover:
  - cycle 1 equal to the order demand forecast for every SKU of the real fixture;
  - the small example in section 3 exactly;
  - cycle 12 (one order) and a cycle that does not divide 12 (e.g. 5 → months 1, 6, 11);
  - MOQ raising an order-month order, and a 0 order in an order month when stock is already enough;
  - holding not set (null orders) and no demand data (0 orders);
  - order-cycle validation (0, 13, 1.5, text, missing) with principal-named errors;
  - the v5 upgrade of a v4 database (default 1, no log lines, idempotent);
  - the order-plan status and counts (a SKU that is No order needed in the forecast but To order in the order plan, e.g. available between holding and holding + cycle − 1 months);
  - principal order-plan totals and this-month SKUs to order / total, including blank for blocked principals;
  - the switch driving the count cards, status filter, Principal summary lines and SKU detail (frontend tests on the pure helpers that pick the mode's values);
  - the Order Plan export sheet and the added Order Cycle columns;
  - an older run loading without an order plan and getting one after Recalculate.
