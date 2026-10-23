# Holding-Based Order Plan — Design (v2)

Date: 2026-10-23
Status: Draft for review
Replaces the calculation in: `2026-10-22-order-plan-tool-design.md` (v1). Everything in v1 not mentioned here stays as built.

## 1. Why this change

The v1 tool simulates each SKU day by day with per-supplier reorder/target days and produces a year of future orders. The planner reviewed it and wants the calculation they actually use: keep a set number of **months of stock** (holding) per supplier, and each cycle order the gap between that target and what is on hand. This is simpler to explain in supplier meetings and matches how orders are placed today (one order per SKU per cycle).

## 2. What stays, what changes, what goes

**Stays (as built in v1):**
- local React + FastAPI + SQLite app;
- Data sheet parsing, including tolerant headers, warnings and the stricter month rules;
- plan date (default = day after the MTD period, latest = end of the MTD month);
- run history;
- supplier summary page;
- supplier settings page with save-only-changed-rows;
- Excel export;
- recalculate the latest run after a settings change.

**Changes:**
- a second upload (the sales export);
- the settings field: one **Holding (months)** per supplier instead of reorder/target days;
- the calculation (section 6);
- the result columns;
- the supplier summary columns;
- the export columns.

**Goes:**
- the day-by-day simulation and the list of future orders;
- reorder/target days;
- the weekly projection and the stock chart;
- the "why" sentence per future order;
- the v1 flags (Order now, Stock-out risk, Excess, Expiry risk, MOQ exceeds shelf life, Lead time ≥ reorder, MTD above forecast, No forecast holding stock);
- the "orders due within N weeks" window;
- shelf-life capping.

## 3. Inputs per cycle

### 3.1 Data file (unchanged file, fewer columns used)
From the `Data` sheet, as v1 parses it:
- **Used columns:** `SAP Code`, `By Principal`, `Description`, `Packing Size`, `MOQ`, `Lead Time` (days), `Total Sellable (Ctns)`, `SIT Ctns (pending order)`, the MTD column (only to determine the MTD month and the plan date), and the forecast columns `YYYY Mon IMS`.
- **Still parsed, not used in the calculation:** `Shelf Life month`, `Total Non-Sellable (Ctns)`, MTD quantity.

### 3.2 Sales export (new, second upload)
This is admin's system export (sample: `actual-sales-3m.xlsx`).
- **Sheet:** use the sheet whose header row contains `itemCode`, `Year`, `Month` and `Qty`. Other columns (`Company`, `BranchName`, `Principal`, `Brand`, `Itemname`, `Amount`) are ignored. Other sheets, such as the `Amount` pivot, are ignored. Find the sheet by its headers, not by its name.
- **Rows:** one row per company × branch × item × month. `Qty` is in **pieces**. `Month` is a month name (`Jul`); `Year` is a number (`2026`).
- **Conversion:** per item and month, sum `Qty` over all rows (all companies and branches), then divide by the Data sheet's `Packing Size` for that SAP Code to get **cartons**.
  - This was verified against the planner's old workbook: 2,113 pieces ÷ 40 = 52.83 cartons, which matches exactly.

## 4. Supplier settings

- **Holding (months)** per supplier (`By Principal`). It is a positive number; decimals are allowed (e.g. 1.5). Valid range: 0.5 to 24.
- **No default.** A supplier without a holding value is **blocked**: its SKUs appear in the plan with status "Holding not set" and no order. A banner lists the blocked suppliers with a link to the settings page. The run itself is not rejected.
- **Every change is logged:** supplier, old value, new value, timestamp. The settings page shows the log, newest first. There is no user identity, because the app is single-user and has no login.
- Lead time and MOQ are **not** settings; they come from the Data sheet.

## 5. Which months

Example: Data file dated 12 Oct, MTD period 1–11 Oct.
- **MTD month** = the month of the MTD column (October 2026).
- **Actual months** = the 3 calendar months immediately before the MTD month (Jul, Aug, Sep 2026).
- **Forecast months** = the MTD month and the next 2 (Oct, Nov, Dec 2026), from the Data sheet's forecast columns.

## 6. Calculation (per SKU)

1. **Buffer** (average monthly demand, cartons): the mean of the **valid** values among the 3 actual months and the 3 forecast months.
   - A value is valid if it is a number **greater than 0**.
   - Zero, negative (net returns), blank or missing values are skipped.
   - An item with no rows in the export for a month has 0 for that month, which is skipped.
   - Example: (100 + 120 + 110 + 130 + 140 + 120) ÷ 6 = 120.
2. **Target stock** = buffer × holding. Example: 120 × 3 = 360.
3. **Available stock** = Total Sellable + SIT. Example: 260.
4. **Required** = target − available, never below 0, **rounded up to whole cartons**. Example: 100.
5. **MOQ check:** if required > 0 and required < MOQ, the order = MOQ (MOQ applied). If required = 0, the order = 0 and is not raised to MOQ. MOQ 0 means no minimum. Example: 100 → 150.
6. **Stock cover (months)** = available ÷ buffer. Example: 260 ÷ 120 = 2.2. If the buffer is 0, cover is not shown ("—").
7. **Next calculation date** = plan date + lead time (days). If lead time is missing or negative, it is not shown, with a warning.

