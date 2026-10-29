# MOQ and Lead Time as Supplier Settings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move MOQ and lead time from per-SKU Data sheet columns to per-supplier settings next to Holding. Pre-fill lead times once from the latest saved plan, and log every change.

**Architecture:**
- A single `SupplierSettings` model (holding, MOQ, lead time) replaces `SupplierHolding` in storage, the settings API and `HoldingPlan.settings_used`.
- `plan_sku` gets MOQ and lead time as parameters and never reads them from `SkuInput`. `plan_all` takes `dict[str, SupplierSettings]`.
- SQLite goes to schema v4 with an additive migration. One transaction adds the columns and runs the one-time lead-time pre-fill from the latest run's stored parsed input.
- The frontend Settings page edits all three values. Other screens show the values each plan was calculated with.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, sqlite3, pytest; React 19 + TypeScript, Vite 6, vitest.

**Spec:** `docs/superpowers/specs/2026-10-29-supplier-moq-lead-time-design.md`. Read it with `2026-10-23-holding-based-order-plan-design.md` (v2) and `2026-10-28-stock-files-design.md`.

## Global Constraints

- **MOQ rule:** applies to each SKU on its own. If required > 0 and required < the supplier's MOQ, the order is the supplier's MOQ (`moq_applied` = true). Required 0 gives order 0. MOQ 0 means no minimum.
- **Defaults:** MOQ 0. Lead time blank (`None`) means "not set": no next calculation date, and it does not block the order or change the status. Holding is still the only setting that blocks a supplier.
- **Validation:**
  - Holding: 0.5–24 or blank, unchanged.
  - MOQ: a whole number ≥ 0. Blank is not allowed.
  - Lead time: a whole number 0–365, or blank.
- **422 texts:**
  - `f"Supplier '{name}': MOQ must be a whole number of cartons, 0 or more."`
  - `f"Supplier '{name}': lead time must be a whole number of days from 0 to 365, or blank."`
  - The holding text is unchanged.
- **Data sheet:** `MOQ` and `Lead Time` are no longer required. If either is present, add one warning (`sap_code=None`, `column=None`): `"MOQ and Lead Time columns in the Data sheet are ignored; they come from Supplier settings."`
- **Log `field` values:** `"holding_months"`, `"moq"`, `"lead_time_days"`. Existing log rows read as `"holding_months"`.
- **Schema version 4.** The migration is additive and in place. Never recreate or rename the database. The upgrade does **not** recalculate any stored run.
- **Never touch `backend/data/orderplan.db`, `orderplan.pre-v3-backup.db` or `orderplan.v1-backup*.db`.** Tests use `tmp_path` or the `ORDERPLAN_DB` set in `conftest.py`. The end-to-end check uses a copy in the scratchpad.
- **Stop only processes you started, by PID. Never use `taskkill /IM`.** The planner's app is running on 8000/5173: leave it alone.
- **Do not commit `requests/` or `.superpowers/`.** Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Windows/PowerShell.**
  - Backend: from `backend/`, `.venv/Scripts/python -m pytest -q`.
  - Frontend: `npm --prefix frontend test`, `npm --prefix frontend run build`, `npm --prefix frontend run lint`.

## Review Focus

1. **A supplier in a new Data file with no settings row yet** must plan with holding blocked, MOQ 0 and no next calc date, and must not crash. Covered by Task 2 `test_plan_all_supplier_without_settings`.
2. **The planner types "8,000" into the MOQ box.** Thousands separators must be accepted, and the value saved as 8000. Covered by Task 4 `validateMoq` tests.
3. **Clearing a lead time** must save null and log the change "14 → blank". Covered by Task 1 `test_save_settings_logs_each_changed_field`.
4. **A fractional or negative MOQ, or a boolean, sent to the API** must give a 422 naming the supplier, and nothing is saved. Covered by Task 3 `test_settings_validation_moq_and_lead`.
5. **A run saved before this change** (its `settings_used` has only holding) must open, summarise and export with MOQ/lead time shown as not recorded, and show the "Saved before…" note. Covered by Task 3 `test_old_run_settings_used_loads` and Task 5 `isLegacyRun` tests.

