# Order Plan Tool

A local tool that turns the planner's Excel forecast into a per-SKU order plan. Upload the cycle's input workbook and the tool works out, for every SKU, when to order and how many cartons, based on reorder and target levels (in days of sales) that you set per supplier. It shows the week-by-week projected stock behind each suggestion, flags SKUs that need an order now, may run out of stock, or hold excess stock, rolls the plan up by supplier, exports it to Excel, and keeps a history of past runs.

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
backend/.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000
```

Terminal 2, frontend (port 5173):

```
npm --prefix frontend run dev
```

Then open http://localhost:5173. The frontend forwards `/api` requests to the backend, so both must be running. `.claude/launch.json` holds the same two commands for Claude Code's preview.

## Using it

1. **New plan**: choose the input workbook, check the detected plan date and any warnings, then click Calculate.
2. **Order plan**: filter by supplier, flag or weeks ahead; click a SKU to see its projection and why each order is suggested. The supplier summary is reached from this page.
3. **Supplier settings**: reorder and target days per supplier. Saving re-runs the plan for the current upload. New suppliers start at 20 / 30 days and are flagged until you review them.
4. **History**: reopen a past run exactly as it was calculated.
5. **Export**: Excel download with five sheets: SKU plan, planned orders, supplier summary, settings used and warnings.

## Input file

Only the `Data` sheet is read; all other sheets are ignored. Layout: row 1 empty, row 2 column totals (ignored), row 3 headers, one SKU per row from row 4. The tool matches headers tolerantly (extra spaces are fine) and finds the forecast and month-to-date columns by pattern, so next month's file works unchanged.

Columns it expects:

| Header | Meaning |
|---|---|
| `SAP Code` | SKU id (read as text, unique) |
| `By Principal` | Supplier |
| `Description` | SKU name |
| `Packing Size` | Units per carton (display only) |
| `MOQ` | Minimum order in cartons (0 = none) |
| `Shelf Life month` | Months, or `-` / blank / `0` for unknown (no cap) |
| `Lead Time` | Days from order to arrival |
| `Total Sellable (Ctns)` | Sellable stock on hand |
| `Total Non-Sellable (Ctns)` | Shown only, not used in the calculation |
| `SIT Ctns (pending order)` | Stock in transit / already ordered |
| `Oct'26  MTD Sale (1-11 Oct)` | Sales so far this month; the header's date range sets the plan date (the day after) |
| `2026 Oct IMS` ... `2027 Sep IMS` | Monthly forecast in cartons, 12 months |

A missing `Data` sheet or required column rejects the file with a message. Per-row problems (non-numeric values, negative month-to-date sales, missing lead time) are kept and shown as warnings; nothing is cleaned silently.

## Database

SQLite file at `backend/data/orderplan.db` (created on first start; not committed to git). It holds supplier settings and all runs. To use a different file, set the `ORDERPLAN_DB` environment variable before starting the backend:

```
$env:ORDERPLAN_DB = "C:\path\to\other.db"      # PowerShell
export ORDERPLAN_DB=C:/path/to/other.db         # Git Bash
```

The `$env:` setting applies only to the current PowerShell window. Starting the app from the Claude launch configuration (`.claude/launch.json`) always uses the default database.

## Tests

PowerShell or Git Bash, from the project folder:

```
cd backend
.venv/Scripts/python -m pytest
cd ..
npm --prefix frontend test
```

`npm --prefix frontend run build` type-checks and builds the frontend.

## Known limitations

- **No order tracking.** The tool does not record which suggested orders were actually placed. Orders placed since the last upload only count once they appear in the input's `SIT Ctns (pending order)` column; until then a mid-month re-run will suggest them again.
- **Stock in transit is assumed available from the plan date.** The input has no arrival dates for SIT.
- **No Yangon/Mandalay split.** One order quantity per SKU; the input has no regional forecast split.
- **Cartons only.** The input has no prices, so there are no money values.
- The forecast is an input; the tool does not generate or adjust it.
- MOQ is treated as a minimum (not a multiple), and shelf life is taken as the full shelf life from arrival; batch expiry dates are not used.
- Sales missed during a stock-out are treated as lost, not backordered.
