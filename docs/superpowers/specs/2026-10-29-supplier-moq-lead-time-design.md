# MOQ and Lead Time as Supplier Settings — Design

Date: 2026-10-29
Status: Draft for review
Builds on: `2026-10-23-holding-based-order-plan-design.md` (v2) and `2026-10-28-stock-files-design.md` (stock files). Everything not mentioned here stays as built.

## 1. Why this change

MOQ and Lead Time are per-SKU columns in the Data sheet today. The planner wants to maintain them per **supplier**, on the Supplier settings page next to Holding, and remove them from the Data sheet.
- **Lead time** is already the same for every SKU of a supplier in the current file (Constellation 14 days, Myanmar Vineyard Estate 30, and so on).
- **MOQ** is set on only one SKU today: 8,000 on Phwer Htwe, 4201111007.

This continues moving inputs out of the hand-maintained Data sheet. The planner also plans to feed most data from a database later (see the stock-files design, section 8).

## 2. What the planner decided

- **MOQ and Lead Time become supplier settings.** They are not in the Data sheet.
- **The MOQ default is 0** (no minimum).
- **A supplier's MOQ applies to each of its SKUs on its own.** Any SKU of that supplier whose order is above 0 and below the MOQ is raised to the MOQ. It is not a minimum on the supplier's total order.
  - The planner was told the consequence: with Constellation at 8,000, *every* Constellation SKU that needs an order is raised to 8,000, not only Phwer Htwe. For example, 4201111009 would go from 1,614 to 8,000.
- The planner agreed to these proposals:
  - **A blank lead time doesn't block an order.** The next calc date shows "—" with "lead time not set".
  - **Data sheet MOQ / Lead Time columns are ignored if present**, with one warning, the same way the stock columns are.
  - **Lead time is pre-filled once from the current data**; MOQ starts at 0.
  - **Changes are logged** in the existing change log.
  - **Saving recalculates** the latest plan.
  - **Recalculating any plan uses the current settings.**
  - **Validation:** MOQ is a whole number ≥ 0; lead time is a whole number from 0 to 365.

## 3. The calculation

Only where MOQ and lead time come from changes. Steps 1–7 of v2 section 6 are otherwise unchanged:
- **Step 5, MOQ check:** if required > 0 and required < the supplier's MOQ, the order is the supplier's MOQ (MOQ applied). If required = 0, the order is 0. MOQ 0 means no minimum.
- **Step 7, next calculation date** = plan date + the supplier's lead time.
  - If the supplier's lead time is not set, the date is not shown ("—"), and the SKU detail says "Next calculation date: lead time not set".
  - It doesn't block the order and doesn't change the status.
- **Holding is still the only setting that blocks** a supplier ("Holding not set").
- **Each SKU result stores the MOQ and lead time it was calculated with** (`SkuResult.moq`, `SkuResult.lead_time_days`, as now), so the export, SKU detail and supplier summary show the values used.
- **The run records the settings it used:** `HoldingPlan.settings_used` carries holding, MOQ and lead time per supplier.
- **Recalculate** (after a settings save, or the Recalculate button) re-plans from the stored parsed input with the **current** holding, MOQ and lead time.
  - This applies to plans saved before this change too: their MOQ / lead time from the old Data file is no longer used.

## 4. The Data sheet

- **No longer required:** `MOQ` and `Lead Time`.
- **Required columns become:** `SAP Code`, `By Principal`, `Description`, `Packing Size`, `Shelf Life month`, `SIT Ctns (pending order)`, the MTD column and the forecast columns.
- **If `MOQ` or `Lead Time` is present,** add one warning (no SAP code, no column): "MOQ and Lead Time columns in the Data sheet are ignored; they come from Supplier settings." The values are never read for planning.
- **These per-SKU lead-time warnings go away:** "missing or non-numeric lead time" and "negative lead time treated as missing".
- **Exception — the one-time pre-fill (section 6) reads lead times.** It uses the lead times kept in stored runs, not new uploads. A new upload's `Lead Time` column is ignored for planning but may be used by the pre-fill if no stored run exists: **builder's call**, see section 9.

## 5. Supplier settings page

- **Columns:** Supplier, SKUs, Holding (months), **MOQ (cartons)**, **Lead time (days)**. All three are editable.
  - The current read-only "max lead time" column is replaced by the editable Lead time.
- **Highlighting:**
  - Rows without holding stay highlighted: "Holding not set — SKUs blocked".
  - A row without a lead time shows a quieter note: "Lead time not set — no next calculation date".
- **Validation:** inline, per field, as Holding is validated today.
  - Holding: 0.5–24 or blank.
  - MOQ: a whole number ≥ 0. Blank is not allowed; 0 means no minimum.
  - Lead time: a whole number 0–365, or blank.