---

### Task 1: Settings storage, v4 migration and the lead-time pre-fill

**Files:**
- Modify: `backend/app/models.py`, `backend/app/db.py`, `backend/app/repository.py`
- Test: `backend/tests/test_repository.py`

**Interfaces:**
- Produces, in `models.py`:
  - `SupplierSettings` **replaces** `SupplierHolding`:
    ```python
    class SupplierSettings(BaseModel):
        supplier: str
        holding_months: float | None
        moq: float | None = None          # None only in runs saved before MOQ moved to settings
        lead_time_days: int | None = None
    ```
  - `HoldingPlan.settings_used: list[SupplierSettings]`. Old JSON with only holding still validates.
  - `SettingsLogEntry` gains `field: str`.
- Produces, in `repository.py`. These **replace** `get_holdings` and `save_holdings`:
  - `get_settings() -> dict[str, SupplierSettings]`: every stored row. `moq` is always a number here.
  - `save_settings(items: list[SupplierSettings]) -> list[SettingsLogEntry]`
    - It upserts each item.
    - It writes one log row per field whose value changed (`field`, `old_value`, `new_value`).
    - A supplier with no stored row counts as holding None, MOQ 0, lead time None.
    - It returns the new log entries.
- **DB:**
  - `SCHEMA_VERSION = 4`. In `SCHEMA`:
    - `supplier_settings` gains `moq REAL NOT NULL DEFAULT 0` and `lead_time_days INTEGER NULL`;
    - `settings_log` gains `field TEXT NOT NULL DEFAULT 'holding_months'`.
  - `init_schema` adds any of these three columns that are missing, with `ALTER TABLE … ADD COLUMN` (check `PRAGMA table_info` first), as v3 does.
  - **Pre-fill:** if `supplier_settings.lead_time_days` was missing (an existing pre-v4 database is being upgraded), run it in the **same transaction** as the column additions, using explicit `BEGIN`/`COMMIT` with rollback on error, so an interrupted upgrade leaves the database untouched and retries next start.
    1. Read the latest run (`MAX(id)`) `parsed_json` with plain `json`. `db.py` does not import the models.
    2. Group its SKUs by `supplier`. A supplier whose SKUs all have the same non-null `lead_time_days` gets that value.
    3. Upsert: an existing row gets `lead_time_days` set when there is a uniform value. **Every** supplier in that run with no row gets a new row with holding NULL, MOQ 0, and the lead time or NULL. Set `updated_at` to now.
    4. Log one `settings_log` row per lead time actually set: `field='lead_time_days'`, `old_value` NULL, `new_value` the days, `changed_at` now. Rows created with a NULL lead time are not logged.
  - With no runs, nothing is pre-filled. A fresh database creates the columns via `SCHEMA`, so the pre-fill never runs.
  - The v1 backup logic is unchanged. A v2 database (user_version 2, no `reorder_days`) goes through v3 and v4 in one start.

