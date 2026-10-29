# Order Plan Tool

A local tool that turns the planner's Excel forecast, the sales export and two stock reports into a per-SKU order plan. Each cycle you upload four files, and you set one holding (in months of stock) per principal. For every SKU the tool works out the average monthly demand, the stock you should hold, and the cartons to order to get there, with every number shown. It rolls the plan up by principal, exports it to Excel, and keeps a history of past runs.

It runs on your own Windows computer: a Python (FastAPI) backend with a SQLite database, and a React web page in the browser.

## Requirements

- Python 3.12
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

1. **New plan**: choose the four files (the Data file, the sales export, the PG Expiry Check and the PDG Stock List), check the detected months, the stock facts (SKUs with stock, sellable cartons from PG and from PDG, the PDG printed date and the PG as-of date), the plan date and any warnings, then click Calculate. Calculate is enabled once all four files inspect OK.
2. **Order plan**: count cards (To order, Holding not set, No demand data, Zero forecast), a banner listing blocked principals, and filters for principal, status, the Zero forecast flag and search. A warnings panel above the table shows file-level warnings (labelled Data file, Sales export or Stock files; the stock report's name is in the message text) in full and counts the per-SKU warnings in a collapsible list. The plan header lists the four file names. The table has one row per SKU, in column groups: principal settings (MOQ, holding, lead time), the 3 actual sales months, the 3 forecast months (months not counted in the buffer are greyed), stock (buffer, available, target), the order for each of the 12 months, the 12-month total and the status. Principal, SAP code and description stay on the left while the table scrolls sideways. Click a SKU to see its six demand values, its stock (available = PG sellable + PDG sellable + SIT, with non-sellable PG / PDG shown for information) and the arithmetic behind its order. The principal summary is reached from this page.
3. **Principal summary**: per principal, the holding, MOQ and lead time the plan used, SKU counts, total order cartons and blocked / no-demand SKUs. Expand a principal for the list of SKUs to put on one purchase order.
4. **Principal settings**: Holding (months), MOQ (cartons) and Lead time (days) per principal, plus the change log (the newest 200 entries, newest first, one line per changed setting). Saving recalculates the latest run.
5. **History**: reopen a past run exactly as it was calculated. Each run lists its file names (runs saved before the stock uploads show "—" for the two stock files).
6. **Export**: Excel download with five sheets: SKU Plan (with PG Sellable, PDG Sellable, PG Non-Sellable and PDG Non-Sellable columns next to Available), 12-Month Plan (the same columns as the plan page), Principal Summary, Settings Used and Warnings.

## The four uploads

Each cycle needs four files. All four are required, because a missing stock report would make a whole group of SKUs look empty and over-order. In the API they are the multipart fields `data_file`, `sales_file`, `pg_file` and `pdg_file`.

### Data file

Only the `Data` sheet is read; all other sheets are ignored. Layout: row 1 empty, row 2 column totals (ignored), row 3 headers, one SKU per row from row 4. The tool matches headers tolerantly (extra spaces are fine) and finds the forecast and month-to-date columns by pattern, so next month's file works unchanged.

Columns it uses:

| Header | Meaning |
|---|---|
| `SAP Code` | SKU id (read as text, unique) |
| `By Principal` | Principal |
| `Description` | SKU name |
| `Packing Size` | Pieces per carton; used to convert the sales export from pieces to cartons |
| `Shelf Life month` | Required column, but not used in the calculation |
| `SIT Ctns (pending order)` | Stock in transit / already ordered. Neither stock report has it, so it still comes from the Data sheet |
| `Oct'26  MTD Sale (1-11 Oct)` | Sets the MTD month and the stock date (MTD end). The default plan date is the day after, and the plan date can be at most the end of that month. The MTD quantity itself is not used |
| `2026 Oct IMS` ... `2027 Sep IMS` | Monthly forecast in cartons, consecutive months starting no later than the MTD month (month names may be full, 3 or 4 letters, e.g. `Sept`). The MTD month and the next 2 are used |

**Stock columns are no longer needed.** `Sellable (PG)`, `Sellable (PDG)`, `Total Sellable (Ctns)`, `Non-Sellable (PG)`, `Non-Sellable (PDG)` and `Total Non-Sellable (Ctns)` are not required and are never read. If any of them is still in the sheet, one warning is shown ("Stock columns in the Data sheet are ignored; stock comes from the PDG Stock List and PG Expiry Check files.") so you know you can remove them. The Data sheet stays the master SKU list: only its SKUs are planned.

**MOQ and Lead Time are principal settings now.** The `MOQ` and `Lead Time` columns are not required and are never read. If either is still in the sheet, one warning is shown ("MOQ and Lead Time columns in the Data sheet are ignored; they come from Principal settings.").

A missing `Data` sheet or required column, forecast months with a gap, a forecast that starts after the MTD month, or no forecast column at all for the 3 months used (the MTD month and the next 2) rejects the file with a message. If only some of those 3 months have no column, the file is accepted with a warning per missing month ("No forecast column for Nov 2026 — counted as missing"). Per-row problems (non-numeric values, negative forecast, negative SIT, and the shelf life and month-to-date oddities that the calculation does not use) and unrecognised `IMS` headers are kept and shown as warnings; nothing is cleaned silently.

### Sales export

This is admin's system export of past sales.

- A sheet whose header row (within the first 10 rows) contains `itemCode`, `Year`, `Month` and `Qty`. The sheet is found by its headers, not its name. Other columns and other sheets are ignored.
- One row per branch, item and month. `Month` is a month name (`Jul`), a number 1-12, or an Excel date (its own month and year are used), and `Year` is a number (`2026`). A row whose year or month cannot be read is skipped with a warning; if that leaves none of the 3 actual months, the rejection message says how many rows were unreadable.
- `Qty` is in **pieces**. The tool sums `Qty` over all rows for an item and month, then divides by the item's `Packing Size` in the Data file to get cartons (for example 2,113 pieces / 40 = 52.83 cartons).
- It must cover the 3 months before the MTD month (Jul, Aug, Sep 2026 for an October MTD). The file is rejected if it has none of them. If only one or two are missing, the run continues and the missing months count as missing demand, with a warning.

Also warned about, and the run continues: extra months in the export (ignored), items not in the Data file (ignored), items with sales but no usable Packing Size (their actuals count as missing), and non-numeric `Qty` (row skipped).

### PG Expiry Check

The batch-level stock report for the PG warehouses.

- The sheet is found by its headers, not its name: the first sheet whose header row (within the first 10 rows) contains `Item Code`, `Location` and `Ctn`. An optional totals row above the headers is fine.
- One row per item, batch, warehouse and bin.
- Columns read: `Item Code` (matched to the Data file's `SAP Code`; text or number), `Ctn` (cartons) and `Location`. `expired Date` and `Day Left` are read only to work out the report's as-of date (see below).
- **`Location` alone decides sellable:** `Sellable` counts as sellable, `Non-Sellable` as non-sellable. The `WH Code info` sheet and its `SellableFlag` are **not** used (they disagree with `Location` for some transit warehouses, and the Data sheet has always followed `Location`).
- **As-of date:** PG has no printed date, so on every row that has both `expired Date` and `Day Left`, `expired Date - Day Left` is the date the report was run. The most common such date is used. If no row has both, there is no date check.

### PDG Stock List

The system stock report for the PDG warehouses.

- The sheet is found by its headers: the first sheet whose header row (within the first 10 rows) contains `StockCode`, `Location`, `Bin_Qty`, `U_Ratio` and `Sell or Non`. Report-parameter rows above the headers (`Printed_Date` and so on) are fine.
- One row per stock code, location, bin and batch.
- Columns read: `StockCode` (matched to `SAP Code`; text or number), `Bin_Qty` (pieces), `U_Ratio` (pieces per carton) and `Sell or Non`. `Location` must be present (it is needed to find the sheet) but is not otherwise used.
- **Cartons per row = `Bin_Qty` / `U_Ratio`.** A `cs` column, if the file has one, is not needed.
- **`Sell or Non` decides sellable:** blank means sellable, `Non` means non-sellable.
- **Printed date:** the value directly under the `Printed_Date` label in the parameter rows. It is optional: with no `Printed_Date`, there is no date check.

### How stock is totalled

For each SKU in the Data file:

- **PG sellable / non-sellable** = the sum of `Ctn` over the PG rows for that code, split by `Location`.
- **PDG sellable / non-sellable** = the sum of `Bin_Qty / U_Ratio` over the PDG rows for that code, split by `Sell or Non`.
- **Total Sellable** = PG sellable + PDG sellable, and Available = Total Sellable + SIT, as before. Non-sellable stock is shown for information only.
- A SKU in neither file has 0 stock, with no warning. A code in both files simply adds up.
- All sellable stock counts, however close to expiry (see the limitations).

### Stock file checks

A stock file is rejected (error shown under "PG Expiry Check: " or "PDG Stock List: ") if it is not a readable `.xlsx`, if no sheet has the required headers, or if the sheet has no data rows under the header. Otherwise these are warned about and the run continues:

- **Unknown flag value**, one warning per distinct value: "PG Expiry Check: 3 rows have Location 'Quarantine' (not Sellable or Non-Sellable); counted as non-sellable". For PDG it is "PDG Stock List: N rows have Sell or Non 'X' (not blank or Non); counted as non-sellable". Unknown stock counts as non-sellable, so it never reduces an order.
- **Unreadable quantity**, one warning per file: "PG Expiry Check: N rows have no readable Ctn; skipped" (for PDG: "no readable Bin_Qty or U_Ratio", which also covers a missing, 0 or negative `U_Ratio`). A SKU in the Data file that lost a row also gets its own warning.
- **Codes not in the Data file**, one warning per file: "PDG Stock List: 8 stock codes are not in the Data sheet; ignored".
- **No matching SKUs**: "PG Expiry Check has no stock for any SKU in the Data sheet — check that it is the right report". A warning, not a rejection, because a principal group can legitimately have no stock.
- **Hidden rows**: "PG Expiry Check: N rows are hidden by a filter; they are still counted".
- **Old stock date**: if the PDG printed date or the PG as-of date is more than 3 days from the plan date: "PDG Stock List was printed on 2 Oct 2026, 10 days before the plan date" (PG: "PG Expiry Check is as of ..."). It is checked again when the run is created, using the plan date you chose.
- **Negative total**: "negative stock — check the stock report" on a SKU whose total sellable stock is below 0.
- **Negative SIT**: "negative SIT — check the Data sheet" on a SKU whose `SIT Ctns (pending order)` in the Data sheet is below 0. SIT is the only stock figure that still comes from the Data sheet.

## How the order is calculated

The months: actual months are the 3 calendar months before the MTD month; forecast months are the MTD month and the next 2. Example: a Data file dated 12 Oct with an MTD of 1-11 Oct gives actuals Jul, Aug, Sep 2026 and forecasts Oct, Nov, Dec 2026.

For each SKU:

1. **Buffer** (average monthly demand, cartons) = the mean of the valid values among the 3 actual and 3 forecast months. A value is valid if it is greater than 0; zero, negative (net returns), blank and missing values are skipped.
2. **Target stock** = buffer x holding (months).
3. **Available stock** = Total Sellable (PG sellable + PDG sellable) + SIT.
4. **Required** = target - available, never below 0, rounded up to whole cartons.
5. **MOQ check**: if 0 < required < the principal's MOQ, the order is the MOQ (tagged "MOQ"). The MOQ applies to each SKU of the principal on its own, not to the principal's total. If required is 0, the order is 0 and is not raised to MOQ. MOQ 0 means no minimum.
6. **Stock cover** (months) = available / buffer. Not shown if there is no buffer or if available stock is negative.
7. **Next calculation date** = plan date + the principal's lead time (days). Not shown ("lead time not set") if the principal has no lead time; this does not block the order.

Worked example (principal settings: holding 3 months, MOQ 150, lead time 61 days; available stock 260, plan date 14 Oct 2026):

| Step | Working | Result |
|---|---|---|
| Valid values | 100, 120, 110, 130, 140, 120 (6 of 6) | |
| Buffer | (100 + 120 + 110 + 130 + 140 + 120) / 6 | 120 |
| Target | 120 x 3 | 360 |
| Available | PG sellable + PDG sellable + SIT | 260 |
| Required | 360 - 260 | 100 |
| Order | 100 is below the MOQ of 150, so the MOQ applies | 150 |
| Stock cover | 260 / 120 | 2.2 months |
| Next calculation date | 14 Oct 2026 + 61 days lead time (about 2 months) | 14 Dec 2026 |

The SKU detail page writes out this arithmetic for every SKU, with the six values and which were valid.

## 12-month plan

Besides this cycle's order, each plan shows how much to order in each of the next 12 months: the MTD month and the 11 after it (Oct 2026 – Sep 2027 for the current file).

- **Demand each month** is the SKU's buffer, the same every month. For now the 12-month plan uses the past 3 months' sales and the next 3 months' forecast only, so forecast months 4–12 in the Data sheet are not used. When forecasts come from a database later, only this one step changes.
- **Month 1** is this cycle's order. Opening stock is available (sellable + SIT), and closing = opening + order − demand.
- **Each later month** opens with last month's closing stock. Its order = (buffer × holding) − opening, never below 0, rounded up and raised to the principal's MOQ. Its closing = opening + order − demand.
- **Orders arrive within the month they are placed**; lead time does not move them.
- **Holding not set:** the principal's SKUs show "—" for every month, and their stock runs down. **No demand data:** every month is 0.

With the worked example above (buffer 120, holding 3, available 260, MOQ 150) the 12 orders are 150, 150, 150, 150, 0, 150, 150, 150, 150, 0, 150, 150. The MOQ overshoot builds stock until a month needs nothing. With MOQ 0 they are 100, then 120 every month.

**Where it shows:**
- the Order plan table (one order column per month plus a total, next to the settings, sales and stock that produce them);
- a 12-month table (opening, demand, order, closing) in the SKU detail;
- a **12-month orders** table on the Principal summary page;
- a **12-Month Plan** sheet in the Excel export, laid out like the plan page (MOQ, holding, lead time, the 6 sales months, buffer, available, target, one "<month> Order" column per month, 12-Month Total, status), with the monthly totals also on the Principal Summary sheet.

Plans saved before the 12-month plan existed show "Recalculate to see the 12-month plan" until they are recalculated. No database upgrade is needed.

## Statuses and flags

| Status | Meaning |
|---|---|
| **To order** | The principal has a holding and the order quantity is above 0. |
| **No order needed** | The principal has a holding and available stock already covers the target, so the order is 0. |
| **Holding not set** | The principal has no holding yet, so its SKUs are blocked: target, required and order are shown as "—". Buffer, available and cover are still shown. The run is not rejected; a banner lists the blocked principals with a link to Principal settings. |
| **No demand data** | None of the 6 values is valid, so there is no buffer. Target and order are 0 whatever the stock (even if stock is negative), so a no-demand SKU is never ordered, and cover is "—". |

**Zero forecast** is a flag, not a status. It is raised when all 3 forecast months are 0 or invalid but at least one actual month is valid. The order is still calculated from the actuals, and the flag tells the planner to review the SKU before ordering. It shows in the table, on a count card, and as a filter option, whether or not the order is above 0.

## Principal settings

- One **Holding (months)** per principal (`By Principal`), on the Principal settings page. The range is 0.5 to 24 months and decimals are allowed (for example 1.5).
- A blank value means not set. There is no default: a principal with no holding is blocked (status Holding not set) until you enter one.
- **MOQ (cartons)** per principal: a whole number, 0 or more (default 0 = no minimum). Any SKU of the principal whose order is above 0 but below the MOQ is raised to the MOQ; it is not a minimum on the principal's total order. "8,000" with a thousands separator is accepted.
- **Lead time (days)** per principal: a whole number from 0 to 365, or blank. It only sets the next calculation date; a blank lead time shows "Lead time not set — no next calculation date" and does not block anything.
- Every change is recorded in the change log, one line per changed setting: principal, setting, old value, new value and time (newest first). There is no user name, because the tool is single-user.
- Saving sends only the changed rows and recalculates the latest run. The Order plan page also has a Recalculate button. Recalculating any plan, including an older one, uses the current settings.

## Database

SQLite file at `backend/data/orderplan.db` (created on first start; not committed to git). It holds principal settings, the change log and all runs. To use a different file, set the `ORDERPLAN_DB` environment variable before starting the backend:

```
$env:ORDERPLAN_DB = "C:\path\to\other.db"      # PowerShell
export ORDERPLAN_DB=C:/path/to/other.db         # Git Bash
```

The `$env:` setting applies only to the current PowerShell window. The `backend` and `frontend` entries in `.claude/launch.json` always use the default database. The `backend-test` entry (port 8001, with `frontend-test` on port 5174 pointing at it) uses its own scratch database, `backend/data/orderplan-test.db` (set through `ORDERPLAN_DB`; the file is created on first use and `backend/data/` is git-ignored), for trying things without touching real runs.

**Upgrading from v1.** If the database file is a v1 one (it has reorder/target days), the tool renames it to `orderplan.v1-backup.db` in the same folder (`orderplan.v1-backup-1.db`, `-2` and so on if that name is taken) and creates a fresh v2 database. Nothing is deleted. v1 runs and settings are not carried over.

**Upgrading from v2 (stock reports).** A v2 database is upgraded in place the first time the new backend starts: three columns (the two stock file names and the stock breakdown) are added to the runs table and the schema version moves to 3. Nothing is recreated or renamed, so your runs and holding settings stay. Older runs open and recalculate as before; they show "—" for the PG / PDG split and for the stock file names, and keep the total sellable stock as it was stored. Recalculating a run reuses the stock it stored and never reads files again. The upgrade is one-way, so if you want to keep a copy of the v2 file, copy `backend/data/orderplan.db` before restarting the backend.

**Upgrading to v4 (principal MOQ and lead time).** A v3 database is upgraded in place the first time the new backend starts:
- `supplier_settings` gains MOQ (0 for every principal) and lead time columns, the change log gains a setting column, and the schema version moves to 4.
- In the same step, and only then, each principal's lead time is filled in once from the latest saved run. A principal whose SKUs all had the same Data-sheet lead time gets it, and each value is written to the change log (blank → n days). MOQ is not filled in.
- The upgrade does not recalculate any saved run. Until you recalculate it (or save settings), an older plan stays exactly as it was and shows "Saved before MOQ and lead time moved to Principal settings — Recalculate to use the current settings."

To keep the v3 file, copy `backend/data/orderplan.db` to `orderplan.pre-v4-backup.db` before restarting the backend.

## Tests

PowerShell or Git Bash, from the project folder:

```
cd backend
.venv/Scripts/python -m pytest
cd ..
npm --prefix frontend test
```

The backend tests run against a temporary database automatically (`backend/tests/conftest.py` sets `ORDERPLAN_DB` before the app is imported), so they never touch `backend/data/orderplan.db`.

`npm --prefix frontend run build` type-checks and builds the frontend, and `npm --prefix frontend run lint` runs the linter.

## Known limitations

- **No order tracking.** The tool does not record which suggested orders were actually placed. Orders placed since the last upload only count once they appear in the Data file's `SIT Ctns (pending order)` column; until then a mid-month re-run will suggest them again.
- **Stock in transit counts as available.** SIT is added to available stock in full; the Data file has no arrival dates for it.
- **Near-expiry stock still counts as available.** All sellable stock from both reports is counted, however close it is to expiry. The reports carry batch expiry data, so this can be refined later; the cut-off is not decided.
- **Excel is a stand-in.** The stock reports and the sales export are read from Excel files for now; the stock parsers produce plain stock lines that are totalled separately from the calculation, so a database source can replace them later.
- **Lead time does not change the order quantity.** It only sets the next calculation date.
- **No minimum number of valid values.** A buffer built from few values is shown, not hidden. The "Valid" column on the Order plan page (shown as n/6) shows how thin a buffer is.
- **No Yangon/Mandalay split.** One order quantity per SKU.
- **Cartons only.** There are no prices or money values; the sales export's `Amount` column is ignored.
- The forecast is an input; the tool does not generate or adjust it.
- Shelf life is not used (no shelf-life capping), and MOQ is treated as a minimum, not a multiple.

## Removed since v1

The v1 day-by-day simulation is gone: reorder and target days, the list of future orders, the weekly projection and stock chart, the "orders due within N weeks" window, the v1 flags (Order now, Stock-out risk, Excess and so on) and shelf-life capping. The charting library (`recharts`) is no longer a dependency.
