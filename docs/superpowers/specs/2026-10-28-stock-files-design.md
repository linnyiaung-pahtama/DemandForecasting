# Stock From PDG Stock List and PG Expiry Check — Design (v3 inputs)

Date: 2026-10-28
Status: Draft for review
Builds on: `2026-10-23-holding-based-order-plan-design.md` (v2). Everything in v2 not mentioned here stays as built.

## 1. Why this change

Today the planner copies stock figures into the Data sheet by hand (Sellable/Non-Sellable for PG and PDG, plus totals). They want to remove those columns from the Data sheet and upload the two stock reports they come from, **PDG Stock List** and **PG Expiry Check**, as separate files. The tool then adds up stock per SKU itself.

The planner also said that **the Excel uploads are a testing stand-in**. Later, most of the data (stock, sales, master data) will come from a database. This design must not lock the calculation to Excel layouts (section 8).

## 2. What stays, what changes

**Stays:**
- the calculation (v2 section 6), including Available = Total Sellable + SIT;
- the sales export upload;
- holding settings, statuses, the supplier summary, history and recalculate.

**Changes:**
- **Two more uploads:** a PDG Stock List file and a PG Expiry Check file. Each cycle needs four files.
- **Stock no longer comes from the Data sheet.** The Data sheet's stock columns become optional and are ignored.
- **More stock detail:** the SKU detail and the export show sellable stock split into PG and PDG.
- **Each run stores** the two stock file names and the per-SKU stock breakdown.

## 3. Inputs per cycle

### 3.1 Data file
Same `Data` sheet as v2, with fewer required columns.
- **Required:** `SAP Code`, `By Principal`, `Description`, `Packing Size`, `MOQ`, `Shelf Life month`, `Lead Time`, `SIT Ctns (pending order)`, the MTD column, and the forecast columns. These rules are unchanged from v2.
- **No longer required, and ignored if present:** `Sellable (PG)`, `Sellable (PDG)`, `Total Sellable (Ctns)`, `Non-Sellable (PG)`, `Non-Sellable (PDG)`, `Total Non-Sellable (Ctns)`.
  - If any of these columns is present, show one warning: "Stock columns in the Data sheet are ignored; stock comes from the PDG Stock List and PG Expiry Check files." This tells the planner they can remove them.
- **The Data sheet stays the master SKU list.** Only SKUs in the Data sheet are planned. SIT still comes from the Data sheet, because neither stock report has it: PDG's `OnOrder` is 0 for every row, while the Data sheet has SIT for 6 PDG SKUs.

### 3.2 PDG Stock List (new upload)
The system stock report. Sample: the `PDG Stock List` sheet in `Local Principals data for Demand Forecasting Tool.xlsx`.
- **Layout:** two report-parameter rows at the top (`Printed_Date`, `Item_Code`, … and their values), a blank row, then the header row (row 4 in the sample), then one row per stock code × warehouse location × bin × batch.
- **Finding the sheet:** use the sheet whose header row (within the first 10 rows) contains `StockCode`, `Location`, `Bin_Qty`, `U_Ratio` and `Sell or Non`. Find it by its headers, not by the sheet name, as the sales export is found.
- **Columns used:**
  - `StockCode`: matches the Data sheet's `SAP Code`. In the sample it is numeric (e.g. `120701330181`); normalise it the way the Data sheet's SAP codes are normalised.
  - `Bin_Qty`: quantity in pieces.
  - `U_Ratio`: pieces per carton.
  - `Sell or Non`: blank means sellable; `Non` means non-sellable.
  - `Location`: used only for warnings.
- **Cartons per row** = `Bin_Qty ÷ U_Ratio`.
  - The sample has a `cs` column with the formula `=BI/L`, which is the same thing. It was added by the planner, so the tool computes the value itself and does not need `cs`.
- **Printed date:** the value under `Printed_Date` in the parameter rows (12 Oct 2026 06:45 in the sample). It is optional: if it isn't found, there is no date check.

### 3.3 PG Expiry Check (new upload)
The batch-level stock report. Sample: the `PG Expiry Check` sheet in the same workbook.
- **Layout:** an optional totals row (SUBTOTAL formulas), then the header row (row 2 in the sample), then one row per item × batch × warehouse × bin.
- **Finding the sheet:** use the sheet whose header row (within the first 10 rows) contains `Item Code`, `Location` and `Ctn`.
- **Columns used:**
  - `Item Code`: matches `SAP Code`. It is text in the sample.
  - `Ctn`: cartons. It equals `SOH ÷ UOM` on every row of the sample.
  - `Location`: `Sellable` or `Non-Sellable`.
