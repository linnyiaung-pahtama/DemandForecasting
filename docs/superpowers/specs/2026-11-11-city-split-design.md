# Yangon / Mandalay Split — Design

Date: 2026-11-11
Status: Planner said "just implement"; the decisions marked **(my call)** were not reviewed by the planner.
Builds on: `2026-11-10-stock-in-transit-design.md`. Everything not mentioned stays as built.

## 1. Why

The planner wants the order demand forecast and the order plan worked out separately for Yangon and Mandalay.

## 2. What the planner decided

- **City rule for stock and past sales:** Mandalay = branches Mandalay, Taunggyi, Naypyitaw and SubDistributor-Upper. Every other branch is Yangon.
- **Forecast by city** comes from the Sales Forecast file's Data sheet. The team copies the city forecast there with the same headers as the "SIT by weekly" sheet: a label row above the headers says "YGN IMS" / "MDY IMS" over each group, and the month headers are like "Oct'26".
- **Settings are per principal, the same for both cities** (holding days, MOQ, lead time, order cycle).
- The forecast playback was accepted: each month column belongs to the nearest label to its left; "… IMS Total" and "Total IMS" columns are ignored; a file without both city groups is rejected; if the combined "2026 Oct IMS" columns are still there they only serve as a check.

## 3. Inputs by city

- **Data sheet:** month headers matching `<month>'<yy>` (e.g. "Oct'26", "Sept'27") belong to the city of the nearest text label to their left in the rows above the header row: a label containing "YGN" or "Yangon" → Yangon, "MDY" or "Mandalay" → Mandalay; any other label (e.g. "Total IMS") → the column is ignored. Same window rules as the combined forecast, per city: at least one of the 3 window months must have a column (else rejected at upload), a missing window month gives a warning, the same month twice in a city is rejected. Negative values are 0 with a warning, non-numeric 0 with a warning.
  - The combined "2026 Oct IMS" columns become optional when both city groups exist. When present, for each SKU and window month, if |Yangon + Mandalay − combined| > 0.5 carton, one warning per SKU names the month **(my call: 0.5 carton tolerance, window months only)**.
  - A Data sheet with neither city group parses as before (combined only); the **upload** is rejected with "Sales Forecast file: the Data sheet has no Yangon and Mandalay forecast columns (headers under 'YGN IMS' and 'MDY IMS', like \"Oct'26\")." A file with only one of the two groups is rejected naming the missing city.
- **Actual Sales file:** `BranchName` with the city rule ("Nay Pyi Taw" is Naypyitaw; matching ignores case and spaces). **(my call)** A file without `BranchName` counts all sales as Yangon, with a warning.
- **PG Expiry Check:** `BranchName` with the city rule. **(my call)** No `BranchName` column → all Yangon, with a warning.
- **PDG Stock List:** `WH B` ("Mandalay" → Mandalay, anything else → Yangon). **(my call)** No `WH B` column → all Yangon, with a warning.
- **Stock in Transit file:** each arrival column belongs to the city of the nearest text label to its left in the rows above the header ("YGN"/"Yangon" → Yangon, "MDY"/"Mandalay" → Mandalay). **(my call)** No label → Yangon.
- The SKU's combined figures (sellable, non-sellable, SIT, arrivals, forecast) stay as the sums, so older code paths and the combined export columns keep working.

## 4. The calculation

- **One plan row per SKU per city (my call).** Each row is planned exactly as a SKU is today, from that city's actual sales, forecast, sellable stock and SIT arrivals, with the principal's settings. Avg sales, buffer, target, order, order plan, run-out flag, zero-forecast flag and status are all per city.
- **MOQ applies to each city's order on its own (my call).** The planner doesn't know whether the cities get separate purchase orders; per-city orders are what the plan shows, so the MOQ check is applied where the order is made.
- **Which rows (my call):** a SKU gets a Mandalay row only when Mandalay has something: a valid sales value (actual or forecast above 0), stock (sellable or non-sellable not 0) or SIT. Same for Yangon. A SKU with nothing in either city keeps a Yangon row, so every SKU still appears.
- **Older runs** (saved before the split) have no city data: they plan as one combined row per SKU exactly as before, with City shown as "—". Recalculate keeps them combined.

## 5. Results, storage, screens, export

- `SkuResult.city`: "YGN" / "MDY", or null for combined rows of older runs.
- Count cards, statuses and filters count rows (SKU × city). The run's SKU count (History) stays the number of distinct SKUs.
- **Plan page:** a **City** column after SAP Code ("Yangon" / "Mandalay"), a **City** filter (All cities / Yangon / Mandalay), and the row key is SKU + city. The SKU detail heading shows the city.
- **Principal summary:** totals cover both cities; "SKUs" counts distinct SKUs; the expanded purchase-order lines show the city **(my call)**.
- **Excel export:** a City column after SAP Code in SKU Plan, 12-Month Plan, Order Plan and Order Dates.
- **Warnings:** the run-out flag text starts with the city ("Mandalay: runs out about …").
- **Database:** no schema change (the city lives in the stored JSON).

## 6. Non-goals

- Separate settings per city; separate purchase orders; moving stock between cities.
- Splitting the MTD sale by city (it isn't used in the calculation).
