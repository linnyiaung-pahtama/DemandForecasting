"""HTTP API: wires parsing, planning and storage to FastAPI routes."""
from datetime import date
from pathlib import Path

from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app import config
from app.holding import forecast_window, plan_all, plan_date_bounds, validate_plan_date
from app.export import XLSX_MEDIA_TYPE, build_export
from app.models import (ActualSales, InputFileError, InspectResponse, ParsedInput, RunListItem,
                        RunRecord, SettingsLogEntry, StockResult, SupplierSettings,
                        SupplierSettingView, SupplierSummary)
from app.parsing import parse_input
from app.repository import Repository
from app.sales import actual_cartons, parse_sales
from app.stock import PDG_NAME, PG_NAME, apply_stock, parse_pdg, parse_pg, stock_date_warnings
from app.summary import summarize_suppliers

MIN_HOLDING, MAX_HOLDING = 0.5, 24


def _parse_uploads(data_file: UploadFile, sales_file: UploadFile, pg_file: UploadFile,
                   pdg_file: UploadFile) -> tuple[ParsedInput, ActualSales, StockResult]:
    """Parse the four uploads in order; the first unusable file is reported under its own name."""
    try:
        parsed = parse_input(data_file.file.read())
    except InputFileError as exc:
        raise HTTPException(status_code=400, detail=f"Data file: {exc}") from exc
    try:
        actual = actual_cartons(parse_sales(sales_file.file.read()), parsed)
    except InputFileError as exc:
        raise HTTPException(status_code=400, detail=f"Sales export: {exc}") from exc
    try:
        pg = parse_pg(pg_file.file.read())
    except InputFileError as exc:
        raise HTTPException(status_code=400, detail=f"{PG_NAME}: {exc}") from exc
    try:
        pdg = parse_pdg(pdg_file.file.read())
    except InputFileError as exc:
        raise HTTPException(status_code=400, detail=f"{PDG_NAME}: {exc}") from exc
    parsed, stock = apply_stock(parsed, pg, pdg)
    return parsed, actual, stock


def _parse_plan_date(text: str | None) -> date | None:
    if text is None or not text.strip():
        return None
    try:
        return date.fromisoformat(text.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Plan date '{text}' is not a valid date (use YYYY-MM-DD).") from exc


def _parse_holdings(items: list[Any]) -> list[SupplierSettings]:
    """Validate the raw PUT body so every bad value is reported with its supplier's name."""
    holdings: list[SupplierSettings] = []
    for raw in items:
        if not isinstance(raw, dict) or not isinstance(raw.get("supplier"), str) or "holding_months" not in raw:
            raise HTTPException(
                status_code=422, detail="Each setting needs a supplier name and a holding_months value.")
        name, value = raw["supplier"], raw["holding_months"]
        is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if value is not None and not (is_number and MIN_HOLDING <= value <= MAX_HOLDING):
            raise HTTPException(
                status_code=422,
                detail=f"Supplier '{name}': holding must be between {MIN_HOLDING:g} and {MAX_HOLDING:g} "
                       f"months, or blank.")
        holdings.append(SupplierSettings(supplier=name, holding_months=value))
    return holdings


def create_app(db_path: Path | None = None) -> FastAPI:
    """App factory. Start the server with: uvicorn app.main:create_app --factory --app-dir backend"""
    repo = Repository(db_path or config.DB_PATH)
    app = FastAPI(title="Order Plan Tool")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    def holdings() -> dict[str, float]:  # stop-gap until planning takes supplier settings
        return {k: v.holding_months for k, v in repo.get_settings().items() if v.holding_months is not None}

    def get_run_or_404(run_id: int) -> RunRecord:
        run = repo.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
        return run

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/inspect", response_model=InspectResponse)
    def inspect(data_file: UploadFile = File(...), sales_file: UploadFile = File(...),
                pg_file: UploadFile = File(...), pdg_file: UploadFile = File(...)) -> InspectResponse:
        parsed, actual, stock = _parse_uploads(data_file, sales_file, pg_file, pdg_file)
        min_date, max_date = plan_date_bounds(parsed)
        return InspectResponse(
            file_name=data_file.filename or "", sales_file_name=sales_file.filename or "",
            pg_file_name=pg_file.filename or "", pdg_file_name=pdg_file.filename or "", stock=stock,
            sku_count=len(parsed.skus), supplier_count=len({s.supplier for s in parsed.skus}),
            forecast_months=parsed.forecast_months, actual_months=actual.months,
            forecast_window=forecast_window(parsed),
            skus_with_sales=actual.skus_with_sales, mtd_label=parsed.mtd_label,
            mtd_end=parsed.mtd_end, default_plan_date=parsed.default_plan_date,
            min_plan_date=min_date, max_plan_date=max_date,
            warnings=(parsed.warnings + actual.warnings + stock.warnings
                      + stock_date_warnings(stock, parsed.default_plan_date)))

    @app.post("/api/runs", response_model=RunRecord)
    def create_run(data_file: UploadFile = File(...), sales_file: UploadFile = File(...),
                   pg_file: UploadFile = File(...), pdg_file: UploadFile = File(...),
                   plan_date: str | None = Form(None)) -> RunRecord:
        parsed, actual, stock = _parse_uploads(data_file, sales_file, pg_file, pdg_file)
        chosen = _parse_plan_date(plan_date) or parsed.default_plan_date
        try:
            validate_plan_date(parsed, chosen)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = plan_all(parsed, actual, repo.get_settings(), chosen)
        stock.warnings = stock.warnings + stock_date_warnings(stock, chosen)
        run_id = repo.create_run(data_file.filename or "", sales_file.filename or "",
                                 pg_file.filename or "", pdg_file.filename or "",
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
        stored = holdings()
        stats: dict[str, tuple[int, int | None]] = {}
        latest = repo.latest_run_id()
        if latest is not None:
            for sku in get_run_or_404(latest).result.skus:
                count, lead = stats.get(sku.supplier, (0, None))
                if sku.lead_time_days is not None:
                    lead = sku.lead_time_days if lead is None else max(lead, sku.lead_time_days)
                stats[sku.supplier] = (count + 1, lead)
        return [
            SupplierSettingView(supplier=name, holding_months=stored.get(name),
                                sku_count=stats.get(name, (0, None))[0],
                                max_lead_time_days=stats.get(name, (0, None))[1])
            for name in sorted(set(stats) | set(stored))]

    @app.get("/api/settings", response_model=list[SupplierSettingView])
    def get_settings() -> list[SupplierSettingView]:
        return settings_views()

    @app.put("/api/settings", response_model=list[SupplierSettingView])
    def put_settings(items: list[Any]) -> list[SupplierSettingView]:
        stored = repo.get_settings()  # stop-gap until the settings API takes MOQ and lead time
        repo.save_settings([h.model_copy(update={"moq": stored[h.supplier].moq if h.supplier in stored else 0,
                                                 "lead_time_days": stored[h.supplier].lead_time_days
                                                 if h.supplier in stored else None})
                            for h in _parse_holdings(items)])
        return settings_views()

    @app.get("/api/settings/log", response_model=list[SettingsLogEntry])
    def settings_log() -> list[SettingsLogEntry]:
        return repo.get_settings_log()

    return app

