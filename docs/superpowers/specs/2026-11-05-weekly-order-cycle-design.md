# Weekly Order Cycle — Design

Date: 2026-11-05
Status: Draft for review
Builds on: `2026-10-29-order-cycle-design.md` and the changes since (Order-up-to shown in place of Target in Order plan mode; shelf life and MTD warnings dropped). Everything not mentioned here stays as built.

## 1. Why this change

The order cycle is set in whole months today. In practice principals are ordered from every few weeks, for example once every 3 or 4 weeks. The planner wants the order plan to follow a cycle in **weeks**.

## 2. What the planner decided

- **Every principal's order cycle is in weeks.** There is no months option any more.
- **Existing month values are not converted.** The planner re-enters each principal's cycle by hand. Until then every principal uses the **default of 4 weeks**.
- **The plan keeps its 12 month columns.** A month cell shows the total ordered in that month. When more than one order falls in a month, the cell says so (for example "2 orders"). Each order is listed separately with its date in the SKU detail and in a new Excel sheet. (The planner asked for a suggestion and agreed to this one.)
- **Order-up-to keeps today's rule (option A):** just before the next order, stock has fallen to holding − 1 month, as it does today with monthly ordering. That gives order-up-to = buffer × (holding − 1 + cycle weeks × 12 ÷ 52). The other option, never dipping below the holding (buffer × (holding + cycle weeks × 12 ÷ 52)), was rejected because it carries about one extra month of stock on every SKU.
- **Order-up-to is floored at one cycle's demand.** This stops a holding under 1 month on a short cycle from giving a level below zero and never ordering. Blocking such settings was the other option.
- **Holding stays in months and lead time in days.** The demand inputs (actuals, sales forecast, buffer) stay monthly.
- **Order demand forecast mode is unchanged.** It still tops stock up to the target every month and does not use the cycle.

## 3. The calculation (per SKU, order plan only)

Inputs: the SKU's buffer, holding, MOQ and available stock as today, the plan date, and the principal's **cycle** (whole weeks, 1–52).

