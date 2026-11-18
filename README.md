# Order Plan Tool

A local tool that turns the planner's Excel forecast, the Actual Sales file and two stock reports into a per-SKU order plan. Each cycle you upload five files (those plus the Stock in Transit file), and you set one holding (in days of stock) per principal. For every SKU the tool works out the average monthly demand, the stock you should hold, and the cartons to order to get there, with every number shown. It rolls the plan up by principal, exports it to Excel, and keeps a history of past runs.

It runs on your own Windows computer: a Python (FastAPI) backend with a PostgreSQL database, and a React web page in the browser.

## Requirements

- Python 3.12
- PostgreSQL (see [Database](#database))
- Node 22.12+ (22 or 24 LTS); needed by vitest 5, and the app uses React 19 and Vite 6

## First-time setup

PowerShell or Git Bash, from the project folder.

Backend (Python 3.12, virtual environment in `backend/.venv`, dependencies in `backend/requirements.txt`):

```
cd backend
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cd ..
```

Frontend:

```
cd frontend
npm install
cd ..
```

## Starting the tool

Open two terminals (PowerShell or Git Bash), both starting in the project folder.

Terminal 1, backend (port 8000):

```
backend/.venv/Scripts/python -m uvicorn app.main:create_app --factory --app-dir backend --port 8000
```

Terminal 2, frontend (port 5173):

```
npm --prefix frontend run dev
```

Then open http://localhost:5173. The frontend forwards `/api` requests to the backend, so both must be running. `.claude/launch.json` holds these two commands for Claude Code's preview, plus two test entries (`backend-test` and `frontend-test`, see the end of this file).

## Using it

1. **New plan**: choose the five files (the Sales Forecast file, the Actual Sales file, the PG Expiry Check, the PDG Stock List and the Stock in Transit file), check the detected months, the stock facts (SKUs with stock, sellable cartons from PG and from PDG, the PDG printed date and the PG as-of date, and the stock in transit: SKUs, cartons and the arrival weeks it covers), the plan date and any warnings, add any **commits** (see [Commits](#commits)), then click Calculate. Calculate is enabled once all five files inspect OK.
2. **Order plan**: a switch between **Order plan** (the default) and **Order demand forecast** decides which plan every order figure on the page comes from (see [Order plan and order cycle](#order-plan-and-order-cycle)); it is kept in the address (`?mode=forecast`) and carries over to the Principal summary. Count cards (To order, Holding not set, No demand data, Zero forecast), a banner listing blocked principals, and filters for principal, status, the Zero forecast flag and search. A warnings panel above the table shows file-level warnings (labelled Sales Forecast file, Actual Sales file, Stock files or Stock in Transit file; the stock report's name is in the message text) in full and counts the per-SKU warnings in a collapsible list. The plan header lists the five file names. The table has one row per SKU, in column groups: principal settings (MOQ, holding, lead time, order cycle), the 3 actual sales months, the 3 sales forecast months (months not counted in the buffer are greyed), stock (avg sales, buffer, available, and the target or order-up-to), the order for each of the 12 months in the chosen mode (in the order plan, each order with its date, such as "7 Dec", and a Months | Weeks switch for one column per Monday-to-Sunday week, where each week also shows the stock in transit arriving in it, such as "+1,200 arriving"; "·" marks a month without an order), the 12-month total and the status (with a red **Runs out before SIT** chip on a SKU whose stock runs out before its stock in transit arrives). Principal, SAP code and description stay on the left while the table scrolls sideways. Click a SKU to see its six demand values, its stock (available = PG sellable + PDG sellable + SIT, with non-sellable PG / PDG shown for information), its stock in transit by arrival date, and the arithmetic behind its order. The principal summary is reached from this page.
3. **Principal summary**: the same switch; per principal, the holding, MOQ, lead time and order cycle the plan used, SKU counts, this month's total order cartons in the chosen mode and blocked / no-demand SKUs. Expand a principal for the list of SKUs to put on this month's purchase order. Below it, each principal's order total for each of the 12 months.
4. **Principal settings**: Holding (days), MOQ (cartons), Lead time (days) and Order cycle (weeks) per principal, plus the change log (the newest 200 entries, newest first, one line per changed setting). Saving recalculates the latest run.
5. **History**: reopen a past run exactly as it was calculated. Each run lists its file names (runs saved before the stock uploads show "—" for the two stock files, and runs saved before the Stock in Transit file show "—" for it).
6. **Export**: Excel download with seven sheets: SKU Plan (the order demand forecast's this-month figures, with PG Sellable, PDG Sellable, PG Non-Sellable and PDG Non-Sellable columns next to Available), 12-Month Plan and Order Plan (the plan page's columns, one sheet per mode), Order Dates (one row per planned order above 0: principal, SAP code, description, order date, quantity and MOQ applied), Principal Summary (both modes' this-month totals and monthly totals), Settings Used and Warnings. Every sheet with principal settings has an "Order Cycle (weeks)" column.

## The five uploads

Each cycle needs five files. All five are required, because a missing stock report or stock in transit file would make a whole group of SKUs look empty and over-order. In the API they are the multipart fields `data_file`, `sales_file`, `pg_file`, `pdg_file` and `sit_file`.

### Sales Forecast file

Only the `Data` sheet is read; all other sheets are ignored. Layout: row 1 empty, row 2 column totals (ignored), row 3 headers, one SKU per row from row 4. The tool matches headers tolerantly (extra spaces are fine) and finds the forecast and month-to-date columns by pattern, so next month's file works unchanged.

Columns it uses:

| Header | Meaning |
|---|---|
| `SAP Code` | SKU id (read as text, unique) |
| `By Principal` | Principal |
| `Description` | SKU name |
| `Packing Size` (or `UOM`) | Pieces per carton; used to convert the Actual Sales file from pieces to cartons. Newer files call it `UOM`; either header works |
| `Shelf Life month` | Required column, but not used in the calculation |
| `Oct'26  MTD Sale (1-11 Oct)` | Sets the MTD month and the stock date (MTD end). The default plan date is the day after, and the plan date can be at most the end of that month. The MTD quantity itself is not used |
| `2026 Oct IMS` ... `2027 Sep IMS` | Monthly forecast in cartons, consecutive months starting no later than the MTD month (month names may be full, 3 or 4 letters, e.g. `Sept`). The MTD month and the next 2 are used |
| `Oct'26` ... under a `YGN IMS` / `MDY IMS` label | **Forecast by region, required.** A label row above the headers says `YGN IMS` over the first Yangon month column and `MDY IMS` over the first Mandalay one (as in the planning workbook's "SIT by weekly" sheet); each month column (`Oct'26`, `Sept'27`, …) belongs to the nearest label to its left. Columns under any other label (`Total IMS`) and the `… IMS Total` columns are ignored. Each region follows the same month rules as the combined forecast. With both region groups, the combined `2026 Oct IMS` columns are optional; when present they are only a check (a warning per SKU when Yangon + Mandalay differs by more than 0.5 carton in a forecast month used). A file with no region groups is rejected ("the Data sheet has no Yangon and Mandalay forecast columns…"), and so is one with only one region |

**Stock and SIT columns are no longer needed.** `Sellable (PG)`, `Sellable (PDG)`, `Total Sellable (Ctns)`, `Non-Sellable (PG)`, `Non-Sellable (PDG)`, `Total Non-Sellable (Ctns)` and `SIT Ctns (pending order)` are not required and are never read: stock comes from the two stock reports and stock in transit from the Stock in Transit file. If any of them is still in the sheet, one warning is shown ("Stock and SIT columns in the Data sheet are ignored; stock comes from the PDG Stock List and PG Expiry Check files, and stock in transit from the Stock in Transit file.") so you know you can remove them. The Data sheet stays the master SKU list: only its SKUs are planned.

**MOQ and Lead Time are principal settings now.** The `MOQ` and `Lead Time` columns are not required and are never read. If either is still in the sheet, one warning is shown ("MOQ and Lead Time columns in the Data sheet are ignored; they come from Principal settings.").

A missing `Data` sheet or required column, forecast months with a gap, a forecast that starts after the MTD month, or no forecast column at all for the 3 months used (the MTD month and the next 2) rejects the file with a message. If only some of those 3 months have no column, the file is accepted with a warning per missing month ("No forecast column for Nov 2026 — counted as missing"). Per-row problems (non-numeric values, negative forecast) and unrecognised `IMS` headers are kept and shown as warnings; nothing is cleaned silently. Shelf life and the month-to-date quantity are not used in the calculation, so their odd values (zero, negative or blank) are not warned about, and saved runs no longer show the warnings they stored for them.

### Actual Sales file

This is admin's system export of past sales.

- A sheet whose header row (within the first 10 rows) contains `itemCode`, `Year`, `Month` and `Qty`. The sheet is found by its headers, not its name. Other columns and other sheets are ignored.
- One row per branch, item and month. `Month` is a month name (`Jul`), a number 1-12, or an Excel date (its own month and year are used), and `Year` is a number (`2026`). A row whose year or month cannot be read is skipped with a warning; if that leaves none of the 3 actual months, the rejection message says how many rows were unreadable.
- `BranchName` sets the region of each row: **Mandalay, Taunggyi, Naypyitaw (also "Nay Pyi Taw") and SubDistributor-Upper are Mandalay; every other branch is Yangon** (case and spaces don't matter). Without a `BranchName` column all sales count as Yangon, with a warning.
- `Qty` is in **pieces**. The tool sums `Qty` over all rows for an item and month, then divides by the item's `Packing Size` in the Sales Forecast file to get cartons (for example 2,113 pieces / 40 = 52.83 cartons).
- It must cover the 3 months before the MTD month (Jul, Aug, Sep 2026 for an October MTD). The file is rejected if it has none of them. If only one or two are missing, the run continues and the missing months count as missing demand, with a warning.

Also warned about, and the run continues: extra months in the export (ignored), items not in the Sales Forecast file (ignored), items with sales but no usable Packing Size (their actuals count as missing), and non-numeric `Qty` (row skipped).

### PG Expiry Check

The batch-level stock report for the PG warehouses.

- The sheet is found by its headers, not its name: the first sheet whose header row (within the first 10 rows) contains `Item Code`, `Location` and `Ctn`. An optional totals row above the headers is fine.
- One row per item, batch, warehouse and bin.
- Columns read: `Item Code` (matched to the Sales Forecast file's `SAP Code`; text or number), `Ctn` (cartons) and `Location`. `expired Date` and `Day Left` are read only to work out the report's as-of date (see below).
- **`BranchName` sets the region** with the same rule as the Actual Sales file (Mandalay, Taunggyi, Naypyitaw → Mandalay; every other branch → Yangon). Without it all PG stock counts as Yangon, with a warning.
- **`Location` alone decides sellable:** `Sellable` counts as sellable, `Non-Sellable` as non-sellable. The `WH Code info` sheet and its `SellableFlag` are **not** used (they disagree with `Location` for some transit warehouses, and the Data sheet has always followed `Location`).
- **As-of date:** PG has no printed date, so on every row that has both `expired Date` and `Day Left`, `expired Date - Day Left` is the date the report was run. The most common such date is used. If no row has both, there is no date check.

### PDG Stock List

The system stock report for the PDG warehouses.

- The sheet is found by its headers: the first sheet whose header row (within the first 10 rows) contains `StockCode`, `Location`, `Bin_Qty`, `U_Ratio` and `Sell or Non`. Report-parameter rows above the headers (`Printed_Date` and so on) are fine.
- One row per stock code, location, bin and batch.
- Columns read: `StockCode` (matched to `SAP Code`; text or number), `Bin_Qty` (pieces), `U_Ratio` (pieces per carton) and `Sell or Non`. `Location` must be present (it is needed to find the sheet) but is not otherwise used.
- **Cartons per row = `Bin_Qty` / `U_Ratio`.** A `cs` column, if the file has one, is not needed.
- **`WH B` sets the region:** `Mandalay` is Mandalay, anything else Yangon. Without it all PDG stock counts as Yangon, with a warning.
- **`Sell or Non` decides sellable:** blank means sellable, `Non` means non-sellable.
- **Printed date:** the value directly under the `Printed_Date` label in the parameter rows. It is optional: with no `Printed_Date`, there is no date check.

### Stock in Transit file

Stock in transit (SIT) by arrival week, for example the planning workbook's "SIT by weekly" sheet.

- The sheet is found by its headers, not its name: the first sheet whose header row (within the first 10 rows) has a `SAP Code` cell and at least one arrival column. A group row above the headers (YGN / MDY) is fine, so you can upload the whole planning workbook or just that sheet.
- **Arrival columns** are headed `<month> W<n> Arrival`, for example `Oct W3 Arrival` (month names may be short or long, such as `Sept`; case and extra spaces don't matter; n is 1 to 5). Every other column is ignored, including `Total SIT` and the IMS forecast columns. Hidden columns are read like any other.
- **Yangon and Mandalay stay apart:** each arrival column belongs to the region of the nearest `YGN` / `MDY` label to its left in the rows above the headers (no label means Yangon). Repeated rows for one SAP code are added. The SKU's SIT is the sum of both regions.
- **Week dates:** weeks run Monday to Sunday and **W1 is the week that holds the 1st** of the month, so Oct W3 2026 is 12–18 Oct and Oct W5 is 26 Oct – 1 Nov, which is also Nov W1 (the last week of a month and W1 of the next are the same week unless the 1st is a Monday). A delivery lands on the **Monday** of its week, or on the plan date if that Monday is earlier. The year is the one that puts the month nearest the Sales Forecast file's MTD month (a December plan reads "Jan W1" as next January).
- **Values:** a blank or 0 cell is no arrival; fractions are kept; a negative or non-numeric cell is skipped with a warning naming the SAP code and column.
- **SIT per SKU** = the total of its arrivals. A Sales Forecast SKU missing from the file has SIT 0 (one warning counts them); codes in the file but not in the Sales Forecast file are ignored (one warning counts them).
- The file is rejected ("Stock in Transit file: No sheet has a SAP Code column and '<Month> W<n> Arrival' columns (looked in the first 10 rows of each sheet).") if no sheet has those headers, or if it is not a readable `.xlsx`.

### How stock is totalled

For each SKU in the Sales Forecast file:

- **PG sellable / non-sellable** = the sum of `Ctn` over the PG rows for that code, split by `Location`.
- **PDG sellable / non-sellable** = the sum of `Bin_Qty / U_Ratio` over the PDG rows for that code, split by `Sell or Non`.
- **Total Sellable** = PG sellable + PDG sellable, and Available = Total Sellable + SIT, as before. Non-sellable stock is shown for information only.
- A SKU in neither file has 0 stock, with no warning. A code in both files simply adds up.
- All sellable stock counts, however close to expiry (see the limitations).

### Stock file checks

A stock file is rejected (error shown under "PG Expiry Check: " or "PDG Stock List: ") if it is not a readable `.xlsx`, if no sheet has the required headers, or if the sheet has no data rows under the header. Otherwise these are warned about and the run continues:

- **Unknown flag value**, one warning per distinct value: "PG Expiry Check: 3 rows have Location 'Quarantine' (not Sellable or Non-Sellable); counted as non-sellable". For PDG it is "PDG Stock List: N rows have Sell or Non 'X' (not blank or Non); counted as non-sellable". Unknown stock counts as non-sellable, so it never reduces an order.
- **Unreadable quantity**, one warning per file: "PG Expiry Check: N rows have no readable Ctn; skipped" (for PDG: "no readable Bin_Qty or U_Ratio", which also covers a missing, 0 or negative `U_Ratio`). A SKU in the Sales Forecast file that lost a row also gets its own warning.
- **Codes not in the Sales Forecast file**, one warning per file: "PDG Stock List: 8 stock codes are not in the Data sheet; ignored".
- **No matching SKUs**: "PG Expiry Check has no stock for any SKU in the Data sheet — check that it is the right report". A warning, not a rejection, because a principal group can legitimately have no stock.
- **Hidden rows**: "PG Expiry Check: N rows are hidden by a filter; they are still counted".
- **Old stock date**: if the PDG printed date or the PG as-of date is more than 3 days from the plan date: "PDG Stock List was printed on 2 Oct 2026, 10 days before the plan date" (PG: "PG Expiry Check is as of ..."). It is checked again when the run is created, using the plan date you chose.
- **Negative total**: "negative stock — check the stock report" on a SKU whose total sellable stock is below 0.

## How the order is calculated

The months: actual months are the 3 calendar months before the MTD month; forecast months are the MTD month and the next 2. Example: a Sales Forecast file dated 12 Oct with an MTD of 1-11 Oct gives actuals Jul, Aug, Sep 2026 and forecasts Oct, Nov, Dec 2026.

For each SKU:

1. **Avg sales** (average monthly demand, cartons) = the mean of the valid values among the 3 actual and 3 forecast months. A value is valid if it is greater than 0; zero, negative (net returns), blank and missing values are skipped.
2. **Buffer** (cartons) = avg sales / 30 x holding (days). This is the target stock the order demand forecast tops up to.
3. **Available stock** = Total Sellable (PG sellable + PDG sellable) + SIT.
4. **Required** = buffer - available, never below 0, rounded up to whole cartons.
5. **MOQ check**: if 0 < required < the principal's MOQ, the order is the MOQ (tagged "MOQ"). The MOQ applies to each SKU of the principal on its own, not to the principal's total. If required is 0, the order is 0 and is not raised to MOQ. MOQ 0 means no minimum.
6. **Stock cover** (months) = available / avg sales. Not shown if there is no average or if available stock is negative.
7. **Next calculation date** = plan date + the principal's lead time (days). Not shown ("lead time not set") if the principal has no lead time; this does not block the order.

Worked example (principal settings: holding 90 days, MOQ 150, lead time 61 days; available stock 260, plan date 14 Oct 2026):

| Step | Working | Result |
|---|---|---|
| Valid values | 100, 120, 110, 130, 140, 120 (6 of 6) | |
| Avg sales | (100 + 120 + 110 + 130 + 140 + 120) / 6 | 120 a month |
| Buffer (target) | 120 / 30 x 90 days | 360 |
| Available | PG sellable + PDG sellable + SIT | 260 |
| Required | 360 - 260 | 100 |
| Order | 100 is below the MOQ of 150, so the MOQ applies | 150 |
| Stock cover | 260 / 120 | 2.2 months |
| Next calculation date | 14 Oct 2026 + 61 days lead time (about 2 months) | 14 Dec 2026 |

The SKU detail page writes out this arithmetic for every SKU, with the six values and which were valid.

## 12-month plan

Besides this cycle's order, each plan shows how much to order in each of the next 12 months: the MTD month and the 11 after it (Oct 2026 – Sep 2027 for the current file).

- **Demand each month** is the SKU's avg sales, the same every month. For now the 12-month plan uses the past 3 months' sales and the next 3 months' forecast only, so forecast months 4–12 in the Data sheet are not used. When forecasts come from a database later, only this one step changes.
- **Month 1** is this cycle's order. Opening stock is available (sellable + SIT), and closing = opening + order − demand.
- **Each later month** opens with last month's closing stock. Its order = buffer − opening, never below 0, rounded up and raised to the principal's MOQ. Its closing = opening + order − demand.
- **Orders arrive within the month they are placed**; lead time does not move them.
- **Holding not set:** the principal's SKUs show "—" for every month, and their stock runs down. **No demand data:** every month is 0.

With the worked example above (avg sales 120, holding 90 days so buffer 360, available 260, MOQ 150) the 12 orders are 150, 150, 150, 150, 0, 150, 150, 150, 150, 0, 150, 150. The MOQ overshoot builds stock until a month needs nothing. With MOQ 0 they are 100, then 120 every month.

**Where it shows:**
- the Order plan table (one order column per month plus a total, next to the settings, sales and stock that produce them);
- a 12-month table (opening, demand, order, closing) in the SKU detail;
- a **12-month order demand forecast** table on the Principal summary page;
- a **12-Month Plan** sheet in the Excel export, laid out like the plan page (MOQ, holding, lead time, the 6 sales months, avg sales, buffer, available, target, one "<month> Order Demand Forecast" column per month, 12-Month Total, status), with the monthly totals also on the Principal Summary sheet.

Plans saved before the 12-month plan existed show "Recalculate to see the 12-month plan" until they are recalculated. No database upgrade is needed.

## Order plan and order cycle

The 12-month plan above is the **order demand forecast**: it tops stock up every month. The **order plan** follows each principal's **order cycle** instead, set in **weeks**: with cycle 4 the principal is ordered from once every four weeks, and each order covers the weeks until the next one. The forecast is unchanged; the switch on the plan page and the Principal summary chooses which one the order figures come from.

- **Order dates:** the plan date, then every *cycle* weeks after it, up to the last day of the 12th plan month. For now every principal's cycle starts on the plan date; later, with order history from the database, it can start per principal.
- **Stock day by day:** each day uses its month's demand ÷ the number of days in that month, so every full month still uses exactly its avg sales. The first month only counts the days from the plan date, because the available stock is as of the plan date. (If the MTD ends on a month's last day, the plan date is the 1st of the next month: the first plan month then shows no demand and no order.)
- **Each order** tops stock up to the **order-up-to level = buffer + avg sales × (cycle weeks × 12 ÷ 52 − 1)**, minus the stock on that day, rounded up to whole cartons and raised to the MOQ as usual. Just before the next order arrives, stock is down to about the buffer less one month's sales, as it is when ordering monthly (a 4-week cycle behaves almost like ordering every month).
- **Stock in transit by arrival day:** stock on hand starts at sellable stock on the plan date, and each delivery in the Stock in Transit file joins it on its arrival day (the Monday of its week). Each order still counts stock on hand **plus the SIT still on its way**, so SIT is never ordered twice and order quantities are the same whenever it arrives; only the stock on hand changes. The SKU detail's order-plan table has an **Arrivals** column (closing = opening + arrivals + orders − demand), and the Weeks view shows each week's arrivals.
- **Runs out before SIT arrives:** a SKU is flagged when its sellable stock plus the SIT landed so far, less each day's demand and with **no new orders**, falls below 0 before its last delivery arrives (an order placed now can't arrive before SIT already on its way, so the flag means "chase this delivery"). The flag shows as a red chip on the plan row, in the SKU detail ("Runs out about 22 Oct, before its stock in transit arrives on 2 Nov"), in the warnings panel and on the export's Warnings sheet. SKUs with no demand data or no SIT are never flagged.
- **Floor:** the order-up-to level is never below one cycle's sales (avg sales × cycle weeks × 12 ÷ 52). This only matters for a holding under 30 days: each order then lasts until the next one, and stock gets down to about 0 just before it.
- **Months and weeks:** the plan keeps its 12 month columns. In Order plan mode a month cell lists each order placed in it with its date, for example "2,250 / 7 Dec"; a month with two orders shows both. A month without an order shows "·" on screen and is blank in Excel, where the Order Plan sheet keeps the month totals. A **Months | Weeks** switch next to the mode switch (Order plan mode only) shows one column per Monday-to-Sunday week instead, headed by the week's Monday (for example "7 Dec") and placed under the month that Monday falls in; the first plan month also starts with the week holding its 1st. Every column is 7 days, so orders one cycle apart are always the same number of columns apart (a 4-week cycle: every 4th column). Hovering a week heading shows its days, for example "30 Nov – 6 Dec 2026". The page starts in Months view. Order sizes vary by a few cartons from one order to the next because months have different numbers of days.
- **Holding not set:** "—" every month. **No demand data:** 0 every order.
- **The stock column** next to Available shows the level the orders top up to: **Target** in Order demand forecast mode, **Order-up-to** in Order plan mode. The export's 12-Month Plan and Order Plan sheets do the same.
- **This month's order, status and counts** follow the switch: in Order plan mode they are the order placed on the plan date, so a SKU can be "No order needed" in the forecast (stock above the target) but "To order" in the order plan (stock below the order-up-to level). The Principal summary's purchase-order lines and totals and the SKU detail's arithmetic ("Order-up-to = …") follow it too. The SKU detail also lists every planned order with its date under **Orders**, and the export has an **Order Dates** sheet with one row per planned order.

Example (avg sales 120, holding 90 days so buffer 360, available 260 all sellable with no SIT, MOQ 0, cycle 4 weeks, plan date 10 Oct 2026, so the order-up-to level is 360 + 120 × (48 ÷ 52 − 1) ≈ 350.77):

| Month | Opening | Demand | Orders | Closing |
|---|---|---|---|---|
| Oct 2026 | 260.00 | 85.16 (22 of 31 days) | 10 Oct: 91 | 265.84 |
| Nov 2026 | 265.84 | 120.00 | 7 Nov: 109 | 254.84 |
| Dec 2026 | 254.84 | 120.00 | 5 Dec: 112 | 246.84 |
| Jan 2027 | 246.84 | 120.00 | 2 Jan: 108, 30 Jan: 109 | 343.84 |
| Feb 2027 | 343.84 | 120.00 | 27 Feb: 119 | 342.84 |

…and one order a month after that (27 Mar 109, 24 Apr 111, 22 May 110, 19 Jun 110, 17 Jul 110, 14 Aug 109, 11 Sep 109): 13 orders, 1,416 in total.

Plans saved before the order cycle existed, or while it was set in months, show "Recalculate to see the order plan" in Order plan mode; the order demand forecast still shows. Recalculating gives the weekly order plan with the current settings.

Plans saved before the Stock in Transit file show their order plan as stored, with Arrivals "—" (their month 1 opening includes all SIT). Recalculating one treats all its SIT as arriving on the plan date: orders and closings stay the same, and month 1 opens at sellable stock with the SIT under Arrivals. They are never flagged.

## Commits

A **commit** is stock already agreed with a principal that isn't in the Stock in Transit file yet. Enter commits on the New plan page, in the **Commit** section under the warnings, before you click Calculate:

- **SAP Code:** type a code or part of a description and pick the SKU from the list (only SKUs in the Sales Forecast file).
- **Cartons:** a number above 0.
- **Estimated arrival week:** a Monday-to-Sunday week from the plan date's week to the end of the last plan month, labelled like the Stock in Transit file ("Oct W4 (19 Oct)"; W1 is the week holding the 1st, and a sixth week reads as the next month's W1).
- **Region:** Yangon or Mandalay.

**Add commit** adds a line and **Remove** deletes one; the same SKU can have several. Calculate stays disabled until every line is complete.

Each commit is treated **exactly like stock in transit**: it lands on the Monday of its week in its region, it is part of the SKU's SIT (and available stock in Order demand forecast mode), every order in the Order plan counts it as stock on its way so it isn't ordered again, and the run-out flag counts it. On the plan page, a **Commits** panel under the warnings lists every commit of the plan (click one to open that SKU's details for its region), and rows with a commit get a grey **Commit** tag next to their status (hover for the cartons). The SKU detail lists it under Stock in transit with a **Commit** tag, the Weeks view shows it on its own line, "+N committed" (the file's stock in transit stays "+N arriving"), and the export has a **Commits** sheet (Principal, SAP Code, Description, Region, Cartons, Arrival Week); the SKU Plan sheet shows **SIT** (the Stock in Transit file) and **Commit** in separate columns. Commits are saved with the plan, so Recalculate keeps them. They are entered fresh for each new plan (not carried over).

**Changing commits on a calculated plan:** the plan page's **Commits** panel has **Edit commits** (or **Add commits** when there are none). It opens the same editor: change any line, **Add commit**, or **Remove** one, then **Save commits**. Saving recalculates that plan **in place** (same plan number, nothing new in History) with the **current principal settings**, like Recalculate; **Cancel** drops the changes. The same checks apply as on New plan (the SAP code must be in the plan, cartons above 0, a week from the plan week to the end of the plan). Plans saved before the Stock in Transit file can take commits too; their old SIT still counts from the plan date.

## Yangon and Mandalay

Each SKU is planned **separately for Yangon and Mandalay**: the order demand forecast, the order plan, the order quantities, the run-out flag, the zero-forecast flag and the status are all per region.

- **Inputs per region:** actual sales from the Actual Sales file's `BranchName`, the forecast from the Data sheet's `YGN IMS` / `MDY IMS` columns, sellable and non-sellable stock from PG `BranchName` and PDG `WH B`, and stock in transit from the Stock in Transit file's YGN / MDY columns. Region rule for branches: Mandalay, Taunggyi, Naypyitaw and SubDistributor-Upper are Mandalay; every other branch is Yangon.
- **Settings are per principal and the same for both regions** (holding days, MOQ, lead time, order cycle). **The MOQ applies to each region's order on its own.**
- **One plan row per SKU per region.** A SKU gets a Mandalay row only when Mandalay has something: a sales value above 0 (actual or forecast), stock or SIT; the same for Yangon. A SKU with nothing in either region keeps a Yangon row, so every SKU is listed.
- **Screens:** the plan page has a **Region** column (after Description) and a **Region** filter; its count cards and statuses count rows. The SKU detail shows the region under its title. The Principal summary's totals cover both regions, "SKUs" counts each SKU once, and the purchase-order lines show the region. The export has a **Region** column after SAP Code in SKU Plan, 12-Month Plan, Order Plan and Order Dates, and the run-out warning starts with the region.
- **Saved runs** made before the split have one combined row per SKU (Region "—") and stay combined when recalculated. No database upgrade is needed.

## Statuses and flags

| Status | Meaning |
|---|---|
| **To order** | The principal has a holding and the order quantity is above 0. |
| **No order needed** | The principal has a holding and available stock already covers the target, so the order is 0. |
| **Holding not set** | The principal has no holding yet, so its SKUs are blocked: buffer, target, required and order are shown as "—". Avg sales, available and cover are still shown. The run is not rejected; a banner lists the blocked principals with a link to Principal settings. |
| **No demand data** | None of the 6 values is valid, so there is no average and the buffer is 0. Target and order are 0 whatever the stock (even if stock is negative), so a no-demand SKU is never ordered, and cover is "—". |

**Zero forecast** is a flag, not a status. It is raised when all 3 forecast months are 0 or invalid but at least one actual month is valid. The order is still calculated from the actuals, and the flag tells the planner to review the SKU before ordering. It shows in the table, on a count card, and as a filter option, whether or not the order is above 0.

## Principal settings

- One **Holding (days)** per principal (`By Principal`), on the Principal settings page: a whole number of days from 15 to 720. Buffer = avg sales / 30 x holding days, so 60 days keeps two months of average sales.
- A blank value means not set. There is no default: a principal with no holding is blocked (status Holding not set) until you enter one.
- **MOQ (cartons)** per principal: a whole number, 0 or more (default 0 = no minimum). Any SKU of the principal whose order is above 0 but below the MOQ is raised to the MOQ; it is not a minimum on the principal's total order. "8,000" with a thousands separator is accepted.
- **Lead time (days)** per principal: a whole number from 0 to 365, or blank. It only sets the next calculation date; a blank lead time shows "Lead time not set — no next calculation date" and does not block anything.
- **Order cycle (weeks)** per principal: a whole number from 1 to 52 (default 4 = order every four weeks). It cannot be blank. Cycles set in months before the move to weeks were not converted, so re-enter each principal's cycle. See [Order plan and order cycle](#order-plan-and-order-cycle).
- Every change is recorded in the change log, one line per changed setting: principal, setting, old value, new value and time (newest first). There is no user name, because the tool is single-user.
- Saving sends only the changed rows and recalculates the latest run. The Order plan page also has a Recalculate button. Recalculating any plan, including an older one, uses the current settings.

## Database

**PostgreSQL.** It holds principal settings, the change log and all runs, in three tables created on first start (`supplier_settings`, `settings_log`, `runs`). The backend reads its settings from the environment or from `backend/.env` (git-ignored):

```
DATABASE_URL=postgresql://127.0.0.1:5432/demandforecasting
DATABASE_USER=df_app
DATABASE_PASSWORD=<the login's password>
```

`DATABASE_USER` / `DATABASE_PASSWORD` are used when the URL has no user of its own, so the password needs no URL-encoding. The login should own the database (it creates the tables). Without a `DATABASE_URL`, the backend uses `postgresql://127.0.0.1:5432/demandforecasting`.

The tables mirror the SQLite layout the tool used up to version 8, in the same storage types: plans stay JSON text and dates ISO text, and the unused columns `holding_months` and `order_cycle_months` are kept so old change-log lines still make sense.

**Moving from the old SQLite file.** Up to version 8 the tool kept everything in `backend/data/orderplan.db`. To move it into PostgreSQL once, stop the backend, set the settings above, and from `backend/` run:

```
.venv/Scripts/python -m app.copy_from_sqlite data/orderplan.db      # Windows (Linux: .venv/bin/python)
```

It refuses unless the file is at version 8 (an older file: open it once with the last SQLite version of the tool, which upgrades it) and the PostgreSQL tables are empty, so nothing is overwritten. It copies the three tables in one transaction, keeping their IDs, moves PostgreSQL's ID counters past them so new rows don't collide, checks the row counts on both sides, and leaves the SQLite file unchanged. Keep the file as a backup.

The `backend-test` entry in `.claude/launch.json` (port 8001, with `frontend-test` on port 5174 pointing at it) uses its own scratch database, `orderplan_scratch`, for trying things without touching real runs; create it once on your local PostgreSQL.

## Tests

The backend tests need a PostgreSQL **test database**; each test works in its own throwaway schema there, dropped afterwards, so they never touch real data. Point them at it with `TEST_DATABASE_URL` (plus `TEST_DATABASE_USER` / `TEST_DATABASE_PASSWORD` when the URL has no user), either as environment variables or in `backend/.env.pgtest` (git-ignored). Tests that need no database run without it.

PowerShell or Git Bash, from the project folder:

```
cd backend
.venv/Scripts/python -m pytest
cd ..
npm --prefix frontend test
```

`npm --prefix frontend run build` type-checks and builds the frontend, and `npm --prefix frontend run lint` runs the linter.

## Known limitations

- **No order tracking.** The tool does not record which suggested orders were actually placed. Orders placed since the last upload only count once they appear in the Stock in Transit file; until then a mid-month re-run will suggest them again.
- **Arrival weeks, not days.** Each SIT delivery lands on the Monday of its week; the exact day within the week isn't known. New orders still arrive on their order date (lead time doesn't delay them).
- **Near-expiry stock still counts as available.** All sellable stock from both reports is counted, however close it is to expiry. The reports carry batch expiry data, so this can be refined later; the cut-off is not decided.
- **Excel is a stand-in.** The stock reports and the Actual Sales file are read from Excel files for now; the stock parsers produce plain stock lines that are totalled separately from the calculation, so a database source can replace them later.
- **Lead time does not change the order quantity.** It only sets the next calculation date.
- **No minimum number of valid values.** An average built from few values is shown, not hidden. The "Valid" column on the Order plan page (shown as n/6) shows how thin it is.
- **No transfers between regions.** Each region is planned on its own stock; surplus stock in one region does not cover the other.
- **The MTD sale is not split by region.** It is not used in the calculation.
- **Cartons only.** There are no prices or money values; the Actual Sales file's `Amount` column is ignored.
- The forecast is an input; the tool does not generate or adjust it.
- Shelf life is not used (no shelf-life capping), and MOQ is treated as a minimum, not a multiple.

## Removed since v1

The v1 day-by-day simulation is gone: reorder and target days, the list of future orders, the weekly projection and stock chart, the "orders due within N weeks" window, the v1 flags (Order now, Stock-out risk, Excess and so on) and shelf-life capping. The charting library (`recharts`) is no longer a dependency.
