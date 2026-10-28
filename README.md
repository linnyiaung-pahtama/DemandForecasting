# Order Plan Tool

A local tool that turns the planner's Excel forecast and the sales export into a per-SKU order plan. Each cycle you upload two files, and you set one holding (in months of stock) per supplier. For every SKU the tool works out the average monthly demand, the stock you should hold, and the cartons to order to get there, with every number shown. It rolls the plan up by supplier, exports it to Excel, and keeps a history of past runs.

It runs on your own Windows computer: a Python (FastAPI) backend with a SQLite database, and a React web page in the browser.

## Requirements

- Python 3.12
- Node 22.12 or later (needed by vitest 5; the app uses React 19 and Vite 6)

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

Then open http://localhost:5173. The frontend forwards `/api` requests to the backend, so both must be running. `.claude/launch.json` holds the same two commands for Claude Code's preview.

## Using it

1. **New plan**: choose the two files (the Data file and the sales export), check the detected months, plan date and any warnings, then click Calculate. Calculate is enabled once both files inspect OK.
2. **Order plan**: count cards (SKUs to order, Holding not set, No demand data, Zero forecast), a banner listing blocked suppliers, and filters for supplier, status, the Zero forecast flag and search. Click a SKU to see its six demand values and the arithmetic behind its order. The supplier summary is reached from this page.
3. **Supplier summary**: per supplier, the holding, SKU counts, total order cartons and blocked / no-demand SKUs. Expand a supplier for the list of SKUs to put on one purchase order.
4. **Supplier settings**: one Holding (months) per supplier, plus the change log. Saving recalculates the latest run.
5. **History**: reopen a past run exactly as it was calculated.
6. **Export**: Excel download with four sheets: SKU Plan, Supplier Summary, Settings Used and Warnings.

## The two uploads

Each cycle needs two files. In the API they are the multipart fields `data_file` and `sales_file`.

### Data file

Only the `Data` sheet is read; all other sheets are ignored. Layout: row 1 empty, row 2 column totals (ignored), row 3 headers, one SKU per row from row 4. The tool matches headers tolerantly (extra spaces are fine) and finds the forecast and month-to-date columns by pattern, so next month's file works unchanged.

Columns it uses:

| Header | Meaning |
|---|---|
| `SAP Code` | SKU id (read as text, unique) |
| `By Principal` | Supplier |
| `Description` | SKU name |
| `Packing Size` | Pieces per carton; used to convert the sales export from pieces to cartons |
| `MOQ` | Minimum order in cartons (0 = none) |
| `Lead Time` | Days from order to arrival; sets the next calculation date only |
| `Total Sellable (Ctns)` | Sellable stock on hand |
| `SIT Ctns (pending order)` | Stock in transit / already ordered |
| `Oct'26  MTD Sale (1-11 Oct)` | Sets the MTD month and the stock date (MTD end). The default plan date is the day after, and the plan date can be at most the end of that month. The MTD quantity itself is not used |
| `2026 Oct IMS` ... `2027 Sep IMS` | Monthly forecast in cartons, consecutive months starting no later than the MTD month (month names may be full, 3 or 4 letters, e.g. `Sept`). The MTD month and the next 2 are used |

`Shelf Life month` and `Total Non-Sellable (Ctns)` are still read and checked but are not used in the calculation.

A missing `Data` sheet or required column, forecast months with a gap, or a forecast that starts after the MTD month rejects the file with a message. Per-row problems (non-numeric values, negative month-to-date sales, negative forecast, zero or negative shelf life, missing lead time) and unrecognised `IMS` headers are kept and shown as warnings; nothing is cleaned silently.

### Sales export

This is admin's system export of past sales.

- A sheet whose header row (within the first 10 rows) contains `itemCode`, `Year`, `Month` and `Qty`. The sheet is found by its headers, not its name. Other columns and other sheets are ignored.
- One row per branch, item and month. `Month` is a month name (`Jul`) and `Year` a number (`2026`).
- `Qty` is in **pieces**. The tool sums `Qty` over all rows for an item and month, then divides by the item's `Packing Size` in the Data file to get cartons (for example 2,113 pieces / 40 = 52.83 cartons).
- It must cover the 3 months before the MTD month (Jul, Aug, Sep 2026 for an October MTD). The file is rejected if it has none of them. If only one or two are missing, the run continues and the missing months count as missing demand, with a warning.

Also warned about, and the run continues: extra months in the export (ignored), items not in the Data file (ignored), items with sales but no usable Packing Size (their actuals count as missing), and non-numeric `Qty` (row skipped).

## How the order is calculated

The months: actual months are the 3 calendar months before the MTD month; forecast months are the MTD month and the next 2. Example: a Data file dated 12 Oct with an MTD of 1-11 Oct gives actuals Jul, Aug, Sep 2026 and forecasts Oct, Nov, Dec 2026.

