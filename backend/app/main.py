"""HTTP API: wires parsing, planning and storage to FastAPI routes."""
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app import config
from app.engine import plan_all, plan_date_bounds, validate_plan_date
from app.export import XLSX_MEDIA_TYPE, build_export
from app.models import (InputFileError, InspectResponse, ParsedInput, RunListItem, RunRecord,
                        SupplierSetting, SupplierSettingView, SupplierSummary)
from app.parsing import parse_input
from app.repository import Repository
from app.summary import summarize_suppliers


def _parse_upload(file: UploadFile) -> ParsedInput:
    try:
        return parse_input(file.file.read())
    except InputFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _parse_plan_date(text: str | None) -> date | None:
    if text is None or not text.strip():
        return None
    try:
        return date.fromisoformat(text.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Plan date '{text}' is not a valid date (use YYYY-MM-DD).") from exc


def _validate_setting(item: SupplierSetting) -> None:
    for label, value in (("reorder_days", item.reorder_days), ("target_days", item.target_days)):
        if not 1 <= value <= 365:
            raise HTTPException(
                status_code=422,
                detail=f"Supplier '{item.supplier}': {label} must be a whole number from 1 to 365.")
    if item.target_days <= item.reorder_days:
        raise HTTPException(
            status_code=422,
            detail=f"Supplier '{item.supplier}': target days must be greater than reorder days.")


def create_app(db_path: Path = config.DB_PATH) -> FastAPI:
    repo = Repository(db_path)
    app = FastAPI(title="Order Plan Tool")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    def get_run_or_404(run_id: int) -> RunRecord:
        run = repo.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found.")
        return run

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/inspect", response_model=InspectResponse)
    def inspect(file: UploadFile = File(...)) -> InspectResponse:
        parsed = _parse_upload(file)
        min_date, max_date = plan_date_bounds(parsed)
        return InspectResponse(
            file_name=file.filename or "", sku_count=len(parsed.skus),
            supplier_count=len({s.supplier for s in parsed.skus}),
            forecast_months=parsed.forecast_months, mtd_label=parsed.mtd_label,
            default_plan_date=parsed.default_plan_date,
            min_plan_date=min_date, max_plan_date=max_date, warnings=parsed.warnings)

    @app.post("/api/runs", response_model=RunRecord)
    def create_run(file: UploadFile = File(...), plan_date: str | None = Form(None)) -> RunRecord:
        parsed = _parse_upload(file)
        chosen = _parse_plan_date(plan_date) or parsed.default_plan_date
        try:
            validate_plan_date(parsed, chosen)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = plan_all(parsed, repo.get_settings(), chosen)
        repo.add_default_settings([s for s in result.settings_used if s.supplier in result.new_suppliers])
        run_id = repo.create_run(file.filename or "", parsed, result)
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
        result = plan_all(run.parsed, repo.get_settings(), run.result.plan_date)
        repo.update_run_result(run_id, result)
        return get_run_or_404(run_id)

    @app.get("/api/runs/{run_id}/suppliers", response_model=list[SupplierSummary])
    def run_suppliers(run_id: int, window_weeks: int = Query(4, ge=1, le=52)) -> list[SupplierSummary]:
        return summarize_suppliers(get_run_or_404(run_id).result, window_weeks)

    @app.get("/api/runs/{run_id}/export")
    def export_run(run_id: int, window_weeks: int = Query(4, ge=1, le=52)) -> Response:
        run = get_run_or_404(run_id)
        filename = f"order-plan-{run.plan_date.isoformat()}-run{run.id}.xlsx"
        return Response(content=build_export(run, window_weeks), media_type=XLSX_MEDIA_TYPE,
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    def settings_views() -> list[SupplierSettingView]:
        stats: dict[str, tuple[int, int | None]] = {}
        latest = repo.latest_run_id()
        if latest is not None:
            for sku in get_run_or_404(latest).result.skus:
                count, lead = stats.get(sku.supplier, (0, None))
                if sku.lead_time_days is not None:
                    lead = sku.lead_time_days if lead is None else max(lead, sku.lead_time_days)
                stats[sku.supplier] = (count + 1, lead)
        return [
            SupplierSettingView(**s.model_dump(), max_lead_time_days=stats.get(s.supplier, (0, None))[1],
                                sku_count=stats.get(s.supplier, (0, None))[0])
            for s in sorted(repo.get_settings().values(), key=lambda s: s.supplier)]

    @app.get("/api/settings", response_model=list[SupplierSettingView])
    def get_settings() -> list[SupplierSettingView]:
        return settings_views()

    @app.put("/api/settings", response_model=list[SupplierSettingView])
    def put_settings(items: list[SupplierSetting]) -> list[SupplierSettingView]:
        for item in items:
            _validate_setting(item)
        repo.save_settings([item.model_copy(update={"is_default": False}) for item in items])
        return settings_views()

    return app


app = create_app()