- [ ] **Step 1: Write the failing tests** in `test_repository.py`.
  - `test_v3_database_is_upgraded_to_v4_with_lead_times_prefilled`:
    - Build a v3 database literally. Copy the current `db.py` `SCHEMA` text as it is before your change, and set `user_version = 3`.
    - `supplier_settings` rows: `("A", 2.0)` and `("D", 3.0)`.
    - One `settings_log` row (A, None → 2.0).
    - Two runs. The latest run's `parsed_json` has SKUs: A with lead 14 and 14; B with 7 and None; C with 21. Build it from current models with `model_dump_json()`.
    - Open with `Repository(path)`, then assert:
    ```python
    s = repo.get_settings()
    assert (s["A"].holding_months, s["A"].moq, s["A"].lead_time_days) == (2.0, 0, 14)
    assert s["B"].lead_time_days is None and s["D"].lead_time_days is None and s["D"].moq == 0
    assert (s["C"].holding_months, s["C"].moq, s["C"].lead_time_days) == (None, 0, 21)
    log = repo.get_settings_log()
    assert [(e.supplier, e.field, e.old_value, e.new_value) for e in log[:2]] in (
        [("A", "lead_time_days", None, 14), ("C", "lead_time_days", None, 21)],
        [("C", "lead_time_days", None, 21), ("A", "lead_time_days", None, 14)])
    assert log[-1].field == "holding_months"
    # user_version is 4; the runs table rows (all columns) are byte-identical to before;
    # a second Repository(path) adds no log rows and changes no settings
    ```
  - `test_save_settings_logs_each_changed_field`:
    - Save A as (2, 0, 14). Then save A as (2, 8000, None).
    - The second save returns exactly two entries, `("moq", 0, 8000)` and `("lead_time_days", 14, None)`.
    - Saving A unchanged again returns `[]`.
  - `test_fresh_database_has_no_prefill`: a new database has `get_settings() == {}` and an empty log.
  - Update the existing tests that call `get_holdings` / `save_holdings`, including `test_v2_database_is_migrated_in_place`, which now ends at user_version 4.

