# app/web.py
import asyncio
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import sqlite3

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import settings
from app.logger import logger
from app.storage import connection_dependency, get_open_orders, get_pnl_totals, get_trades

api = FastAPI(
    title="Flash-Green PoC",
    version="0.1.0",
    docs_url="/",
    redoc_url=None,
)

_UI_HTML_CACHE: Optional[str] = None
_ORCHESTRATOR_CMD = ["python", "-m", "app.orchestrator"]
_orchestrator_process: Optional[subprocess.Popen[str]] = None
_LAST_TEST_RESULT: Optional[Dict[str, object]] = None
_UI_HTML_PATH = Path(__file__).with_name("static").joinpath("ui.html")

# ─── Models for serialization ────────────────────────────────────────────────


class TradeOut(BaseModel):
    id: int
    timestamp: datetime
    qty_mwh: float
    spot_price: float
    fut_price: float
    profit: float

    class Config:
        from_attributes = True


class OrderOut(BaseModel):
    id: Optional[str]
    symbol: str
    side: str
    qty_requested: float
    qty_filled: float
    avg_price: float
    status: str

    class Config:
        from_attributes = True


class ServiceStartRequest(BaseModel):
    command: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None


class TestRunRequest(BaseModel):
    markers: Optional[str] = None
    extra_args: Optional[List[str]] = None


# ─── Auth ────────────────────────────────────────────────────────────────────


async def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    expected_key = settings.api_key

    # In development/test environments the API can be used without configuring an
    # API_KEY. When a key is set (staging/production), the header is required.
    if not expected_key:
        logger.debug("API_KEY not configured; skipping authentication")
        return

    if x_api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


def _load_ui_html() -> str:
    global _UI_HTML_CACHE

    if _UI_HTML_CACHE is None:
        if not _UI_HTML_PATH.exists():
            logger.error("UI template missing at %s", _UI_HTML_PATH)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="UI template not found",
            )

        _UI_HTML_CACHE = _UI_HTML_PATH.read_text(encoding="utf-8")

    return _UI_HTML_CACHE


def _process_command(proc: Optional[subprocess.Popen[str]]) -> List[str]:
    if proc and isinstance(proc.args, list):
        return [str(arg) for arg in proc.args]
    return _ORCHESTRATOR_CMD.copy()


def _orchestrator_status() -> Dict[str, object]:
    running = _orchestrator_process is not None and _orchestrator_process.poll() is None
    return {
        "running": running,
        "pid": _orchestrator_process.pid if running and _orchestrator_process else None,
        "command": _process_command(_orchestrator_process),
    }


# ─── Health & metrics ────────────────────────────────────────────────────────


@api.get("/healthz")
async def health():
    return {"status": "ok"}


@api.get("/metrics", dependencies=[Depends(require_api_key)])
async def prom():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@api.get("/pnl", dependencies=[Depends(require_api_key)])
async def pnl(conn: sqlite3.Connection = Depends(connection_dependency)):
    """Return aggregated profit/loss totals: net, positive, and negative."""
    return get_pnl_totals(conn=conn)


@api.get("/ui", response_class=HTMLResponse)
async def ui():
    return HTMLResponse(content=_load_ui_html())


# ─── Data endpoints ──────────────────────────────────────────────────────────


@api.get("/trades", response_model=List[TradeOut], dependencies=[Depends(require_api_key)])
async def trades(limit: int = 100, conn: sqlite3.Connection = Depends(connection_dependency)):
    """
    Retrieve up to `limit` most recent trades.
    """
    return get_trades(limit=limit, conn=conn)


@api.get("/orders/open", response_model=List[OrderOut], dependencies=[Depends(require_api_key)])
async def open_orders(conn: sqlite3.Connection = Depends(connection_dependency)):
    """
    List any in-flight (open) orders.
    """
    try:
        return get_open_orders(conn=conn)
    except Exception:
        # log full traceback
        logger.error("Error in /orders/open", exc_info=True)
        # return a plain-text 500 so the client sees something legible
        return PlainTextResponse(
            "Internal Server Error fetching open orders", status_code=500
        )


# ─── UI helpers for orchestration and tests ──────────────────────────────────


@api.get("/ui/state", dependencies=[Depends(require_api_key)])
async def ui_state():
    config_preview = {
        "api_port": settings.api_port,
        "metrics_port": settings.metrics_port,
        "trading_enabled": settings.trading_enabled,
        "spread_min": settings.spread_min,
        "neg_threshold": settings.neg_threshold,
        "max_notional_per_trade": settings.max_notional_per_trade,
        "max_daily_loss_gbp": settings.max_daily_loss_gbp,
        "use_live_feed": settings.use_live_feed,
        "use_ice_live": settings.use_ice_live,
        "use_web3_loan": settings.use_web3_loan,
    }
    return {
        "config": config_preview,
        "orchestrator": _orchestrator_status(),
        "last_test_result": _LAST_TEST_RESULT,
    }


@api.get("/ui/services/status", dependencies=[Depends(require_api_key)])
async def ui_service_status():
    return _orchestrator_status()


@api.post("/ui/services/start", dependencies=[Depends(require_api_key)])
async def ui_service_start(request: ServiceStartRequest):
    global _orchestrator_process

    if _orchestrator_process and _orchestrator_process.poll() is None:
        return {"detail": "orchestrator already running", **_orchestrator_status()}

    env = os.environ.copy()
    if request.env:
        env.update(request.env)

    cmd = request.command or _ORCHESTRATOR_CMD

    try:
        _orchestrator_process = subprocess.Popen(cmd, env=env)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Command not found; ensure the executable exists in PATH",
        )
    except Exception as exc:  # pragma: no cover - safeguard
        logger.error("Failed to start orchestrator", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not start orchestrator: {exc}",
        )

    return {"detail": "orchestrator started", **_orchestrator_status()}


@api.post("/ui/services/stop", dependencies=[Depends(require_api_key)])
async def ui_service_stop():
    global _orchestrator_process

    if _orchestrator_process is None or _orchestrator_process.poll() is not None:
        _orchestrator_process = None
        return {"detail": "orchestrator already stopped", **_orchestrator_status()}

    _orchestrator_process.terminate()
    try:
        _orchestrator_process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        _orchestrator_process.kill()

    stopped = _orchestrator_status()
    _orchestrator_process = None
    return {"detail": "orchestrator stopped", **stopped}


@api.post("/ui/tests/run", dependencies=[Depends(require_api_key)])
async def ui_run_tests(request: TestRunRequest):
    global _LAST_TEST_RESULT

    cmd = ["poetry", "run", "pytest"]
    if request.markers:
        cmd += ["-k", request.markers]
    if request.extra_args:
        cmd += request.extra_args

    started_at = datetime.utcnow().isoformat() + "Z"

    result = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=True,
    )

    _LAST_TEST_RESULT = {
        "command": cmd,
        "started_at": started_at,
        "finished_at": datetime.utcnow().isoformat() + "Z",
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "succeeded": result.returncode == 0,
    }

    return _LAST_TEST_RESULT


@api.get("/ui/tests/last", dependencies=[Depends(require_api_key)])
async def ui_last_test():
    if _LAST_TEST_RESULT is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No tests have been run yet")
    return _LAST_TEST_RESULT
