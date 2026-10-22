# Order Plan Tool — Design

Date: 2026-10-22
Status: Draft for review

## 1. Intent

Each planning cycle, the Dry Food Local Principals planner receives a forecast for every SKU (monthly in-market sales, IMS) plus current stock and pending orders. Today, turning that into "what do we order, from whom, and when" is done by hand in a large Excel workbook (`by sku`, `Pivot.by supplier`, weekly `TRACKING SHEET`s). That workbook has grown to 41 sheets, carries stale copies from earlier cycles, and is full of broken formulas.

This tool replaces that manual step. The planner uploads the cycle's input file, and the tool calculates the order plan automatically: for each SKU, when to order and how many cartons, rolled up by supplier.

The forecast is an **input**, not something the tool produces.

## 2. Users and usage

- Primary user: the planner (single user), running the tool on their own computer.
- Usage rhythm: once per planning cycle (roughly monthly, with mid-month refreshes), upload → review → adjust supplier settings → re-run → export.
- Output is reviewed in supplier meetings, so it must be easy to explain *why* each order is suggested.

## 3. Goals

1. Upload the input Excel file and get a complete order plan without manual formulas.
2. Per-supplier ordering rules (reorder level and target level, in days of sales) that the planner sets once and the tool remembers.
3. Show, per SKU, the week-by-week projected stock and the orders that keep it between the reorder and target levels.
4. Highlight what needs action now: SKUs that must be ordered immediately, SKUs at risk of running out before an order can arrive, and SKUs holding excess stock.
5. Summarize by supplier.
6. Export the plan to Excel.
7. Keep a history of past runs.

## 4. Non-goals (for now)

- Generating or adjusting forecasts.
- Splitting orders between Yangon and Mandalay (the input has no regional forecast split). One order quantity per SKU.
- Money values. The input has no prices, so the plan is in cartons only.
- Sending purchase orders to suppliers or integrating with SAP.
- Multiple users, logins, or hosting on a server.

## 5. Anti-goals (would make it a failure even if it "works")

- A black box. Every suggested order must be traceable to the numbers that caused it (stock, forecast, lead time, settings).
- Silently altering the planner's input numbers. Any cleaning (e.g. negative sales treated as zero) must be visible as a warning.
- Requiring the planner to reshape their file. The tool reads the file as it is produced today.

## 6. Constraints (decided by the planner)

- Frontend: **React**.
- Backend: **Python, FastAPI**.
- Database: **SQLite**.
- Runs locally on the planner's Windows computer.
- UI is a web page in the browser.

## 7. Input file