- [ ] **Step 2: Run the tests and check they fail.**
Run from `backend/`: `.venv/Scripts/python -m pytest tests/test_repository.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the models, `db.py` and repository changes.**
`main.py` and `holding.py` still call `get_holdings` and use `SupplierHolding`. Keep them importable by updating those call sites minimally:
- `repo.get_holdings()` becomes `{k: v.holding_months for k, v in repo.get_settings().items() if v.holding_months is not None}`.
- `save_holdings` becomes `save_settings`, filling MOQ and lead time from the stored row.
Task 2 and Task 3 replace these properly.

- [ ] **Step 4: Run the full backend suite and check it passes.**
Run from `backend/`: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit.** `feat: supplier MOQ and lead time storage; v4 migration with one-time lead-time pre-fill`

---

### Task 2: Planning uses supplier MOQ and lead time; Data sheet columns optional

**Files:**
- Modify: `backend/app/parsing.py`, `backend/app/holding.py`, `backend/app/main.py` (the `plan_all` call sites only)
- Test: `backend/tests/test_holding.py`, `backend/tests/test_parsing.py`, plus the direct-call tests in `test_summary.py`, `test_export.py` and `test_repository.py` that call `plan_all`/`plan_sku`.

**Interfaces:**
- Consumes: `SupplierSettings`, `Repository.get_settings()` (Task 1).
- Produces:
  - `plan_sku(sku: SkuInput, actuals: dict[str, float], actual_months: list[str], forecast_months: list[str], holding_months: float | None, plan_date: date, moq: float = 0.0, lead_time_days: int | None = None) -> SkuResult`
    - It uses `moq` and `lead_time_days` and never reads `sku.moq` / `sku.lead_time_days`.
    - `SkuResult.moq` and `SkuResult.lead_time_days` are the values used.
  - `plan_all(parsed: ParsedInput, actual: ActualSales, settings: dict[str, SupplierSettings], plan_date: date) -> HoldingPlan`
    - A supplier missing from `settings` plans with holding None, MOQ 0 and lead time None.
    - `settings_used` has one `SupplierSettings` per supplier with the values used. `moq` is always a number here.
    - `blocked_suppliers` are those with holding None.
  - `main.py` passes `repo.get_settings()` to `plan_all` at run creation and at recalculate.
- **`parse_input`:**
  - `REQUIRED_COLUMNS` loses `MOQ` and `Lead Time`.
  - Add `SUPPLIER_SETTING_COLUMNS = ["MOQ", "Lead Time"]`. If either is present, add the one warning from Global Constraints; the values are never read.
  - `SkuInput.moq` is `0.0` and `lead_time_days` is `None`. The fields stay for old stored runs.
  - The two lead-time warnings ("negative lead time treated as missing", "missing or non-numeric lead time") are removed.

- [ ] **Step 1: Write the failing tests.**
  - In `test_holding.py`:
    - `test_supplier_moq_raises_each_sku`: `plan_sku(..., holding_months=3, ..., moq=150)` on the worked example (required 100) gives `order_qty == 150` and `moq_applied`.
    - With `moq=0`, it gives 100.
    - With required 0 and `moq=150`, it gives 0.
    - `test_plan_sku_ignores_moq_and_lead_on_sku_input`: `SkuInput(moq=999, lead_time_days=5)`, called with `moq=0, lead_time_days=None`, gives no MOQ applied and `next_calc_date is None`.
    - `test_blank_lead_time_does_not_block`: status is `TO_ORDER` and `next_calc_date is None`.
    - `test_plan_all_supplier_without_settings`: a supplier absent from `settings` gives status `HOLDING_NOT_SET`, `settings_used` entry `(holding None, moq 0, lead None)`, and `next_calc_date is None`.
    - `test_plan_all_uses_supplier_settings`: two SKUs of supplier S with `settings={"S": SupplierSettings(supplier="S", holding_months=3, moq=150, lead_time_days=61)}`. Both get MOQ 150 and lead 61, and `next_calc_date == plan_date + 61 days`.
  - In `test_parsing.py`:
    - `test_moq_and_lead_columns_are_optional_and_ignored`. Without the columns: no warning, `moq == 0`, `lead_time_days is None`. With them: exactly one warning with the text above, and the values are not read.
    - Remove or update the tests that assert lead-time warnings or parsed MOQ/lead values.
  - **Existing direct-call tests that relied on Data-sheet MOQ/lead** (fixture `plan_all` tests in `test_holding.py`, `test_summary.py`, `test_export.py`, `test_repository.py`): pass settings that reproduce the old values. In the fixture every supplier's lead time is uniform; read it from the Data sheet in the test with openpyxl, or use the per-supplier list in the spec's section 1. Their expected numbers must not change, except where a test asserted the 8,000 MOQ on 4201111007, which now needs `moq=8000` on Constellation or an updated expectation, stated in the report.

- [ ] **Step 2: Run the tests and check they fail.**
Run from `backend/`: `.venv/Scripts/python -m pytest tests/test_holding.py tests/test_parsing.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement `parse_input`, `plan_sku`, `plan_all` and the `main.py` call sites.**

- [ ] **Step 4: Run the backend suite.**
Run from `backend/`: `.venv/Scripts/python -m pytest -q`
Expected:
- Everything passes except tests in `test_api.py` / `test_export.py` that post files and expect a next calc date or MOQ from the Data sheet. With no lead times set through the API they now get `None`.
- List those tests in the report; Task 3 fixes them by setting lead times through `PUT /api/settings`. Every other test must pass.

- [ ] **Step 5: Commit.** `feat: plan with supplier MOQ and lead time; Data sheet MOQ/Lead Time optional`

---

### Task 3: Settings API, supplier summary and export

**Files:**
- Modify: `backend/app/main.py`, `backend/app/models.py`, `backend/app/summary.py`, `backend/app/export.py`
- Test: `backend/tests/test_api.py`, `backend/tests/test_summary.py`, `backend/tests/test_export.py`

**Interfaces:**
- Consumes: `SupplierSettings`, `get_settings`, `save_settings`, `plan_all` (Tasks 1–2).
- **Models:**
  - `SupplierSettingView`: `supplier: str`, `holding_months: float | None`, `moq: float`, `lead_time_days: int | None`, `sku_count: int`. This replaces `max_lead_time_days`.
  - `SupplierSummary`: replaces `max_lead_time_days` with `moq: float | None` and `lead_time_days: int | None`, both taken from `settings_used`. They are None for runs saved before this change.
