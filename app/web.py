# app/web.py
import asyncio
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Set

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
import jwt
from jwt import InvalidTokenError, PyJWKClient
import requests
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.logger import logger
from app.orchestrator import OrchestratorService, OrchestratorSupervisor
from app.storage import connection_dependency, get_open_orders, get_pnl_totals, get_trades

api = FastAPI(
    title="Flash-Green PoC",
    version="0.1.0",
    docs_url="/",
    redoc_url=None,
)

_UI_HTML_CACHE: Optional[str] = None
_supervisor = OrchestratorSupervisor(lambda: OrchestratorService())
_LAST_TEST_RESULT: Optional[Dict[str, object]] = None
_UI_HTML_PATH = Path(__file__).with_name("static").joinpath("ui.html")
_RATE_LIMIT_MAX_CALLS = 10
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_BUCKETS: Dict[str, List[float]] = defaultdict(list)
_HEALTH_HTTP_TIMEOUT_SECONDS = 5
_DEFAULT_AUTH_ROLE = "authenticated"


@dataclass
class Principal:
    subject: str
    roles: Set[str]
    auth_method: str
    claims: Optional[Dict[str, object]] = None
# ─── Models for serialization ────────────────────────────────────────────────


class TradeOut(BaseModel):
    id: int
    timestamp: datetime
    qty_mwh: float
    spot_price: float
    fut_price: float
    profit: float
    repo_tx_hash: str | None = None
    repo_cash_token: str | None = None
    repo_asset_token: str | None = None
    repo_timestamp: datetime | None = None

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


def _detect_scheme(request: Request) -> str:
    forwarded_header = settings.forwarded_proto_header
    if forwarded_header:
        forwarded = request.headers.get(forwarded_header)
        if forwarded:
            return forwarded.split(",", 1)[0].strip().lower()
    return request.url.scheme


def _enforce_https(request: Request) -> None:
    if not settings.require_https:
        return
    scheme = _detect_scheme(request)
    if scheme != "https":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="HTTPS is required for this service",
        )


def _get_jwk_client() -> Optional[PyJWKClient]:
    if not settings.oidc_jwks_url:
        return None

    @lru_cache(maxsize=1)
    def _cached_client(url: str) -> PyJWKClient:
        return PyJWKClient(url)

    return _cached_client(str(settings.oidc_jwks_url))


def _decode_oidc_token(token: str) -> Dict[str, object]:
    jwk_client = _get_jwk_client()
    options = {"verify_aud": bool(settings.oidc_audience)}
    if jwk_client:
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        key = signing_key.key
    else:
        key = None

    return jwt.decode(
        token,
        key=key,
        algorithms=settings.oidc_allowed_algorithms,
        audience=settings.oidc_audience,
        issuer=settings.oidc_issuer,
        options=options,
    )


def _extract_roles(claims: Dict[str, object]) -> Set[str]:
    roles: Set[str] = set()
    claim_roles = claims.get("roles")
    if isinstance(claim_roles, list):
        roles.update(str(role) for role in claim_roles)
    elif isinstance(claim_roles, str):
        roles.add(claim_roles)

    scopes = claims.get("scope")
    if isinstance(scopes, str):
        roles.update(scope for scope in scopes.split())

    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        nested_roles = realm_access.get("roles")
        if isinstance(nested_roles, list):
            roles.update(str(role) for role in nested_roles)

    if not roles:
        roles.add(_DEFAULT_AUTH_ROLE)

    return roles


async def require_principal(request: Request) -> Principal:
    _enforce_https(request)
    errors: List[str] = []
    if not (
        (settings.oidc_issuer and settings.oidc_audience)
        or settings.client_cert_subject_header
    ):
        logger.error("Identity provider is not configured; refusing request")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity provider is not configured",
        )

    bearer = request.headers.get("Authorization")
    bearer_token = None
    if bearer:
        prefix = "bearer "
        if bearer.lower().startswith(prefix):
            bearer_token = bearer[len(prefix) :]

    if settings.oidc_issuer and settings.oidc_audience and bearer_token:
        try:
            claims = _decode_oidc_token(bearer_token)
            return Principal(
                subject=str(claims.get("sub") or "unknown"),
                roles=_extract_roles(claims),
                auth_method="oidc",
                claims=claims,
            )
        except InvalidTokenError as exc:
            errors.append(f"oidc: {exc}")

    subject_header = settings.client_cert_subject_header
    if subject_header:
        subject_value = request.headers.get(subject_header)
        if subject_value:
            if settings.mtls_allowed_subjects and subject_value not in settings.mtls_allowed_subjects:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Client certificate is not authorized",
                )
            return Principal(
                subject=subject_value,
                roles=set(settings.mtls_assigned_roles or [_DEFAULT_AUTH_ROLE]),
                auth_method="mtls",
                claims={"cn": subject_value},
            )
        errors.append("mTLS subject header missing")

    logger.warning("Authentication failed", extra={"errors": errors})
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


