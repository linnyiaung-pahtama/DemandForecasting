"""HTTP API: wires parsing, planning and storage to FastAPI routes."""
import json
from datetime import date

from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import ValidationError

from app.commits import apply_commits, remove_commits
from app.holding import drop_monthly_order_plan, forecast_window, plan_all, plan_date_bounds, validate_plan_date
from app.export import XLSX_MEDIA_TYPE, build_export
from app.models import (DEFAULT_ORDER_CYCLE_WEEKS, ActualSales, Commit, InputFileError, InspectResponse, ParsedInput,
                        RunListItem,
                        RunRecord, SettingsLogEntry, SkuOption, StockResult, SupplierSettings,
                        SupplierSettingView, SupplierSummary)
from app.parsing import drop_unused_warnings, parse_input
from app.repository import Repository
from app.sales import actual_cartons, parse_sales
from app.sit import SIT_NAME, apply_sit, parse_sit
from app.stock import PDG_NAME, PG_NAME, apply_stock, parse_pdg, parse_pg, stock_date_warnings
from app.summary import summarize_suppliers

MIN_HOLDING, MAX_HOLDING = 15, 720  # days (half a month to 24 months)
MAX_LEAD_TIME_DAYS = 365
MIN_ORDER_CYCLE, MAX_ORDER_CYCLE = 1, 52  # weeks


def _parse_uploads(data_file: UploadFile, sales_file: UploadFile, pg_file: UploadFile,
                   pdg_file: UploadFile, sit_file: UploadFile) -> tuple[ParsedInput, ActualSales, StockResult]:
    """Parse the five uploads in order; the first unusable file is reported under its own name."""
    try:
        parsed = parse_input(data_file.file.read())
    except InputFileError as exc:
        raise HTTPException(status_code=400, detail=f"Sales Forecast file: {exc}") from exc
    if any(s.cities is None for s in parsed.skus):
        raise HTTPException(status_code=400, detail=(
            "Sales Forecast file: the Data sheet has no Yangon and Mandalay forecast columns "
            "(headers like \"Oct'26\" under 'YGN IMS' and 'MDY IMS' labels)."))
    try:
        actual = actual_cartons(parse_sales(sales_file.file.read()), parsed)
    except InputFileError as exc:
        raise HTTPException(status_code=400, detail=f"Actual Sales file: {exc}") from exc
    try:
        pg = parse_pg(pg_file.file.read())
    except InputFileError as exc:
        raise HTTPException(status_code=400, detail=f"{PG_NAME}: {exc}") from exc
    try:
        pdg = parse_pdg(pdg_file.file.read())
    except InputFileError as exc:
        raise HTTPException(status_code=400, detail=f"{PDG_NAME}: {exc}") from exc
    try:
        sit = parse_sit(sit_file.file.read())
    except InputFileError as exc:
        raise HTTPException(status_code=400, detail=f"{SIT_NAME}: {exc}") from exc
    parsed, stock = apply_stock(parsed, pg, pdg)
    parsed, sit_summary, sit_warnings = apply_sit(parsed, sit)
    return parsed, actual, stock.model_copy(update={"sit": sit_summary, "sit_warnings": sit_warnings})


