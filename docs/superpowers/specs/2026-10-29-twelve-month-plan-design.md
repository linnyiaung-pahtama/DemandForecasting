# 12-Month Order Plan — Design

Date: 2026-10-29
Status: Draft for review
Builds on: `2026-10-23-holding-based-order-plan-design.md` (v2), `2026-10-28-stock-files-design.md`, `2026-10-29-supplier-moq-lead-time-design.md`. Everything not mentioned here stays as built.

## 1. Why this change

Today the tool answers one question: how much to order **this cycle**. The planner wants to see how much to order in **each of the next 12 months**.
- Later, actual sales and forecasts will arrive regularly from a database, and a 12-month plan will be made each cycle.
- For now the inputs are the same as today: the past 3 months of sales and the next 3 months of forecast.

## 2. What the planner decided

- The plan covers **12 months**, with a row per SKU and a column per month, showing **how much to order** in each month.
- **For now, the forecast for each of the 12 months is the buffer**: the average of the valid values among the past 3 months' sales and the next 3 months' forecast (v2 section 6, step 1). It is the same number every month.
  - This means the Data sheet's forecast months 4–12 (`2027 Jan IMS` … `2027 Sep IMS`) are not used by the 12-month plan.
- The planner agreed to these proposals:
  - **Month 1 is today's order.** Each later month rolls stock forward (section 3), so an MOQ order is followed by months with no order until the stock runs down.
  - **Orders arrive within the month they are placed.** Lead time does not shift them.
  - **Blocked and no-demand SKUs:** "Holding not set" SKUs show no orders; "No demand data" SKUs show 0.
  - **Where it shows:**
    - a 12-month view on the Order plan page with the same filters;
    - total cartons per supplier per month on the Supplier summary;
    - a "12-Month Plan" sheet in the Excel export.

## 3. The calculation (per SKU)

- **Months:** the MTD month (the plan month, the first forecast-window month) and the next 11. For the current file that is Oct 2026 – Sep 2027.
- **Demand per month** = the SKU's buffer. With no valid values there is no buffer, and demand is 0.
- **Target stock** = buffer × holding, the same every month, exactly as today.
- **Month 1:**
  - opening stock = available (Total Sellable + SIT);
  - order = today's `order_qty`, unchanged, including the MOQ rule;
  - closing stock = opening + order − demand.
- **Each later month:**
  - opening stock = the previous month's closing stock;
  - required = max(target − opening, 0), rounded up to whole cartons (the same epsilon handling as today);
  - order = required, raised to the supplier's MOQ when 0 < required < MOQ (today's rule; MOQ 0 = no minimum);
  - closing stock = opening + order − demand.
- **Special cases:**
  - **Holding not set:** every month has no order ("—" / null). Opening and closing stock still roll forward with orders of 0, so the planner sees the stock running down.
  - **No demand data:** demand 0, and every order is 0, as today. Stock stays flat.
  - **Negative available:** handled by the same formula. The month-1 order brings stock up to target, as today.
- **Full months:** each month's demand is the whole buffer, including month 1, even though the plan date is mid-month. This is the builder's call, made in design; it matches today's target, which is also a whole-month figure.
- **Worked example** (v2's example: buffer 120, holding 3 → target 360, available 260, MOQ 150):

  | Month | Opening | Order | Demand | Closing |
  |---|---|---|---|---|
  | 1 | 260 | 150 (MOQ; required 100) | 120 | 290 |
  | 2 | 290 | 150 (MOQ; required 70) | 120 | 320 |
  | 3 | 320 | 150 (MOQ; required 40) | 120 | 350 |
  | 4 | 350 | 150 (MOQ; required 10) | 120 | 380 |
  | 5 | 380 | 0 | 120 | 260 |
  | 6 | 260 | 150 (MOQ; required 100) | 120 | 290 |
  | … | | | | |

  With MOQ 0, month 1 orders 100 and each later month orders 120.

## 4. Built for a database source later

The demand for a month comes from **one function**, today returning the buffer for every month. When the database provides monthly forecasts, only that function changes, for example to use each month's own forecast. The roll-forward, MOQ and display stay the same.

## 5. Results and storage

- **Each SKU result** gains `monthly`: a list of 12 entries `{month: "YYYY-MM", opening, demand, order (int or null), closing}`.
- **The plan** gains:
  - `plan_months`: the 12 "YYYY-MM" keys;
  - per-supplier monthly order totals. These may be computed in the summary instead of stored: builder's call.
- **Stored runs** keep this in `result_json`, as today. Runs saved before this change have no `monthly`. They show "Recalculate to see the 12-month plan" in the 12-month view, and Recalculate fills it in, because it re-plans from the stored parsed input.
- **No database schema change** is needed; everything lives in the stored JSON.

## 6. Screens

1. **Order plan page:**
   - A switch between **This cycle** (today's table) and **12 months**.
   - The 12-month table has Supplier, SAP Code, Description, then one column per month (e.g. "Oct 2026") showing the order quantity ("—" when holding is not set), and a **Total** column.
   - The same supplier / status / zero-forecast filters and search apply.
   - Clicking a SKU opens the SKU detail as today.
2. **SKU detail:** a "12-month plan" table with Month, Opening, Demand, Order (with an "MOQ" tag when applied) and Closing. Demand is labelled as the buffer, e.g. "Demand each month = buffer (average of the 6 valid values)".
3. **Supplier summary:** each supplier row gains its order total per month (12 columns) or an expandable monthly breakdown (builder's call on layout), plus a 12-month total.
4. **Excel export:**
   - A new sheet, **"12-Month Plan"**: Supplier, SAP Code, Description, Status, the 12 month columns (order quantities; blank when holding is not set) and Total.
   - A final **Total** row per supplier is not required. The Supplier Summary sheet gains the 12 monthly totals.

**Builder's calls, made in design:**
- **Old runs without `monthly`:** the Supplier summary's monthly columns and the export's "12-Month Plan" sheet are blank, with "Recalculate to see the 12-month plan" shown on the page.
- **Total column:** shows "—" (blank in the export) for a "Holding not set" SKU, the same as its months.
- **Stock figures:** opening, closing and demand are stored unrounded, like buffer and available today, and shown with the existing exact-number formatting. Orders are whole cartons.

## 7. Non-goals

- Using the Data sheet's forecast months 4–12, or seasonality. "For now" means the buffer only.
- Shifting orders by lead time, or ordering in one month for arrival in another.
- Part-month demand for month 1.
- Money values, budgets or cash flow.
- Rounding to pallets or packs beyond the MOQ rule.
- Editing future orders by hand.

## 8. Left to the builder

- Model names and where the roll-forward lives. Suggestion: a function in `holding.py`, e.g. `plan_months(...)`, called from `plan_sku`, with the demand-per-month function from section 4.
- UI layout details: the switch control, column widths, horizontal scrolling for 12 months.
- Whether supplier monthly totals are stored or computed.
- **Tests** must cover:
  - the worked example in section 3, exactly as tabled;
  - MOQ 0;
  - holding not set, with null orders and stock rolling down;
  - no demand data;
  - negative available;
  - month 1 matching today's `order_qty` for every SKU of the real fixture;
  - the plan months for the fixture (Oct 2026 – Sep 2027);
  - supplier monthly totals;
  - the export sheet;
  - an old run without `monthly` loading and getting it after Recalculate.