- **API:**
  - `GET /api/settings`:
    - It returns a row for every supplier in the latest run or stored settings, sorted by name.
    - A supplier with no stored row shows holding None, MOQ 0 and lead None.
    - `sku_count` comes from the latest run.
  - `PUT /api/settings` body: a list of `{supplier, holding_months, moq, lead_time_days}`. All four keys are required.
    - A missing key or a non-object gives 422 `"Each setting needs a supplier name and holding_months, moq and lead_time_days values."`
    - Validate holding (existing rule), then MOQ, then lead time, with the exact 422 texts in Global Constraints.
    - Whole numbers: an `int`, or a `float` with `.is_integer()`. `bool` is rejected.
    - Validation is all-or-nothing: nothing is saved if any item fails.
    - Save via `save_settings`, then return the new `GET` view.
  - `GET /api/settings/log`: entries include `field`.
- **Summary:** each supplier's `moq` and `lead_time_days` are taken from its `settings_used` entry.
- **Export:** the "Settings Used" sheet columns are `Supplier`, `Holding (months)`, `MOQ`, `Lead Time (days)`, blank when None.

- [ ] **Step 1: Write the failing tests.**
  - In `test_api.py`:
    - `test_settings_round_trip`: after a run, PUT `[{"supplier":"CFC","holding_months":3,"moq":200,"lead_time_days":7}]`. GET shows those values, and the other suppliers show `moq` 0 and lead `None`. The log has three CFC entries with fields `holding_months`, `moq`, `lead_time_days`.
    - `test_settings_validation_moq_and_lead`:
      - These give a 422 with the MOQ text for supplier 'Acme': `moq` of `-1`, `1.5`, `True`, `"x"` and `None`.
      - These give a 422 with the lead text: `lead_time_days` of `-1`, `366`, `2.5` and `True`.
      - `moq` `8000.0` and `lead_time_days` `None` are accepted.
      - A failing batch saves nothing.
    - `test_settings_missing_keys_returns_422`.
    - Update `test_set_holding_recalculates_real_sku`: PUT CFC `holding_months 3, moq 0, lead_time_days 7`. Its existing assertions must still hold, including `next_calc_date == "2026-10-19"` and `order_qty == 110`.
    - Update every other settings call to send all four keys.
    - Fix the API-posting tests listed in Task 2's report by setting the needed lead times via PUT.
  - In `test_summary.py`:
    - The summary has `moq`/`lead_time_days` from `settings_used`.
    - `test_old_run_settings_used_loads`: a `HoldingPlan` validated from JSON whose `settings_used` items have only `supplier` and `holding_months` gives a summary with `moq is None` and `lead_time_days is None`.
  - In `test_export.py`: the Settings Used header is `["Supplier", "Holding (months)", "MOQ", "Lead Time (days)"]`, the values match, and the cells are blank for an old run.