def _parse_plan_date(text: str | None) -> date | None:
    if text is None or not text.strip():
        return None
    try:
        return date.fromisoformat(text.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Plan date '{text}' is not a valid date (use YYYY-MM-DD).") from exc


def _parse_commits(text: str | None) -> list[Commit]:
    """The commits form field: a JSON list of commit objects; blank means none. ValueError when unreadable."""
    if text is None or not text.strip():
        return []
    try:
        items = json.loads(text)
        if not isinstance(items, list):
            raise ValueError
        return [Commit.model_validate(item) for item in items]
    except (ValueError, ValidationError):
        raise ValueError("Commits could not be read: each needs a SAP code, cartons, an arrival week (its Monday, "
                         "YYYY-MM-DD) and a region (YGN or MDY).") from None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_whole(value: Any) -> bool:
    return _is_number(value) and float(value).is_integer()


def _parse_settings(items: list[Any]) -> list[SupplierSettings]:
    """Validate the raw PUT body so every bad value is reported with its supplier's name."""
    settings: list[SupplierSettings] = []
    for raw in items:
        if (not isinstance(raw, dict) or not isinstance(raw.get("supplier"), str)
                or any(key not in raw for key in ("holding_days", "moq", "lead_time_days", "order_cycle_weeks"))):
            raise HTTPException(
                status_code=422,
                detail="Each setting needs a supplier name and holding_days, moq, lead_time_days "
                       "and order_cycle_weeks values.")
        name, holding, moq, lead = raw["supplier"], raw["holding_days"], raw["moq"], raw["lead_time_days"]
        cycle = raw["order_cycle_weeks"]
        if holding is not None and not (_is_whole(holding) and MIN_HOLDING <= holding <= MAX_HOLDING):
            raise HTTPException(
                status_code=422,
                detail=f"Principal '{name}': holding must be a whole number of days from {MIN_HOLDING} to "
                       f"{MAX_HOLDING}, or blank.")
        if not (_is_whole(moq) and moq >= 0):
            raise HTTPException(
                status_code=422, detail=f"Principal '{name}': MOQ must be a whole number of cartons, 0 or more.")
        if lead is not None and not (_is_whole(lead) and 0 <= lead <= MAX_LEAD_TIME_DAYS):
            raise HTTPException(
                status_code=422,
                detail=f"Principal '{name}': lead time must be a whole number of days from 0 to "
                       f"{MAX_LEAD_TIME_DAYS}, or blank.")
        if not (_is_whole(cycle) and MIN_ORDER_CYCLE <= cycle <= MAX_ORDER_CYCLE):
            raise HTTPException(
                status_code=422,
                detail=f"Principal '{name}': order cycle must be a whole number of weeks from "
                       f"{MIN_ORDER_CYCLE} to {MAX_ORDER_CYCLE}.")
        settings.append(SupplierSettings(supplier=name, holding_days=None if holding is None else float(holding),
                                         moq=float(moq),
                                         lead_time_days=None if lead is None else int(lead),
                                         order_cycle_weeks=int(cycle)))
    return settings


def create_app(database_url: str | None = None, schema: str | None = None) -> FastAPI:
    """App factory. Start the server with: uvicorn app.main:create_app --factory --app-dir backend
    The database is DATABASE_URL (backend/.env) unless given; `schema` is for the tests."""
    repo = Repository(database_url, schema)
    app = FastAPI(title="Order Plan Tool")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    def get_run_or_404(run_id: int) -> RunRecord:
        run = repo.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
        return run.model_copy(update={"parsed": drop_unused_warnings(run.parsed),
                                      "result": drop_monthly_order_plan(run.result)})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/inspect", response_model=InspectResponse)
    def inspect(data_file: UploadFile = File(...), sales_file: UploadFile = File(...),
                pg_file: UploadFile = File(...), pdg_file: UploadFile = File(...),
                sit_file: UploadFile = File(...)) -> InspectResponse:
        parsed, actual, stock = _parse_uploads(data_file, sales_file, pg_file, pdg_file, sit_file)
        min_date, max_date = plan_date_bounds(parsed)
        return InspectResponse(
            file_name=data_file.filename or "", sales_file_name=sales_file.filename or "",
            pg_file_name=pg_file.filename or "", pdg_file_name=pdg_file.filename or "",
            sit_file_name=sit_file.filename or "", stock=stock,
            sku_count=len(parsed.skus), supplier_count=len({s.supplier for s in parsed.skus}),
            forecast_months=parsed.forecast_months, actual_months=actual.months,
            forecast_window=forecast_window(parsed),
            skus_with_sales=actual.skus_with_sales, mtd_label=parsed.mtd_label,
            mtd_end=parsed.mtd_end, default_plan_date=parsed.default_plan_date,
            min_plan_date=min_date, max_plan_date=max_date,
            warnings=(parsed.warnings + actual.warnings + stock.warnings
                      + stock_date_warnings(stock, parsed.default_plan_date) + stock.sit_warnings),
            skus=[SkuOption(sap_code=s.sap_code, description=s.description, supplier=s.supplier)
                  for s in parsed.skus])

    @app.post("/api/runs", response_model=RunRecord)
    def create_run(data_file: UploadFile = File(...), sales_file: UploadFile = File(...),
                   pg_file: UploadFile = File(...), pdg_file: UploadFile = File(...),
                   sit_file: UploadFile = File(...), plan_date: str | None = Form(None),
                   commits: str | None = Form(None)) -> RunRecord:
        parsed, actual, stock = _parse_uploads(data_file, sales_file, pg_file, pdg_file, sit_file)
        chosen = _parse_plan_date(plan_date) or parsed.default_plan_date
        try:
            validate_plan_date(parsed, chosen)
            # commits: a JSON list of {sap_code, cartons, arrival_week (its Monday), region}, entered on New plan
            parsed = apply_commits(parsed, _parse_commits(commits), chosen)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = plan_all(parsed, actual, repo.get_settings(), chosen)
        stock.warnings = stock.warnings + stock_date_warnings(stock, chosen)
        run_id = repo.create_run(data_file.filename or "", sales_file.filename or "",
                                 pg_file.filename or "", pdg_file.filename or "", sit_file.filename or "",
                                 parsed, actual, stock, result)
        return get_run_or_404(run_id)

    @app.get("/api/runs", response_model=list[RunListItem])
    def list_runs() -> list[RunListItem]:
        return repo.list_runs()

    @app.get("/api/runs/{run_id}", response_model=RunRecord)
    def get_run(run_id: int) -> RunRecord:
        return get_run_or_404(run_id)

    @app.post("/api/runs/{run_id}/recalculate", response_model=RunRecord)
    def recalculate(run_id: int) -> RunRecord:
        run = get_run_or_404(run_id)
        result = plan_all(run.parsed, run.actual, repo.get_settings(), run.result.plan_date)
        repo.update_run_result(run_id, result)
        return get_run_or_404(run_id)

    @app.put("/api/runs/{run_id}/commits", response_model=RunRecord)
    def replace_commits(run_id: int, items: list[Any]) -> RunRecord:
        """Replace a saved plan's commits and recalculate it in place with the current settings."""
        run = get_run_or_404(run_id)
        try:
            commits = [Commit.model_validate(item) for item in items]
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=(
                "Commits could not be read: each needs a SAP code, cartons, an arrival week (its Monday, "
                "YYYY-MM-DD) and a region (YGN or MDY).")) from exc
        stored = repo.get_run(run_id)   # as saved (get_run_or_404 drops unused warnings for display)
        plan_date = run.result.plan_date
        try:
            parsed = apply_commits(remove_commits(stored.parsed), commits, plan_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = plan_all(parsed, stored.actual, repo.get_settings(), plan_date)
        repo.update_run_inputs(run_id, parsed, result)
        return get_run_or_404(run_id)

    @app.get("/api/runs/{run_id}/suppliers", response_model=list[SupplierSummary])
    def run_suppliers(run_id: int) -> list[SupplierSummary]:
        return summarize_suppliers(get_run_or_404(run_id).result)

    @app.get("/api/runs/{run_id}/export")
    def export_run(run_id: int) -> Response:
        run = get_run_or_404(run_id)
        content = build_export(run)
        filename = f"order-plan-{run.plan_date.isoformat()}-run{run.id}.xlsx"
        return Response(content=content, media_type=XLSX_MEDIA_TYPE,
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    def settings_views() -> list[SupplierSettingView]:
        """Every supplier in the latest run or the stored settings; one with no stored row shows
        holding not set, MOQ 0, no lead time and an order cycle of 4 weeks."""
        stored = repo.get_settings()
        counts: dict[str, int] = {}
        latest = repo.latest_run_id()
        if latest is not None:
            codes: dict[str, set[str]] = {}
            for sku in get_run_or_404(latest).result.skus:   # a SKU has a row per city; count it once
                codes.setdefault(sku.supplier, set()).add(sku.sap_code)
            counts = {supplier: len(c) for supplier, c in codes.items()}
        views = []
        for name in sorted(set(counts) | set(stored)):
            s = stored.get(name)
            views.append(SupplierSettingView(
                supplier=name, holding_days=s.holding_days if s else None, moq=s.moq if s else 0,
                lead_time_days=s.lead_time_days if s else None,
                order_cycle_weeks=(s.order_cycle_weeks or DEFAULT_ORDER_CYCLE_WEEKS) if s else DEFAULT_ORDER_CYCLE_WEEKS,
                sku_count=counts.get(name, 0)))
        return views

    @app.get("/api/settings", response_model=list[SupplierSettingView])
    def get_settings() -> list[SupplierSettingView]:
        return settings_views()

    @app.put("/api/settings", response_model=list[SupplierSettingView])
    def put_settings(items: list[Any]) -> list[SupplierSettingView]:
        repo.save_settings(_parse_settings(items))
        return settings_views()

    @app.get("/api/settings/log", response_model=list[SettingsLogEntry])
    def settings_log() -> list[SettingsLogEntry]:
        return repo.get_settings_log()

    return app