File: `Local Principals data for Demand Forecasting Tool.xlsx`. Only the **`Data`** sheet is used (planner's decision). The other sheets (`PDG PV`, `PDG Stock List`, `PG PV`, `PG Expiry Check`, `WH Code info`) are raw system exports that the planner already rolls up into `Data`; the tool ignores them for now.

How the stock columns are derived (verified against the sample: exact match):
- `Sellable (PG)` / `Non-Sellable (PG)` = `PG Expiry Check` `Ctn` summed per `Item Code`, split by `Location` (Sellable / Non-Sellable).
- `Sellable (PDG)` / `Non-Sellable (PDG)` = `PDG Stock List` `cs` summed per `StockCode`, split by `Sell or Non` (blank = sellable, `Non` = non-sellable).
- Totals = PG + PDG.

Possible later extension: read those sheets directly to build the stock columns and to use batch expiry dates (`expired Date` / `Day Left`, `ExpMonth`) for expiry risk. Note that `PG Expiry Check` holds stock for 32 item codes that are not in `Data` (mostly Myanmar Vineyard Estate under a different code format, plus Constellation); a code mapping would be needed.

Layout of `Data`:
- Row 1: empty. Row 2: column totals (ignore). Row 3: headers. Row 4 onward: one row per SKU (212 SKUs in the sample, 17 suppliers).

Columns used:

| Header (as in file) | Meaning | Notes from sample |
|---|---|---|
| `SAP Code` | SKU id | Read as text. Unique. |
| `By Principal` | Supplier | Groups SKUs; key for supplier settings. |
| `Description` | SKU name | |
| `Packing Size` | Units per carton | Display only. |
| `MOQ` | Minimum order quantity, cartons | All 0 in sample (0 = no minimum). |
| `Shelf Life month` | Shelf life in months | Numeric, or `-` (43 SKUs) meaning no expiry; some `0` (treat as unknown/no cap). |
| `Lead Time` | Days from order to arrival | Values 3, 7, 14, 21, 30. |
| `Total Sellable (Ctns)` | Sellable stock on hand | Sum of PG + PDG. |
| `Total Non-Sellable (Ctns)` | Damaged/expired/blocked stock | Shown, not used in the calculation. |
| `SIT Ctns (pending order)` | Stock in transit / already ordered | 44 SKUs > 0. |
| `Oct'26  MTD Sale (1-11 Oct)` | Sales so far this month | Header carries the month and date range. 10 SKUs negative (returns). |
| `2026 Oct IMS` … `2027 Sep IMS` | Monthly forecast, cartons | 12 months. 118 SKUs have all-zero forecast. |

Header matching should be tolerant of extra spaces and should detect the forecast months and the MTD column by pattern (`YYYY Mon IMS`, `... MTD Sale (d1-d2 Mon)`), not by fixed position, so next month's file (e.g. Nov MTD, Nov–Oct forecast) works without code changes.

Upload validation: reject the file with a clear message if the `Data` sheet or required columns are missing; warn (don't reject) on per-row problems (non-numeric values, negative MTD, missing lead time).

## 8. Supplier settings

Per supplier (from `By Principal`):
- **Reorder level** (days of sales, including lead time): when stock plus orders already on the way drops below this, place an order.
- **Target level** (days of sales, including lead time): an order brings stock plus orders on the way back up to this.

Rules:
- Stored in SQLite; persist across runs.
- New suppliers seen in an upload get default values (*builder's call: 20 / 30 days*) and are flagged so the planner notices.
- Target must be greater than reorder level.
- Editable on a settings page; changing settings re-runs the plan for the current upload.

## 9. Calculation

The planner agreed the ordering rule is "reorder level / target level per supplier, order only when stock starts running low."

Per SKU, starting from the **plan date** (as-of date):

1. **Plan date.** The day after the MTD period end parsed from the MTD header (e.g. `1-11 Oct` → 12 Oct 2026). The planner can override it on upload.
2. **Daily demand.** Each forecast month's quantity is spread evenly over its days. For the current month, the remaining demand is `max(Oct forecast − max(MTD, 0), 0)` spread over the days from the plan date to month end. If MTD already exceeds the month forecast, remaining demand for the month is 0 and the SKU is flagged.
3. **Starting stock** = Total Sellable + SIT. (*Builder's call: SIT is treated as available from the plan date, because arrival dates are not in the input. Flag as an assumption in the UI.*)
4. **Days of sales → cartons.** "N days of sales" at a given day means the forecast demand over the following N days (forward-looking). Near the end of the forecast horizon, use the last month's daily rate for days beyond it.
5. **Projection.** Simulate day by day to the end of the forecast horizon: stock decreases by daily demand and increases when a planned order arrives. Stock may go negative in the projection (this represents unmet demand / stock-out) and must be flagged.
6. **When to order.** The reorder level **already includes the lead time** (planner's decision): "when cover drops to X days, place the order." Track the *inventory position* = projected stock on hand + planned orders not yet arrived. Find the first day *d* (on or after the plan date) where the inventory position falls below the reorder level at *d*. That day is the **order date**; the **arrival date** is *d + lead time*.
   - If the inventory position is already below the reorder level on the plan date, the order date is the plan date and the SKU is flagged **Order now**.
   - If projected stock on hand reaches 0 before the arrival date, flag **Stock-out risk** with the number of days and cartons short.
   - If a SKU's lead time is greater than or equal to its supplier's reorder level, warn on the settings page and on the SKU: with that setting the SKU will run out before each order arrives.
7. **How much.** Quantity = target level (in cartons, at the order date) − inventory position at the order date, where on-hand stock is floored at 0. The target level, like the reorder level, is measured at the order date and so also includes lead-time demand. (*Builder's call: sales missed during a stock-out are lost, not backordered, so the order refills from zero rather than adding the shortfall back. In the projection, stock is floored at 0 and the lost cartons are reported as the stock-out size.*) Then:
   - round up to whole cartons;
   - if MOQ > 0, raise to at least MOQ (*builder's call: MOQ is a minimum, not a multiple*);
   - **shelf-life cap**: if shelf life is known (> 0), stock after arrival must not exceed forecast demand over the shelf-life period; cap the quantity, and flag **MOQ exceeds shelf-life cover** if MOQ forces it above the cap. (*Builder's call: `Shelf Life month` is treated as the full shelf life available from arrival. Real batch expiry dates in `PG Expiry Check` are not used in this version.*)
8. Repeat from step 6 after adding the order, until the end of the horizon. This yields a list of planned orders per SKU (order date, arrival date, cartons).
9. **SKUs with zero forecast** get no orders. If they hold sellable stock, flag **No forecast, holding stock**.
10. **Excess stock**: flag SKUs whose starting stock exceeds the target level (*builder's call: flag when current days of cover > target × 1.5*), and SKUs whose stock will not sell before shelf life ends.

Every number used for an order (stock at arrival, reorder/target in cartons, lead time, cap applied) is kept with the order so the UI can show "why".

## 10. Screens

1. **Upload**: choose file, see detected plan date (editable), see validation warnings, run.
2. **Order plan (main view)**
   - Top: counts of Order now / Stock-out risk / Excess / No forecast.
   - Table, one row per SKU: supplier, SKU, description, stock, SIT, days of cover today, next order date, next order qty, arrival date, flags. Filter by supplier, flag, and "orders due within next N weeks" (default 4). Sort by order date.
   - SKU detail (click a row): week-by-week projection table and a simple chart of projected stock against the reorder and target lines, with order arrivals marked, and the "why" for each order.
3. **Supplier summary**: per supplier, SKUs needing orders, total cartons to order in the next 4 weeks, earliest order date, flag counts. Expanding a supplier lists every SKU with an order due in the chosen window, so the planner can put them on one purchase order.
   (*Builder's call: the planner wasn't sure whether they order SKU by SKU or one order per supplier. The engine calculates each SKU separately; grouping is only in this view. Combining SKUs into one supplier order on a fixed cycle is a possible later change.*)
4. **Supplier settings**: editable table of reorder/target days.
5. **Run history**: past runs (date, file name, plan date) with the ability to reopen.
6. **Export**: Excel download with sheets for the SKU plan, all planned orders, supplier summary, and the settings used.

Weekly buckets in the UI start from the plan date (week 1 = plan date + 0..6 days). The underlying simulation is daily.

## 11. Storage (SQLite)

- Supplier settings (current values).
- Runs: upload metadata, plan date, a snapshot of the settings used, the parsed input rows, and the results (orders, flags). Reopening a run shows exactly what was calculated then, even if settings have since changed.

## 12. Left to the builder

- Project layout, frontend tooling (e.g. Vite), UI component and chart libraries, Excel reading/writing libraries.
- API shape between frontend and backend.
- How runs are stored (normalized tables vs. JSON blobs).
- Visual design.
- Test approach. The calculation engine must have unit tests covering the rules in section 9 (including late orders, MOQ, shelf-life cap, zero forecast, negative MTD, MTD above forecast).

## 13. Known limitations

- **No order tracking.** The tool does not record which suggested orders were actually placed. Orders placed since the last upload only count once they appear in the input's `SIT Ctns (pending order)` column; until then a mid-month re-run will suggest them again. Replacing the weekly TRACKING SHEETs (recording placed orders and arrivals) is out of scope for this version.
- SIT arrival timing is unknown (see section 9, step 3).

## 14. Notes

- The project folder `C:\projects\DemandForecasting` is currently empty and is not a git repository.
- Sample input: `C:\Users\linnyiaung\Downloads\Local Principals data for Demand Forecasting Tool.xlsx` (Data sheet: header on row 3, totals on row 2, 212 SKUs; `Shelf Life month` contains `-` and `0`; values are plain numbers). The builder should copy it into the project as a test fixture.
- Acceptance check: before sign-off, the planner reviews the tool's suggested orders for a handful of SKUs they know well (e.g. one SKU each from Honesty, Ya Thar Taw Win, Glamdust/CMP Fruits Garden) against their own judgement.
- Calls marked *builder's call* above were made during design, not by the planner, and should be confirmed in review.