async def require_api_key(
    principal: Principal = Depends(require_principal),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    expected_key = settings.api_key

    if not expected_key:
        logger.error("API_KEY is not configured; refusing to serve requests")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API_KEY is not configured",
        )

    if not x_api_key or x_api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )

    return x_api_key


def _rate_limit_identifier(api_key: str, request: Request, principal: Principal | None = None) -> str:
    client_host = request.client.host if request.client else "unknown"
    principal_part = principal.subject if principal else "anonymous"
    return f"{principal_part}:{api_key}:{client_host}"


def _enforce_rate_limit(identifier: str, action: str) -> None:
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS
    bucket = _RATE_LIMIT_BUCKETS[identifier]
    _RATE_LIMIT_BUCKETS[identifier] = [ts for ts in bucket if ts >= window_start]

    if len(_RATE_LIMIT_BUCKETS[identifier]) >= _RATE_LIMIT_MAX_CALLS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for {action}",
        )

    _RATE_LIMIT_BUCKETS[identifier].append(now)


def _audit_log(action: str, request: Request, principal: Principal, **extra: object) -> None:
    logger.info(
        "AUDIT action=%s principal=%s roles=%s auth_method=%s client=%s extra=%s",
        action,
        principal.subject,
        sorted(principal.roles),
        principal.auth_method,
        request.client.host if request.client else "unknown",
        extra,
    )


async def control_plane_guard(
    request: Request,
    api_key: str = Depends(require_api_key),
    principal: Principal = Depends(require_principal),
) -> Principal:
    allowed_roles = set(settings.control_plane_roles)
    if allowed_roles and not principal.roles.intersection(allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal is not permitted to access control-plane routes",
        )

    identifier = _rate_limit_identifier(
        api_key=api_key, request=request, principal=principal
    )
    _enforce_rate_limit(identifier=identifier, action=request.url.path)
    _audit_log(action=request.url.path, request=request, principal=principal)
    return principal


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


def _orchestrator_status() -> Dict[str, object]:
    return _supervisor.status()


def _check_database(conn: Session) -> Dict[str, object]:
    try:
        conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.error("Database health check failed", exc_info=True)
        return {"status": "error", "detail": str(exc)}


def _check_orchestrator_health() -> Dict[str, object]:
    status = _orchestrator_status()
    if status.get("running"):
        return {"status": "ok", **status}
    detail = status.get("last_error") or "orchestrator service not running"
    return {"status": "error", "detail": detail, **status}


def _probe_live_feed() -> Dict[str, object]:
    try:
        from app.exchange import LivePowerExchange

        adapter = LivePowerExchange(
            exchange_id=settings.live_exchange,
            symbol=settings.live_symbol,
            api_key=settings.live_api_key,
            api_secret=settings.live_api_secret,
        )
        price = adapter.quote()
        return {"status": "ok", "last_price": price}
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("Live feed health check failed", exc_info=True)
        return {"status": "error", "detail": str(exc)}


def _probe_ice_live() -> Dict[str, object]:
    headers = {
        "X-API-KEY": settings.ice_api_key or "",
        "X-API-SECRET": settings.ice_api_secret or "",
    }
    try:
        resp = requests.get(
            f"{settings.ice_api_url}/marketdata/{settings.ice_symbol}/orderbook",
            timeout=_HEALTH_HTTP_TIMEOUT_SECONDS,
            headers=headers,
        )
        resp.raise_for_status()
        body = resp.json()
        bids = body.get("bids") or []
        asks = body.get("asks") or []
        return {
            "status": "ok",
            "status_code": resp.status_code,
            "best_bid": float(bids[0]["price"]) if bids else None,
            "best_ask": float(asks[0]["price"]) if asks else None,
        }
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("ICE live health check failed", exc_info=True)
        return {"status": "error", "detail": str(exc)}


def _probe_powerledger_live() -> Dict[str, object]:
    headers = {"X-PL-API-Key": settings.powerledger_api_token or "", "X-PL-Org": settings.powerledger_org or ""}
    try:
        resp = requests.get(
            f"{settings.powerledger_api_url}/markets/{settings.powerledger_market}/price",
            timeout=_HEALTH_HTTP_TIMEOUT_SECONDS,
            headers=headers,
        )
        resp.raise_for_status()
        body = resp.json()
        return {
            "status": "ok",
            "status_code": resp.status_code,
            "last_price": float(body.get("price_mwh", 0)),
        }
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("Powerledger health check failed", exc_info=True)
        return {"status": "error", "detail": str(exc)}