- **Report date:** PG has no printed date, but on every dated row `expired Date − Day Left` is the date the report was run. In the sample, all 6,096 such rows give 12 Oct 2026, and `Day Left` is a stored value, not a formula. Use the most common of these dates as PG's "as of" date. If no row has both values, there is no date check.
- **The `Location` column alone decides sellable vs non-sellable.** This is the planner's decision. The `WH Code info` sheet and its `SellableFlag` are **not** used. They disagree with `Location` for about 1,160 cartons, mostly transit (WT) warehouses, and the Data sheet has always followed `Location`.

### 3.4 Verified against the planner's current Data sheet
Using the rules above on the sample workbook reproduces the Data sheet's `Sellable (PG)`, `Non-Sellable (PG)`, `Sellable (PDG)` and `Non-Sellable (PDG)` for **all 212 SKUs** (within 1e-6). This is the acceptance check for the parsers (section 10).

## 4. Stock per SKU

For each SAP Code in the Data sheet:
- **PG sellable / PG non-sellable** = the sum of `Ctn` over PG rows for that Item Code, split by `Location`.
- **PDG sellable / PDG non-sellable** = the sum of `Bin_Qty ÷ U_Ratio` over PDG rows for that StockCode, split by `Sell or Non`.
- **Total Sellable** = PG sellable + PDG sellable. **Total Non-Sellable** = PG non-sellable + PDG non-sellable.
- **A SKU in neither file has 0 stock, with no warning.** That is normal: 76 of the 212 SKUs have no stock in the sample.
- **The same code in both files** is allowed and simply adds up. It doesn't happen in the sample: PG holds the local principals and PDG holds Myanmar Vineyard Estate, Secret Spice and Kan Sein.

Total Sellable then feeds v2's Available = Total Sellable + SIT unchanged. Non-sellable stays informational only.

## 5. Validation and warnings

**Reject the file (HTTP 400, message prefixed with "PDG Stock List: " or "PG Expiry Check: ") if:**
- it is not a readable .xlsx;
- no sheet has the required headers (the message names the headers it looked for);
- or the sheet has **no data rows** under the header.