For each SKU:

1. **Buffer** (average monthly demand, cartons) = the mean of the valid values among the 3 actual and 3 forecast months. A value is valid if it is greater than 0; zero, negative (net returns), blank and missing values are skipped.
2. **Target stock** = buffer x holding (months).
3. **Available stock** = Total Sellable + SIT.
4. **Required** = target - available, never below 0, rounded up to whole cartons.
5. **MOQ check**: if 0 < required < MOQ, the order is the MOQ (tagged "MOQ"). If required is 0, the order is 0 and is not raised to MOQ.
6. **Stock cover** (months) = available / buffer. Not shown if there is no buffer.
7. **Next calculation date** = plan date + lead time (days). Not shown, with a warning, if lead time is missing or negative.

Worked example (holding 3 months, available stock 260, MOQ 150, plan date 14 Oct 2026, lead time 61 days):

| Step | Working | Result |
|---|---|---|
| Valid values | 100, 120, 110, 130, 140, 120 (6 of 6) | |
| Buffer | (100 + 120 + 110 + 130 + 140 + 120) / 6 | 120 |
| Target | 120 x 3 | 360 |
| Available | Total Sellable + SIT | 260 |
| Required | 360 - 260 | 100 |
| Order | 100 is below the MOQ of 150, so the MOQ applies | 150 |
| Stock cover | 260 / 120 | 2.2 months |
| Next calculation date | 14 Oct 2026 + 61 days lead time (about 2 months) | 14 Dec 2026 |

The SKU detail page writes out this arithmetic for every SKU, with the six values and which were valid.

## Statuses and flags

| Status | Meaning |
|---|---|
| **To order** | The supplier has a holding and the order quantity is above 0. |
| **No order needed** | The supplier has a holding and available stock already covers the target, so the order is 0. |
| **Holding not set** | The supplier has no holding yet, so its SKUs are blocked: target, required and order are shown as "-". Buffer, available and cover are still shown. The run is not rejected; a banner lists the blocked suppliers with a link to Supplier settings. |
| **No demand data** | None of the 6 values is valid, so there is no buffer. Target and order are 0 and cover is "-". |

**Zero forecast** is a flag, not a status. It is raised when all 3 forecast months are 0 or invalid but at least one actual month is valid. The order is still calculated from the actuals, and the flag tells the planner to review the SKU before ordering. It shows in the table, on a count card, and as a filter option, whether or not the order is above 0.

## Holding settings

- One **Holding (months)** per supplier (`By Principal`), on the Supplier settings page. The range is 0.5 to 24 months and decimals are allowed (for example 1.5).
- A blank value means not set. There is no default: a supplier with no holding is blocked (status Holding not set) until you enter one.
- Every change is recorded in the change log: supplier, old value, new value and time (newest first). There is no user name, because the tool is single-user.
- Saving sends only the changed rows and recalculates the latest run. The Order plan page also has a Recalculate button.
- Lead time and MOQ are not settings; they come from the Data file.

## Database

SQLite file at `backend/data/orderplan.db` (created on first start; not committed to git). It holds supplier holdings, the change log and all runs. To use a different file, set the `ORDERPLAN_DB` environment variable before starting the backend:

```
$env:ORDERPLAN_DB = "C:\path\to\other.db"      # PowerShell
export ORDERPLAN_DB=C:/path/to/other.db         # Git Bash
```

The `$env:` setting applies only to the current PowerShell window. Starting the app from the Claude launch configuration (`.claude/launch.json`) always uses the default database.

**Upgrading from v1.** If the database file is a v1 one (it has reorder/target days), the tool renames it to `orderplan.v1-backup.db` in the same folder (`orderplan.v1-backup-1.db`, `-2` and so on if that name is taken) and creates a fresh v2 database. Nothing is deleted. v1 runs and settings are not carried over.

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
- **Lead time does not change the order quantity.** It only sets the next calculation date.
- **No minimum number of valid values.** A buffer built from few values is shown, not hidden. The "n of 6" column on the Order plan page shows how thin a buffer is.
- **No Yangon/Mandalay split.** One order quantity per SKU.
- **Cartons only.** There are no prices or money values; the sales export's `Amount` column is ignored.
- The forecast is an input; the tool does not generate or adjust it.
- Shelf life is not used (no shelf-life capping), and MOQ is treated as a minimum, not a multiple.

## Removed since v1

The v1 day-by-day simulation is gone: reorder and target days, the list of future orders, the weekly projection and stock chart, the "orders due within N weeks" window, the v1 flags (Order now, Stock-out risk, Excess and so on) and shelf-life capping. The charting library (`recharts`) is no longer a dependency.