- [ ] **Step 2: Run the tests and check they fail.**
Run from `backend/`: `.venv/Scripts/python -m pytest tests/test_api.py tests/test_summary.py tests/test_export.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the API, summary and export changes.** Remove the Task 1 stop-gap shims.

- [ ] **Step 4: Run the full backend suite and check it passes.**
Run from `backend/`: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit.** `feat: settings API for holding, MOQ and lead time; summary and export show them`

---

### Task 4: Supplier settings page

**Files:**
- Modify: `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/lib/settings.ts`, `frontend/src/lib/settings.test.ts`, `frontend/src/pages/SettingsPage.tsx`

**Interfaces:**
- Consumes: the API shapes from Task 3.
- **`types.ts`:**
  - `SupplierSettings { supplier: string; holding_months: number | null; moq: number | null; lead_time_days: number | null }` replaces `SupplierHolding`, including in `HoldingPlan.settings_used`.
  - `SettingsLogEntry.field: 'holding_months' | 'moq' | 'lead_time_days'`
  - `SupplierSettingView` has `moq: number` and `lead_time_days: number | null` instead of `max_lead_time_days`.
  - `SupplierSummary` has `moq: number | null` and `lead_time_days: number | null` instead of `max_lead_time_days`.
- **`api.ts`:** `saveSettings(items: SupplierSettings[])`.
- **`lib/settings.ts`:**
  - `validateMoq(text: string): { value: number | null; error: string | null }`
    - Blank gives the error. Commas and spaces are stripped first (`"8,000"` → 8000). The value must be a whole number ≥ 0.
    - Error text: `'MOQ must be a whole number of cartons, 0 or more.'`
  - `validateLeadTime(text: string): { value: number | null; error: string | null }`
    - Blank gives null with no error. Otherwise a whole number 0–365.
    - Error text: `'Lead time must be a whole number of days from 0 to 365, or blank.'`
  - `changedSettings(original: SupplierSettingView[], edited: Record<string, { holding_months: number | null; moq: number; lead_time_days: number | null }>): SupplierSettings[]` replaces `changedHoldings`. It returns the full row for any supplier with at least one field changed.
- **`SettingsPage`:**
  - Columns: Supplier, SKUs, Holding (months), MOQ (cartons), Lead time (days), Notes. All three middle inputs are text inputs with aria-labels `Holding months for {s}`, `MOQ for {s}` and `Lead time days for {s}`, with inline errors.
  - Notes:
    - Holding blank gives the existing "Holding not set — SKUs blocked" and row highlight.
    - Lead time blank gives a muted "Lead time not set — no next calculation date".
  - The intro text mentions that MOQ applies to each SKU of the supplier on its own.
  - Save is disabled while any field has an error.
  - Change log columns: Changed, Supplier, **Setting**, Old, New.
    - Setting labels: `Holding`, `MOQ`, `Lead time`.
    - Values: holding as today; MOQ via `fmtQty`; lead as `{n} days`; blank as `blank`.

- [ ] **Step 1: Write the failing tests** in `settings.test.ts`.
  - `validateMoq`: `'8,000'` → 8000; `' 0 '` → 0; `''`, `'-1'`, `'1.5'`, `'abc'` and `'1e3'` → the error.
  - `validateLeadTime`: `''` → null with no error; `'14'` → 14; `'366'`, `'-1'` and `'2.5'` → the error.
  - `changedSettings`: only changed suppliers, with full rows; a cleared lead time is included as `null`; suppliers not in `edited` are skipped.
  - Update the `view()` helper for the new `SupplierSettingView` shape.

- [ ] **Step 2: Run the tests and check they fail.**
Run: `npm --prefix frontend test`
Expected: FAIL on the new cases.

- [ ] **Step 3: Implement the types, API, settings lib and Settings page.**

- [ ] **Step 4: Run the tests, build and lint.**
Run: `npm --prefix frontend test`, then `npm --prefix frontend run build`, then `npm --prefix frontend run lint`
Expected: all pass.
`SupplierPage.tsx` may break on `max_lead_time_days`. If it does, make the minimal change to keep the build green (show `lead_time_days`); Task 5 finishes it.

- [ ] **Step 5: Commit.** `feat: edit holding, MOQ and lead time on the supplier settings page`

---

### Task 5: SKU detail, explanation, supplier summary and the old-run note

**Files:**
- Modify: `frontend/src/lib/format.ts`, `frontend/src/lib/format.test.ts`, `frontend/src/components/SkuDetail.tsx`, `frontend/src/pages/SupplierPage.tsx`, `frontend/src/pages/PlanPage.tsx`
- Test: `frontend/src/lib/format.test.ts`

**Interfaces:**
- Consumes: the types from Task 4.
- **`format.ts`:**
  - `isLegacyRun(plan: HoldingPlan): boolean` is true when any `settings_used` entry has `moq === null`.
  - In `orderExplanation`, a null `lead_time_days` gives the line `'Next calculation date: lead time not set'`. This replaces `'Next calculation date: no lead time'`.
- **`SkuDetail`:**
  - The MOQ fact reads `{fmtQty(moq)} (supplier)` when moq > 0, else `none`.
  - The Lead time fact reads `{n} days`, or `not set`.
- **`SupplierPage`:** MOQ and Lead time columns from `SupplierSummary.moq` / `lead_time_days`, showing `—` when null. These replace the max lead time column.
- **`PlanPage`:** when `isLegacyRun(run.result)`, show a muted note under the header: `Saved before MOQ and lead time moved to Supplier settings — Recalculate to use the current settings.`

- [ ] **Step 1: Write the failing tests** in `format.test.ts`.
  - `isLegacyRun`: true for a plan whose `settings_used` has `moq: null`; false when every entry has a number.
  - A null-lead SKU's explanation ends with `'Next calculation date: lead time not set'`.
  - Update the existing expectation that used `'no lead time'`.

- [ ] **Step 2: Run the tests and check they fail.**
Run: `npm --prefix frontend test`
Expected: FAIL on the new cases.

- [ ] **Step 3: Implement the changes.**

- [ ] **Step 4: Run the tests, build and lint, and check they pass.**

- [ ] **Step 5: Commit.** `feat: show supplier MOQ and lead time in SKU detail, summary and old-run note`

---

### Task 6: README and end-to-end check on a copy of the real database

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update `README.md`.**
  - The Data sheet no longer needs `MOQ` / `Lead Time`; the warning if they are present.
  - Supplier settings hold Holding, MOQ (each SKU on its own, default 0) and Lead time (blank = no next calc date).
  - The one-time lead-time pre-fill at upgrade, and that it is logged.
  - The upgrade does not recalculate saved plans, and the "Saved before…" note.
  - Copy the database before first start; name the v4 backup `orderplan.pre-v4-backup.db`.
  - Update the worked example's MOQ wording if it refers to a Data sheet MOQ.

- [ ] **Step 2: Run the end-to-end check in a scratch script.**
Use `TestClient(create_app(<copy>))`. Never use a server, and never the original database.
  1. Copy `backend/data/orderplan.db` to the scratchpad with `Copy-Item`. Reading and copying is the only allowed access.
  2. Record the latest run's `result_json` from the copy, using a read-only sqlite connection.
  3. Open the copy with the new code. Then check:
     - user_version is 4;
     - all 17 suppliers have a lead time equal to the uniform per-supplier lead time in that run's Data;
     - every supplier has MOQ 0;
     - 17 `lead_time_days` log rows;
     - the latest run's `result_json` is byte-identical;
     - `GET /api/runs/{id}` shows `settings_used` without MOQ, so the plan is a legacy run.
  4. `POST /api/runs/{id}/recalculate`. Compare with the recorded result:
     - every SKU's available, buffer, target, required, status and `next_calc_date` are identical;
     - `order_qty` is identical except 4201111007, which goes from 8,000 to its required quantity (6,167 in the current data) with `moq_applied` false;
     - `total` order qty drops by exactly 8,000 − required.
  5. Report the numbers.

- [ ] **Step 3: Run the full verification.**
Run: the backend suite, then `npm --prefix frontend test`, then `npm --prefix frontend run build`.
Expected: all green, and the real `backend/data/orderplan.db` size and modification time are unchanged (compare `Get-Item` before and after).

- [ ] **Step 4: Commit.** `docs: README for supplier MOQ and lead time`

- [ ] **Step 5: Controller-only steps (not the implementer).**
  - Browser check on the test servers against a copied database.
  - Then tell the planner: their running server still has the old code. Restarting it upgrades `backend/data/orderplan.db` to v4 and pre-fills lead times. Offer to copy it to `backend/data/orderplan.pre-v4-backup.db` first, and restart only when they say so.
