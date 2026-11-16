# Stock in Transit by Arrival Week — Design

Date: 2026-11-10
Status: Draft for review
Builds on: `2026-11-05-weekly-order-cycle-design.md` and the changes since (holding in days, buffer = avg sales ÷ 30 × holding days, the Weeks view, the file renames). Everything not mentioned here stays as built.

## 1. Why this change

Stock in transit (SIT) is in the Sales Forecast file's Data sheet today as one number per SKU ("SIT Ctns (pending order)"). The app counts all of it as stock from the plan date. The planner's team now keeps SIT in a separate sheet, "SIT by weekly", that says **which week each delivery arrives** and whether it goes to Yangon or Mandalay. The planner wants the app to:

- take SIT only from that sheet, uploaded as its own file;
- follow each delivery to the week it lands, so the order plan's stock follows reality and the app can flag SKUs that will run out before their SIT arrives.

## 2. What the planner decided

- **SIT comes only from the new file.** The Data sheet's SIT column is no longer read.
- **The SIT file is a separate, required upload** on the New plan page, labelled **"Stock in Transit (.xlsx)"**. All five files are required.
- **Week dates (the planner agreed to this reading):** weeks run Monday to Sunday, and **W1 is the week that holds the 1st of the month**. So in October 2026, Oct W3 = Mon 12 – Sun 18 Oct (the plan week), Oct W4 = 19–25 Oct, Oct W5 = 26 Oct – 1 Nov, which is also Nov W1.
- **The hidden Yangon "Oct W3 Arrival" column is real SIT**, not stock already received. (Its total is in the sheet's own Total SIT, and the stock reports were printed on the morning of 12 Oct, before any Oct W3 delivery.)
- **Yangon and Mandalay are added together.** The app plans one combined stock.
- **Order quantities do not drop SIT:** stock on its way still counts when deciding how much to order, so it is never ordered twice.

## 3. The Stock in Transit file

- **Which sheet:** the first sheet that has a **"SAP Code"** header cell in its first 10 rows and at least one **arrival column** in that header row. The sheet name doesn't matter, so the team can upload the whole planning workbook, a copy of "SIT by weekly", or a one-sheet export.
- **Arrival columns:** a header of the form `<month> W<n> Arrival`, ignoring case and extra spaces. `<month>` is a month name or its short form (Jan, Feb, …, Sep or Sept, …, Dec); `<n>` is 1 to 5. Every other column is ignored, including the "Total SIT" column, the YGN/MDY group row above the header and the IMS forecast columns. Hidden columns are read like any other.
- **Same label twice** (once under YGN and once under MDY): their values are added.
- **Values:** a blank cell is 0. A number above 0 is an arrival. Fractions are kept (one Constellation SKU has 880.73). A negative number or text is skipped, with a warning naming the SAP code and the column.
- **Same SAP code on more than one row:** the rows' arrivals are added (as the stock files do).
- **The week's date:** the delivery lands on the **Monday** of its week. Week n's Monday = the Monday on or before the 1st of `<month>` + 7 × (n − 1). The year is the one that puts `<month>` nearest the Sales Forecast file's MTD month (so a plan in December reading "Jan W1" means the next January).
  - **The planner confirmed:** the last week of a month and W1 of the next month are the same week whenever the 1st isn't a Monday. For example, Oct W5 and Nov W1 both mean 26 Oct – 1 Nov, and both land on Monday 26 Oct. Nov W2 starts Monday 2 Nov.
- **Errors that stop the upload** (shown as "Stock in Transit file: …", like the other files):
  - no sheet with a "SAP Code" header and an arrival column: "No sheet has a SAP Code column and '<Month> W<n> Arrival' columns (looked in the first 10 rows of each sheet).";
  - the file isn't a readable .xlsx (the same message style as the other files).
- **Warnings** (source "Stock in Transit file" in the warnings panel and the Excel Warnings sheet):
  - "<n> stock codes in the Stock in Transit file are not in the Sales Forecast file; ignored";
  - "<n> SKUs in the Sales Forecast file are not in the Stock in Transit file; their SIT is 0" (only when n > 0);
  - each skipped value (SAP code, column, "not a number of cartons above 0");
  - arrivals dated after the end of plan month 12: "arrives after the plan ends; counted as on order but never as stock" (SAP code and date). Unlikely, but defined.

## 4. The Sales Forecast file

- **"SIT Ctns (pending order)" is no longer required.** If it is there, it is ignored, and the existing "columns are ignored" note lists it with the stock columns.
- **"UOM" is accepted as the packing size column**, as well as "Packing Size". (The new file renamed it; the values are the same.)

## 5. The calculation

Per SKU, from the SIT file: a list of **arrivals** (date, cartons), and **SIT = their total**.

### Order demand forecast mode — unchanged

Available = sellable + SIT, from the plan date, as today. Required, order, stock cover and the 12-month forecast are unchanged.

### Order plan mode

- **Arrival day:** an arrival dated before the plan date lands on the plan date. Otherwise it lands on its date.
- **Stock on hand, day by day,** starts at **sellable** (not available) on the plan date. On each day, in this order:
  1. that day's arrivals are added;
  2. if it is an order date, the order is placed (below) and added;
  3. that day's demand is taken off.
- **Each order** is worked out from **stock on hand + SIT still to arrive** (arrivals dated after that day). The rule is otherwise today's: required = max(order-up-to, cover until the next order date) − that stock, rounded up, raised to the MOQ.
- **Order quantities are therefore identical to today's in every case**, whatever the arrival dates: stock on hand + SIT still to arrive always equals today's stock (sellable + all SIT, rolled forward). This is intended (the planner agreed SIT on its way must still count, so it is never ordered twice). Arrival dates change only stock on hand (the month openings, arrivals and closings) and the run-out flag. Tests must show identical order lines for early, late and mixed arrivals.
- **Stock on hand can go below 0** in the order plan when SIT lands late (my call: shown as it is, in the same style as any negative stock today; the run-out flag explains it).
- **Per month** (what the screens show): opening = stock on hand at the start of the month's first planned day (sellable for month 1); **arrivals = SIT landing in the month**; orders and demand as today; closing = opening + arrivals + orders − demand.
- **This month's order, order-up-to and required** in Order plan mode keep their meaning, using the plan-date order. `plan_required` uses available (sellable + all SIT) as today.

### "Runs out before its SIT arrives"

- For each SKU with SIT, follow stock on hand from the plan date with **no new orders**: sellable, plus arrivals on their days, minus each day's demand (the same daily demand as the order plan).
- If it falls below 0 on a day **before its last arrival**, the SKU is flagged with the first such day and the next arrival after it, for example: "runs out about 15 Oct, before its stock in transit arrives on 19 Oct".
- New orders are left out on purpose: an order placed today won't arrive before SIT already on the way, so the flag means "chase this delivery".
- A SKU with no demand data or no SIT is never flagged. The flag doesn't depend on the holding.
- It is worked out in plan_all, so a Recalculate keeps it current.

### Saved runs

- Runs saved before this change have no arrivals (stored as missing, not as an empty list). **My call:** wherever arrivals are used (the calculation, the Weeks view, the SKU detail's Stock in transit list), such a run's SIT counts as **one arrival on the plan date**. Its orders and closings are the same as before. After Recalculate, month 1's opening becomes sellable with the SIT in the Arrivals column, which is a deliberate change in what opening means. A run with SIT 0 has no arrivals. Older runs are never flagged, since all their SIT lands on day one.
- **Before Recalculate**, an older run's stored month plans have no arrivals field: they are shown as stored, with Arrivals shown as "—" (my call: no "Recalculate" prompt, since nothing is wrong with them).
- New runs store the arrivals with the parsed input (an empty list for a SKU with no SIT), so Recalculate (after a settings change) uses them again.

## 6. Storage

- **Database v8:** `runs` gains `sit_file_name TEXT NULL`, added in one transaction like the earlier upgrades, and the schema version goes from 7 to 8. Older runs keep NULL. Back up `orderplan.db` to `orderplan.pre-v8-backup.db` before restarting the backend on the new code.
- Each run stores a short SIT file summary next to the stock summaries: SKUs with SIT, total cartons, first and last arrival date. Where it lives is the builder's call.

## 7. Screens

1. **New plan page:** a fifth file box, **"Stock in Transit (.xlsx)"**, after PDG Stock List. The intro sentence mentions it. The file check after choosing files shows its summary: SKUs with SIT, total cartons, and the arrival weeks it covers (for example "44 SKUs, 12,211 cartons arriving 12 Oct – 26 Oct").
2. **History page:** a "Stock in Transit file" column ("—" for older runs).
3. **Plan page:**
   - the "From …" line lists the SIT file after the stock files;
   - in the **Weeks** view, a week with arrivals shows them in the cell (for example "+5,250 arriving"), styled apart from order lines;
   - a SKU flagged as running out before its SIT arrives gets a red chip on its row, with the message on hover. The chip shows in both modes.
4. **SKU detail:**
   - a **Stock in transit** list: arrival date and cartons, one row per arrival (or "No stock in transit");
   - in Order plan mode the 12-month table gains an **Arrivals** column, and its opening and closing follow section 5;
   - the flag's message, when flagged.
5. **Warnings panel:** a new source, "Stock in Transit file", for the file's warnings. The run-out flags are listed there too.
6. **Excel export:** the SKU Plan sheet's SIT column is the total, as today. The flag appears in the Warnings sheet. **Otherwise unchanged** (my call: arrivals in the export can come later).
7. **README:** the new file, the week rule, how arrivals change the order plan, the run-out flag, the UOM header and the v8 upgrade.

## 8. Non-goals

- Planning Yangon and Mandalay separately, or reading the regional IMS forecast in the SIT sheet.
- Using lead time to delay new orders.
- Arrivals in the Excel export.
- Reading SIT from the Data sheet as a fallback.
- Changing Order demand forecast mode.

## 9. Left to the builder

- Model and field names, and where the SIT parser lives (suggestion: a new `sit.py` next to `stock.py`, with `parse_sit` and `apply_sit` like `parse_pg` and `apply_stock`).
- The exact look of the arrivals in the Weeks view and of the run-out chip.
- **Tests** must cover:
  - the week rule: Oct W3 2026 → Mon 12 Oct; Oct W5 → 26 Oct; Nov W1 → 26 Oct; Nov W2 → 2 Nov; a month whose 1st is a Monday (Feb 2027 W1 → 1 Feb); the year for "Jan W1" in a December plan;
  - header matching: "Sept", short and long names, extra spaces and case; non-arrival columns ignored; a duplicate label under YGN and MDY added;
  - the sheet found by headers, not name; a hidden column read; the missing-sheet error;
  - blank, negative, text and fractional values; duplicate SAP rows; SAP codes missing either side;
  - the Data sheet without the SIT column, with it (ignored and noted), and with "UOM" in place of "Packing Size";
  - the order plan: stock on hand starts at sellable; arrivals on their day; an arrival before the plan date; orders the same as today when all SIT arrives before the next order; an order date before a later arrival counting it as SIT still to arrive; the month Arrivals column and closings;
  - the run-out flag: flagged with the right dates, not flagged when sellable lasts, not flagged with no SIT or no demand;
  - an older run (no arrivals): shown as stored before Recalculate; after Recalculate the same order lines and closings as before, with month 1 opening = sellable and Arrivals = SIT;
  - the v8 upgrade of a v7 database (column added, version 8, runs again safely);
  - the upload API with five files and an error from the fifth named "Stock in Transit file";
  - the frontend: the fifth file box, the History column, the arrivals in the Weeks view, the SKU detail list and Arrivals column, the chip, and the new warnings source.
- Use the planner's real file only through copies; never in tests against `backend/data/orderplan.db`.

## 10. Working constraints

- **No commits.** The planner asked for no commits at all: the earlier work (holding in days, the Weeks view, the file renames) is uncommitted in the working tree of `feature/order-plan-tool`, and this feature is built on top of it in the same working tree, also uncommitted. No worktree or new branch (one cut from HEAD would miss that work).
- Tests and probes never touch `backend/data/orderplan.db` or its backups; use copies or a temporary `ORDERPLAN_DB`.