def _check_live_adapters() -> Dict[str, Dict[str, object]]:
    checks: Dict[str, Dict[str, object]] = {}

    if settings.use_live_feed:
        checks["live_feed"] = _probe_live_feed()

    if settings.use_ice_live:
        checks["ice_live"] = _probe_ice_live()

    if settings.use_powerledger_live:
        checks["powerledger_live"] = _probe_powerledger_live()

    if checks:
        checks["status"] = (
            "ok" if all(val.get("status") == "ok" for val in checks.values()) else "error"
        )

    return checks


def _has_degraded(check: Dict[str, object]) -> bool:
    status_value = check.get("status")
    if isinstance(status_value, str) and status_value != "ok":
        return True

    for value in check.values():
        if isinstance(value, dict) and _has_degraded(value):
            return True

    return False


# ─── Health & metrics ────────────────────────────────────────────────────────


@api.get("/healthz")
async def health(probe: str = "readiness", conn: Session = Depends(connection_dependency)):
    checks: Dict[str, Dict[str, object]] = {}

    checks["database"] = _check_database(conn)

    if probe == "readiness":
        checks["orchestrator"] = _check_orchestrator_health()
        adapter_checks = _check_live_adapters()
        if adapter_checks:
            checks["adapters"] = adapter_checks

    degraded = any(_has_degraded(result) for result in checks.values())
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE if degraded else status.HTTP_200_OK

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "degraded" if degraded else "ok",
            "probe": probe,
            "checks": checks,
        },
    )


@api.get("/metrics", dependencies=[Depends(require_api_key)])
async def prom():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@api.get("/pnl", dependencies=[Depends(require_api_key)])
async def pnl(conn: Session = Depends(connection_dependency)):
    """Return aggregated profit/loss totals: net, positive, and negative."""
    return get_pnl_totals(conn=conn)


@api.get("/ui", response_class=HTMLResponse)
async def ui():
    return HTMLResponse(content=_load_ui_html())


# ─── Data endpoints ──────────────────────────────────────────────────────────


@api.get("/trades", response_model=List[TradeOut], dependencies=[Depends(require_api_key)])
async def trades(limit: int = 100, conn: Session = Depends(connection_dependency)):
    """
    Retrieve up to `limit` most recent trades.
    """
    return get_trades(limit=limit, conn=conn)


@api.get("/orders/open", response_model=List[OrderOut], dependencies=[Depends(require_api_key)])
async def open_orders(conn: Session = Depends(connection_dependency)):
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
        "use_depth_sim": settings.use_depth_sim,
        "exec_latency_ms": settings.exec_latency_ms,
        "slippage_bp": settings.slippage_bp,
        "book_levels": settings.book_levels,
        "book_size_mwh": settings.book_size_mwh,
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


@api.get("/ui/services/status")
async def ui_service_status(
    request: Request, principal: Principal = Depends(control_plane_guard)
):
    return _orchestrator_status()


@api.post("/ui/services/start")
async def ui_service_start(
    request: Request,
    payload: ServiceStartRequest,
    principal: Principal = Depends(control_plane_guard),
):
    if payload.command or payload.env:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Custom commands or env overrides are not supported in supervised mode",
        )

    orchestrator_status = _orchestrator_status()
    if orchestrator_status.get("running"):
        return {"detail": "orchestrator already running", **orchestrator_status}

    _supervisor.start()
    orchestrator_status = _orchestrator_status()

    _audit_log(
        action="/ui/services/start",
        request=request,
        principal=principal,
        status=orchestrator_status,
    )
    return {"detail": "orchestrator started", **orchestrator_status}


@api.post("/ui/services/stop")
async def ui_service_stop(request: Request, principal: Principal = Depends(control_plane_guard)):
    orchestrator_status = _orchestrator_status()
    if not orchestrator_status.get("running") and not orchestrator_status.get("supervisor_running"):
        return {"detail": "orchestrator already stopped", **orchestrator_status}

    _supervisor.stop()
    stopped = _orchestrator_status()
    _audit_log(
        action="/ui/services/stop", request=request, principal=principal, status=stopped
    )
    return {"detail": "orchestrator stopped", **stopped}


@api.post("/ui/tests/run")
async def ui_run_tests(
    request: Request,
    payload: TestRunRequest,
    principal: Principal = Depends(control_plane_guard),
):
    global _LAST_TEST_RESULT

    cmd = ["poetry", "run", "pytest"]
    if payload.markers:
        cmd += ["-k", payload.markers]
    if payload.extra_args:
        cmd += payload.extra_args

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

    _audit_log(
        action="/ui/tests/run",
        request=request,
        principal=principal,
        returncode=result.returncode,
        command=cmd,
    )
    return _LAST_TEST_RESULT


@api.get("/ui/tests/last", dependencies=[Depends(require_api_key)])
async def ui_last_test():
    if _LAST_TEST_RESULT is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No tests have been run yet")
    return _LAST_TEST_RESULT