- **Order dates:** the plan date, then every `7 × cycle` days after it, for as long as the date is on or before the last day of plan month 12. The first order is always on the plan date. (Cycles still start on the plan date for every principal; a per-principal start from order history comes later.)
- **Order-up-to** = buffer × (holding − 1 + cycle × 12 ÷ 52). For example, Fish Sauce (buffer 2,427.32, holding 2) on a 4-week cycle gives 2,427.32 × 1.923 ≈ 4,668. None when holding is not set.
- **Floor (the planner's decision):** order-up-to is never below one cycle's demand, buffer × cycle × 12 ÷ 52. This only matters for a holding under 1 month. Without the floor, holding 0.5 on a 2-week cycle would give a negative level and the SKU would never order. With it (buffer 1,000): max(1,000 × (−0.5 + 0.462), 1,000 × 0.462) ≈ 462, so each order lasts until the next one and stock reaches about 0 just before it. For a holding of 1 month or more the floor never applies. The "How this is worked out" text says when the floor was used.
- **Demand by day:** each day uses its month's demand (`monthly_demand`, the buffer for now) ÷ the number of days in that month. Every full month therefore uses exactly its monthly demand. **Plan month 1 counts only the days from the plan date to the end of the month**, because the available stock is as of the plan date (the MTD end).
- **Stock day by day, from the plan date to the end of plan month 12:**
  - stock starts at available;
  - on an order date, before that day's demand: required = max(order-up-to − stock, 0), rounded up to whole cartons with today's epsilon; order = required, raised to the MOQ when 0 < required < MOQ (today's rule); stock += order;
  - then stock −= that day's demand.
- **Per month (what the screens and export show):** opening = stock at the start of the month's first planned day (available for month 1); demand = the sum of its planned days; order = the sum of the orders dated in it (0 when none); closing = opening + order − demand. A month is an **order month** when at least one order is dated in it.
- **Plan date after plan month 1** (my call: this happens when the MTD ends on the last day of its month, so the plan date is the 1st of the next month while plan month 1 is still the MTD month): plan month 1 has no planned days. Its demand and order are 0, it is not an order month, and its closing equals available. The schedule runs from the plan date as above, through months 2–12. This month's order is still the plan-date order. The plan months, the forecast mode and the column headings stay as they are.
- **This month's order-plan order** (the "Order qty" in Order plan mode, the status, the counts and the purchase-order lines) is **the order on the plan date**. A second order later in plan month 1 shows in month 1's total but is not part of this month's purchase order.
- Order quantities vary a little from one order to the next because months have different numbers of days (February's daily demand is higher). Rounding up to whole cartons adds the same small variation as today.
- **Special cases**, as today: **holding not set** → every order is null ("—") and stock still rolls down; **no demand data** → every order is 0; with the floor, a holding below 1 month plans stock down to about 0 before each order, never below.
- **Worked example** for tests: buffer 120, holding 3, available 260, MOQ 0, cycle 4 weeks, plan date 2026-10-10, plan months Oct 2026 – Sep 2027. Order-up-to = 120 × (2 + 48 ÷ 52) ≈ 350.769.

  | Month | Opening | Demand | Orders | Month total | Closing |
  |---|---|---|---|---|---|
  | Oct 2026 | 260.00 | 85.16 (22 of 31 days) | 10 Oct: 91 | 91 | 265.84 |
  | Nov 2026 | 265.84 | 120.00 | 7 Nov: 109 | 109 | 254.84 |
  | Dec 2026 | 254.84 | 120.00 | 5 Dec: 112 | 112 | 246.84 |
  | Jan 2027 | 246.84 | 120.00 | 2 Jan: 108, 30 Jan: 109 | 217 | 343.84 |
  | Feb 2027 | 343.84 | 120.00 | 27 Feb: 119 | 119 | 342.84 |
  | Mar – Sep 2027 | | 120.00 each | 27 Mar 109, 24 Apr 111, 22 May 110, 19 Jun 110, 17 Jul 110, 14 Aug 109, 11 Sep 109 | | 270.84 (Sep) |

  13 orders, 1,416 in total.

## 4. Order cycle setting

- **Order cycle (weeks)** on the Principal settings page replaces Order cycle (months): a whole number from **1 to 52**, default **4**, never blank.
- Validation errors name the principal in the existing style, for example "Principal 'Acme': order cycle must be a whole number of weeks from 1 to 52."
- Every change is a line in the change log (setting "Order cycle (weeks)").
- Saving settings recalculates the latest run, as today.
- **Database v6:** `supplier_settings` gains `order_cycle_weeks INTEGER NOT NULL DEFAULT 4`, added in one transaction like v5, and the schema version becomes 6. Every existing principal gets 4. The old `order_cycle_months` column stays in the table but is no longer read or written. No change-log lines are written for the default. Old `order_cycle_months` change-log lines stay in the log as history.
- The settings API takes and returns `order_cycle_weeks` in place of `order_cycle_months`.

## 5. Results and storage

- Each SKU result records the cycle in weeks. Each order-plan month gains the list of its orders: date, quantity and MOQ applied. The existing month fields (opening, demand, order, MOQ applied, closing, order month) keep their meaning, with `order` as the month total and MOQ applied true when any of its orders was raised. Field names are the builder's call.
- The plan's settings used record each principal's cycle in weeks.
- `plan_order_up_to`, `plan_required`, `plan_order_qty`, `plan_moq_applied` and `plan_status` are as today but use the weekly rule and the plan-date order.
- The principal summary's order-plan monthly totals sum the month totals; its "SKUs to order" and "total order qty" for this month use the plan-date order.
- **Older runs** (saved with a cycle in months) show "Recalculate to see the order plan", like runs saved before the order cycle existed. Recalculate fills in the weekly plan with the current settings. Their forecast mode keeps working.

## 6. Screens

1. **Principal settings page:** the column reads "Order cycle (weeks)". The intro sentence explains it in weeks.
2. **Plan page:** in the Principal settings column group, the cycle shows as weeks (for example "4 wk"). In Order plan mode a month cell shows the month total. A month with more than one order also shows a small marker with the count (for example "2 orders"), and hovering it lists the dates and quantities. Months without an order read as today's non-order months. The footnote explains the weekly order-up-to.
3. **SKU detail** (Order plan mode):
   - the facts list shows the cycle in weeks;
   - "How this is worked out" reads like "Order-up-to = 2,427.32 × (2 − 1 + 4 × 12 ÷ 52) months = 4,668.0" and explains that the order is the one placed on the plan date;
   - the 12-month table keeps its month rows (Month, Opening, Demand, Order, Closing). It is followed by an **Orders** list with one row per order date (Date, Quantity, MOQ tag).
4. **Principal summary page:** unchanged apart from the cycle shown in weeks; month totals and this month's purchase-order lines follow section 5.
5. **Excel export:**
   - "Order Cycle (months)" becomes **"Order Cycle (weeks)"** in every sheet that has it.
   - The Order Plan sheet keeps one column per month with the month total (blank for months without an order).
   - A new sheet **"Order Dates"** after "Order Plan": Principal, SAP Code, Description, Order Date, Order Qty, MOQ Applied. One row per SKU per order date with an order above 0, sorted by principal, date, description and SAP code. SKUs whose holding is not set have no rows.
6. **README:** describe the weekly cycle, the order-up-to rule, the worked example and the v6 upgrade.

## 7. Non-goals

- A per-principal start date or last-order date (later, from the database).
- Shifting orders by lead time.
- Weekly columns on the plan page.
- Any change to the order demand forecast mode.
- Converting old month cycles into weeks.

## 8. Left to the builder

- Model and field names. Where the day-by-day roll-forward lives (suggestion: `holding.py`, next to `roll_forward`, which stays for the forecast mode).
- The exact look of the "2 orders" marker and the Orders list.
- **Tests** must cover:
  - the worked example in section 3 exactly (order dates, quantities, month totals and closings);
  - the order-up-to formula for a few cycles (1, 4, 52 weeks), and the floor (holding 0.5 on 1- and 2-week cycles gives one cycle's demand; holding 2 never floors);
  - a plan date on the 1st of the month after plan month 1 (month 1 empty, the first order in month 2, still this month's order);
  - order dates stopping at the end of plan month 12, including a 52-week cycle (one order only);
  - month 1 demand counted from the plan date; February's daily demand;
  - MOQ raising one order in a month with two orders (the month is flagged as MOQ applied);
  - holding not set (null orders) and no demand data (0 orders);
  - the plan-date order driving this month's Order qty, status, counts and purchase-order lines;
  - cycle validation (0, 53, 1.5, text, missing) with principal-named errors;
  - the v6 upgrade of a v5 database (default 4 for everyone, old column left alone, no log lines, runs again safely);
  - an older run showing "Recalculate" in Order plan mode and getting a weekly plan after Recalculate;
  - the Order Dates export sheet and the renamed cycle columns;
  - the frontend helpers for the month marker and the cycle label.