**Special cases:**
- **Holding not set** (supplier blocked): steps 2, 4 and 5 are skipped and the order shows as "—". Buffer, available and cover are still shown.
- **No valid demand values** (buffer cannot be computed): the status is "No demand data", target and order are 0, and cover is "—".
- **Zero forecast** (all 3 forecast months are 0 or invalid, but there are valid actuals): this is the planner's decision. The order is calculated from the actuals as normal, and the SKU gets the status/flag **"Zero forecast"** so the planner reviews it before ordering. The flag shows in the table, on a count card, and as a filter option. It applies whether or not the order is > 0.
- **Lead time** does not change the order quantity (planner's Step 3). Holding counts stock on hand plus SIT. Lead time only sets the next calculation date.

Every number in steps 1–7 is stored with the SKU result. The SKU detail shows the six input values, marks which were valid, and writes out the arithmetic as in the example above. This continues v1's "no black box" anti-goal.

## 7. Validation and warnings

**Reject the sales export (HTTP 400, clear message) if:**
- it is not a readable .xlsx;
- no sheet has `itemCode`, `Year`, `Month` and `Qty` headers;
- or it contains **none** of the 3 actual months.

**Warn but continue (shown on upload, in the run and in the export) when:**
- one or two of the 3 actual months have no rows at all ("No sales rows for Aug 2026 — counted as missing");
- the export has extra months (ignored);
- an item is in the export but not in the Data sheet (ignored);
- a SKU has sales but its `Packing Size` is missing or 0 (its actuals become invalid);
- `Qty` is non-numeric (the row is skipped).

**Data file:** all v1 validation stays.

## 8. Screens

1. **Upload:**
   - Two file pickers: Data file and Sales export.
   - Inspect shows:
     - SKU and supplier counts;
     - the MTD month, the 3 actual months and the 3 forecast months detected;
     - how many SKUs have actual sales;
     - the plan date (editable, same range as v1);
     - warnings from both files.
   - Calculate is enabled when both files inspect OK.
2. **Order plan:**
   - **Header:** plan date, file names, buttons for Supplier summary, Recalculate and Export.
   - **Count cards:** SKUs to order, Holding not set, No demand data, Zero forecast.
   - **Banner:** blocked suppliers.
   - **Filters:** supplier, status (To order / No order needed / Holding not set / No demand data), a "Zero forecast" flag filter, and search.
   - **Table columns:** Supplier, SAP Code, Description, Available, Buffer, Valid values ("n of 6"), Holding, Target, Order qty (with an "MOQ" tag when applied), Stock cover (months), Next calculation date, Status.
     - **Builder's call:** there is no minimum number of valid values; a buffer built from fewer values is shown, not hidden. The "n of 6" column makes thin buffers visible.
   - **SKU detail:**
     - the 3 actual months and 3 forecast months with values, with valid ones marked;
     - the step-by-step arithmetic from section 6;
     - lead time, MOQ and any warnings for this SKU.
3. **Supplier summary:**
   - Per supplier: Holding, SKUs, SKUs to order, total order cartons, SKUs blocked or with no demand.
   - Expanding a supplier lists its SKUs with an order > 0 (SAP code, description, order qty, next calculation date). This is the list for one purchase order.
4. **Supplier settings:**
   - One editable column, Holding (months).
   - Rows without a value are highlighted "Holding not set — SKUs blocked".
   - The page shows each supplier's SKU count and max lead time.
   - Save sends only changed rows, then recalculates the latest run.
   - **Change log** below the table.
5. **History:** unchanged.
6. **Export:**
   - **SKU Plan:** all the table columns, plus the 6 input values, MOQ, lead time and status.
   - **Supplier Summary.**
   - **Settings Used:** supplier and holding.
   - **Warnings:** from both files.

## 9. Storage

- `supplier_settings` changes to (`supplier`, `holding_months` nullable, `updated_at`).
- A new table, `settings_log` (`id`, `supplier`, `old_value`, `new_value`, `changed_at`).
- `runs` also stores the sales export file name and the parsed actuals.
- The v1 database is empty, and the tool has not been released. The schema can be replaced; no migration is needed. On startup, if an old-schema DB is found, recreate it, or refuse with a clear message. **Builder's call.**

## 10. Non-goals (v2)

- Forecasting.
- A Yangon/Mandalay split.
- Money values. The export's `Amount` column is ignored.
- Order tracking.
- Shelf-life capping.
- Per-SKU holding overrides.
- Lead time or MOQ edited in the tool.

## 11. Left to the builder

- Module layout. Prefer replacing `demand.py`/`engine.py` with a new `holding.py`, and adding `sales.py` for the export parser.
- The exact API shape (two-file multipart).
- UI details.
- Test approach. Unit tests must cover:
  - each step of section 6, using the spec's worked example;
  - the valid-value rules;
  - MOQ edge cases;
  - blocked suppliers and no-demand SKUs;
  - export parsing, including unit conversion and all the section 7 cases;
  - the settings log.

## 12. Calls made in design (confirm in review)

The planner agreed to these as proposals ("ok"); they were not specified by the planner directly.
- The forecast months are the MTD month and the next 2.
- Valid means > 0.
- An item missing from the export means 0, which is invalid.
- The run date is the plan date.
- Required is rounded up to whole cartons.
- MOQ is not applied when the requirement is 0.
- Holding range is 0.5–24 months, with decimals allowed.
- A blocked supplier's SKUs stay in the run, marked "Holding not set", rather than the run being rejected.
- The settings log has no user name.