- **Save** sends only changed rows, all-or-nothing as today, then recalculates the latest plan.
- **Change log:** one entry per changed field, showing which setting changed. For example: "Constellation · MOQ · 0 → 8,000". Existing log entries are holding changes.
- **API:**
  - `GET /api/settings` returns, per supplier: `supplier`, `holding_months`, `moq`, `lead_time_days`, `sku_count`.
  - `PUT /api/settings` accepts a list of `{supplier, holding_months, moq, lead_time_days}`.
  - A 422 names the supplier and the field. For example: "Supplier 'Acme': MOQ must be a whole number of cartons, 0 or more."
  - `GET /api/settings/log` entries gain `field` (`holding_months` | `moq` | `lead_time_days`).

## 6. Storage and the one-time pre-fill

- **`supplier_settings` gains two columns:**
  - `moq REAL NOT NULL DEFAULT 0`, so existing suppliers get 0;
  - `lead_time_days INTEGER NULL`.
- **`settings_log` gains `field TEXT NOT NULL DEFAULT 'holding_months'`**, so existing entries read as holding changes.
- **Schema version 4.** Use an additive in-place migration, like v3: `ALTER TABLE … ADD COLUMN` only when missing. Never recreate or rename the database. The planner's real database (v3, 4 runs, 17 supplier settings) must keep every run and setting.
- **One-time lead-time pre-fill.** It runs as part of the v3 → v4 upgrade, and only then. For each supplier:
  1. Take its SKUs from the **latest stored run's** parsed input.
  2. If all of them have the same non-null `lead_time_days`, set the supplier's lead time to that value. Otherwise leave it blank.
  3. Each value set is logged as a lead-time change (blank → value), so the planner can see where it came from.
  - Suppliers that appear in the latest run but have no settings row get a row: holding blank, MOQ 0, lead time pre-filled.
  - In the planner's database this sets all 17 suppliers: 3, 7, 14, 21 or 30 days.
- **MOQ is not pre-filled** (planner's decision): every supplier starts at 0. The planner re-enters Constellation's 8,000 if wanted, knowing it applies to all Constellation SKUs.
- **The upgrade does not recalculate anything (builder's call, made in design).** Stored run results stay exactly as they were until the planner saves settings or clicks Recalculate.
  - A run saved before this change has `settings_used` entries without MOQ / lead time. Load them as MOQ None and lead time None, meaning "not recorded", not 0.
  - The Plan page shows a note on such a run: "Saved before MOQ and lead time moved to Supplier settings — Recalculate to use the current settings."
  - On such a run, the supplier summary shows "—" for MOQ and lead time.

## 7. Other screens

- **SKU detail:**
  - The MOQ fact reads "{n} (supplier)" or "none". The Lead time fact reads "{n} days" or "not set".
  - The "How this is worked out" MOQ and next-calc-date lines use the stored values. Add "Next calculation date: lead time not set" when it's blank.
- **Supplier summary:** shows each supplier's MOQ and lead time used. Today it shows a max lead time worked out from the SKUs.
- **Export:**
  - The "Settings Used" sheet gains MOQ and Lead Time columns.
  - The SKU Plan sheet's MOQ and Lead Time columns stay. They now hold the supplier values used.
- **Upload page:** no change apart from the new Data-sheet warning when the columns are present.
- **README:**
  - The Data sheet no longer needs MOQ / Lead Time.
  - Supplier settings now hold Holding, MOQ and Lead Time.
  - Describe the one-time pre-fill.

## 8. Non-goals

- **A minimum on the supplier's total order**, or order rounding to packs/pallets.
- **Per-SKU MOQ or lead time overrides.** Every SKU of a supplier shares its values.
- **Lead time changing the order quantity.** It still only sets the next calculation date (v2).
- **Pre-filling MOQ** from the Data sheet.

## 9. Left to the builder

- Model and module layout. Suggestion: a `SupplierSettings` model replacing `SupplierHolding` in `settings_used` and the settings API, plus a repository `get_settings()` returning all three values per supplier.
  - Old stored runs whose `settings_used` entries only have `holding_months` must still load: default MOQ 0, lead time None.
- How `plan_sku` receives MOQ and lead time: parameters, or overriding the `SkuInput` copy.
  - `SkuInput.moq` / `lead_time_days` may stay in the model for old stored runs, but planning must not read them.
- Whether the pre-fill may also use a new upload's `Lead Time` column when there is no stored run. A fresh database has no runs, so lead times would simply start blank.
- UI details.
- **Tests** must cover:
  - step 5 with a supplier MOQ, including MOQ 0 and required 0;
  - step 7 with a blank lead time;
  - the Data sheet with and without MOQ / Lead Time columns;
  - settings validation, including 422 messages that name the supplier and field;
  - per-field log entries;
  - the v3 → v4 migration on a hand-built v3 database: existing runs and settings kept, MOQ 0, lead times pre-filled from the latest run and logged, a second start changes nothing;
  - recalculation of an old run using the current settings.
- **End-to-end check** on a copy of the planner's real database, never the original, and the real workbook.
  - First confirm the upgraded copy's latest run is byte-for-byte unchanged and shows the "Saved before…" note. Then recalculate it.
  - With every supplier at holding 2, MOQ 0 and the pre-filled lead times, the plan must match today's except Phwer Htwe 4201111007: it loses its 8,000 MOQ, so its order drops from 8,000 to its required quantity.
  - Next calc dates must be unchanged.