**Warn but continue (shown on upload, in the run, and in the export's Warnings sheet):**
- **Unknown flag values:** a `Location` value other than `Sellable`/`Non-Sellable` (PG), or a `Sell or Non` value other than blank/`Non` (PDG). The row is counted as **non-sellable**, so unknown stock never reduces an order. Give one warning per distinct value, with a row count.
- **Unreadable quantities:** a non-numeric `Ctn`/`Bin_Qty`, or a missing, non-numeric or 0 `U_Ratio`. The row is skipped. Give one warning per file with a row count, plus the affected codes when they are in the Data sheet.
- **Unknown codes:** codes in a stock file that are not in the Data sheet are ignored, with one warning per file giving the count (8 PDG codes in the sample).
- **No matching SKUs:** a stock file has rows, but none of its codes are in the Data sheet. Show a prominent warning: "PG Expiry Check has no stock for any SKU in the Data sheet — check that it is the right report." It is a warning, not a rejection, because a principal group can legitimately have no stock.
- **Hidden rows:** both sample sheets have an AutoFilter. If a sheet has rows hidden by a filter, the hidden rows **still count**. Warn: "N rows are hidden by a filter in PG Expiry Check; they are still counted." Reading row visibility needs openpyxl's normal (not read-only) mode for that check; the sample's 6,000 rows are fine.
- **Old stock date:** the PDG printed date, or the PG as-of date, is more than 3 days away from the plan date. Example: "PDG Stock List was printed on 2 Oct 2026, 10 days before the plan date."
  - The plan date can change on the upload page, so check this when the run is created as well as at inspect.
- **Negative totals:** v2's existing "negative stock — check the stock report" warning now applies to the computed totals.

## 6. Screens

1. **Upload:**
   - Four file pickers: Data file, Sales export, PDG Stock List, PG Expiry Check.
   - Inspect also shows:
     - how many Data SKUs have stock;
     - total sellable cartons from PG and from PDG;
     - the PDG printed date and the PG as-of date.
   - Calculate is enabled when all four files inspect OK.
2. **Order plan header:** also lists the two stock file names.
3. **SKU detail:**
   - Available is shown as PG sellable + PDG sellable + SIT, with each part shown.
   - Non-sellable (PG/PDG) is shown as information.
4. **Export (SKU Plan sheet):** add PG Sellable, PDG Sellable, PG Non-Sellable and PDG Non-Sellable columns next to Available.
5. **History:** each run also shows the stock file names. Runs saved before this change show "—".

## 7. Storage

- `runs` also stores the two stock file names, and the per-SKU stock breakdown as part of the parsed input.
- **Recalculate reuses the stored stock.** It never reads files again.
- **Existing v2 runs in the planner's database must keep opening and recalculating.** The planner has real runs and holding settings in `backend/data/orderplan.db`. Add the new columns with defaults (an `ALTER TABLE` migration). Don't recreate the database, and don't use the v1 "rename to backup" path. Old runs have no stock breakdown: show "—" for the split, and keep Total Sellable as stored.

## 8. Built for a database source later

The planner will later feed stock, sales and master data from a database instead of Excel. So:
- **Keep reading separate from calculating.** Each stock parser turns its file into plain stock lines (code, cartons, sellable yes/no, source PG/PDG). A separate step totals those lines per SAP code and merges them into the SKU inputs. The calculation (`holding.py`) only sees totals and must not know where they came from.
- **Later, a database reader can produce the same stock lines** and replace the file parsers without touching the totals step or the calculation.
- **Excel-only work stays modest.** No layout auto-detection beyond finding the header row, and no support for other file formats (.xlsb, .csv).

## 9. Non-goals

- **Excluding near-expiry stock from Available.** The planner wants this later ("keep that in mind"). For now all sellable stock counts, however close to expiry. Both files carry batch expiry data (`expired Date`/`Day Left`/`Status` in PG, `ExpMonth`/`ExpMonthStatus` in PDG) for when it's built. The cut-off is not decided.
- Using `WH Code info` or any warehouse-level rules.
- A Yangon/Mandalay or branch split.
- Taking supplier, packing size, lead time, shelf life or SIT from the stock reports. The Data sheet stays the source for all of these.
- Reading from a database (section 8 only keeps the door open).

## 10. Left to the builder

- Module layout. Suggestion: `stock.py` holds both parsers, the stock-line type and the totals/merge step.
- The exact API shape: two more multipart fields on `/api/inspect` and `/api/runs`.
- How the breakdown is stored inside the parsed input.
- UI details.
- **Tests** should cover:
  - both parsers on synthetic workbooks: header row found below report rows or a totals row, numeric vs text codes, the sellable split, unknown flag values, unreadable quantities, unknown codes;
  - the printed-date warning;
  - the merge, including SKUs in neither file and codes in both;
  - an old Data sheet that still has stock columns, and a new one without them;
  - opening and recalculating a run saved before the migration.
- **Do not commit the planner's real workbook.** Run the section 3.4 check once against the planner's file (it is in their Downloads folder, outside the repo) and report the result.

## 11. Calls made in design (confirm in review)

The planner decided:
- only the stock columns move out of the Data sheet;
- PG's `Location` column decides sellable;
- all sellable stock counts for now;
- the uploads have the same layout as the sample sheets.

These were proposed and not objected to:
- All four files are required. A missing stock file would make a whole group of SKUs look empty and over-order.
- Header-based sheet detection.
- 0 stock, without a warning, for SKUs in neither file.
- Ignoring the Data sheet's stock columns, with one warning.
- One count warning for codes not in the Data sheet.
- The PDG printed-date check.
- The PG/PDG split in the SKU detail.
- Stock file names stored per run.

These are the builder's own calls, made in this document:
- Unknown flag values count as non-sellable.
- Rows with unreadable quantities are skipped, with a warning.
- The printed-date tolerance is 3 days.
- The `ALTER TABLE` migration that keeps existing runs.
- The `cs` column is not required.
- PG's as-of date is derived from `expired Date − Day Left`.
- A stock file with no data rows is rejected; a file that matches no Data SKU gets a warning.
- Rows hidden by a filter still count, with a warning.
