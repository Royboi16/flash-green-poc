# app/config.py

"""Centralised runtime settings and secret loading helpers."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Literal, Optional

from pydantic import AnyUrl, Field, PositiveFloat, conint, model_validator

# ── Pydantic v1 ⇆ v2 compatibility ───────────────────────────────────────────
try:  # pragma: no cover - import shim
    from pydantic_settings import BaseSettings  # type: ignore
except ImportError:  # pragma: no cover - fallback for <2.0
    from pydantic import BaseSettings  # type: ignore

# ── auto-load .env ────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ModuleNotFoundError:
    pass
    


SECRET_FIELD_MAP: Dict[str, str] = {
    "live_api_key": "LIVE_API_KEY",
    "live_api_secret": "LIVE_API_SECRET",
    "ice_api_key": "ICE_API_KEY",
    "ice_api_secret": "ICE_API_SECRET",
    "flash_loan_contract": "FLASH_LOAN_CONTRACT",
    "receiver_address": "FLASH_LOAN_RECEIVER",
    "lender_private_key": "LENDER_KEY",
}


def _load_vault_secret(addr: str, token: str, path: str) -> Dict[str, str]:
    """Return secret data from HashiCorp Vault KV v2."""

    try:  # pragma: no cover - exercised via integration tests only
        import hvac  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "HashiCorp Vault support requires the 'hvac' extra. Install with "
            "`pip install hvac` or disable SECRETS_BACKEND=vault."
        ) from exc

    client = hvac.Client(url=addr, token=token)
    if not client.is_authenticated():  # pragma: no cover - depends on remote Vault
        raise RuntimeError("Unable to authenticate with Vault. Check VAULT_TOKEN.")
    response = client.secrets.kv.v2.read_secret_version(path=path)
    data = response.get("data", {}).get("data", {})
    if not isinstance(data, dict):
        raise RuntimeError("Vault secret payload must be a mapping")
    return data


def _load_aws_secret(region: str, secret_id: str) -> Dict[str, str]:
    """Return a JSON secret from AWS Secrets Manager."""

    try:  # pragma: no cover - exercised via integration tests only
        import boto3  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "AWS Secrets Manager support requires 'boto3'. Install it or "
            "unset SECRETS_BACKEND=aws."
        ) from exc

    client = boto3.client("secretsmanager", region_name=region)
    payload = client.get_secret_value(SecretId=secret_id)
    secret_string = payload.get("SecretString")
    if not secret_string:
        raise RuntimeError("AWS secret must provide a JSON SecretString payload")
    try:
        data = json.loads(secret_string)
    except json.JSONDecodeError as exc:  # pragma: no cover - data dependent
        raise RuntimeError("AWS secret payload must be valid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("AWS secret JSON must be an object")
    return data


class Settings(BaseSettings):
    # strategy knobs
    neg_threshold: float = Field(0, description="Spot ≤ this triggers buy (£/MWh)")
    spread_min:   PositiveFloat = Field(50, description="Min fut-spot spread (£/MWh)")
    kelly_bank_gbp: PositiveFloat = Field(50_000, description="Kelly bank size (£)")

    # ── Phase 4: risk & limit knobs ────────────────────────────────────────
    trading_enabled:       bool    = Field(True,     description="Global master switch")
    max_notional_per_trade:float   = Field(10_000.0, description="Max exposure per cycle (£)")
    max_daily_loss_gbp:    float   = Field(500.0,    description="Stop trading after this daily loss (£)")

    # mock-feed params
    pl_sigma: PositiveFloat = Field(25, description="Std-dev for spot noise")
    fut_mu:   float         = Field(65, description="Mean for futures noise")

    # ports
    metrics_port: conint(gt=0, lt=65535) = Field(8000, description="Prometheus port")
    api_port:     conint(gt=0, lt=65535) = Field(8002, description="FastAPI port")

    # externals (placeholders)
    bmrs_api_key: Optional[str] = None
    ice_user:     Optional[str] = None
    ice_pass:     Optional[str] = None
    hardhat_rpc:  Optional[AnyUrl] = Field("http://127.0.0.1:8545", description="EVM RPC")

    # ----------------------------------------------------------------------
    # Logging
    # ----------------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        "INFO",
        description="Log level",
    )

    # ----------------------------------------------------------------------
    # Live-trading knobs
    # ----------------------------------------------------------------------
    use_live_feed: bool = Field(
        False,
        env="USE_LIVE_FEED",
        description="If true, pull quotes from CCXT instead of CSV",
    )
    live_exchange: Optional[str] = Field(
        None,
        env="LIVE_EXCHANGE",
        description="CCXT exchange id, e.g. 'binance'",
    )
    live_symbol: Optional[str] = Field(
        None,
        env="LIVE_SYMBOL",
        description="Trading symbol, e.g. 'BTC/USDT'",
    )
    live_api_key: Optional[str] = Field(
        None,
        env="LIVE_API_KEY",
        description="CCXT API key",
    )
    live_api_secret: Optional[str] = Field(
        None,
        env="LIVE_API_SECRET",
        description="CCXT API secret",
    )
    
    # How long to poll before cancelling
    order_timeout_secs: int = Field(30, env="ORDER_TIMEOUT_SECS", description="Max seconds to wait for fill")
    order_poll_interval: float = Field(1.0, env="ORDER_POLL_INTERVAL", description="Seconds between fetch_order calls")
    
    # Live ICE integration (optional unless USE_ICE_LIVE=1)
    use_ice_live: bool = Field(False, env="USE_ICE_LIVE", description="Enable ICE live trading")
    ice_api_url: Optional[AnyUrl] = Field(
        None, env="ICE_API_URL", description="Base URL for ICE REST API"
    )
    ice_api_key: Optional[str] = Field(
        None, env="ICE_API_KEY", description="API key for ICE orders"
    )
    ice_api_secret: Optional[str] = Field(
        None, env="ICE_API_SECRET", description="API secret for ICE orders"
    )
    ice_symbol: Optional[str] = Field(
        "UK_BASELOAD_Q2_2025", env="ICE_SYMBOL", description="ICE symbol"
    )

    # ----------------------------------------------------------------------
    # On-chain flash-loan contract (Hardhat/EVM)
    # ----------------------------------------------------------------------
    use_web3_loan: bool = Field(
        False,
        env="USE_WEB3_LOAN",
        description="Use the on-chain flash-loan adapter instead of the mock",
    )
    flash_loan_contract: Optional[str] = Field(
        None,
        env="FLASH_LOAN_CONTRACT",
        description="Deployed FlashLoan contract address",
    )
    receiver_address: Optional[str] = Field(
        None,
        env="FLASH_LOAN_RECEIVER",
        description="Address of the deployed TestReceiver contract",
    )
    lender_private_key: Optional[str] = Field(
        None,
        env="LENDER_KEY",
        description="Private key for the account that owns the flash-loan contract",
    )

    # ----------------------------------------------------------------------
    # Secret backends
    # ----------------------------------------------------------------------
    secrets_backend: Optional[Literal["vault", "aws"]] = Field(
        None,
        env="SECRETS_BACKEND",
        description="Optional secret manager integration (vault | aws)",
    )
    secrets_vault_addr: Optional[AnyUrl] = Field(
        None,
        env="VAULT_ADDR",
        description="Vault server address when SECRETS_BACKEND=vault",
    )
    secrets_vault_token: Optional[str] = Field(
        None, env="VAULT_TOKEN", description="Vault token used for auth"
    )
    secrets_vault_path: Optional[str] = Field(
        None,
        env="VAULT_SECRET_PATH",
        description="Secret path (e.g. secret/data/flash-green)",
    )
    secrets_aws_region: Optional[str] = Field(
        None,
        env="AWS_SECRETS_REGION",
        description="Region used for AWS Secrets Manager",
    )
    secrets_aws_secret_id: Optional[str] = Field(
        None,
        env="AWS_SECRETS_ID",
        description="SecretId containing JSON payload",
    )

    # ── Phase 2: order‐book micro‐sim knobs ────────────────────────────
    use_depth_sim: bool = Field(False, description="Enable orderbook micro-sim")
    exec_latency_ms: int = Field(100, description="Simulated execution latency (ms)")
    slippage_bp: float = Field(
        5.0, description="Slippage in basis points (1 bp = 0.01%)"
    )
    book_levels: int = Field(5, description="Number of depth levels per side")
    book_size_mwh: float = Field(
        100.0, description="Quantity at each depth level (MWh)"
    )

    @model_validator(mode="after")
    def _hydrate_secret_backends(cls, model: "Settings") -> "Settings":
        if not model.secrets_backend:
            return model

        if model.secrets_backend == "vault":
            required = ["secrets_vault_addr", "secrets_vault_token", "secrets_vault_path"]
            missing = [name for name in required if getattr(model, name) in (None, "")]
            if missing:
                raise ValueError(
                    "SECRETS_BACKEND=vault requires " + ", ".join(missing)
                )
            secrets = _load_vault_secret(
                str(model.secrets_vault_addr),  # type: ignore[arg-type]
                model.secrets_vault_token,
                model.secrets_vault_path,
            )
        elif model.secrets_backend == "aws":
            required = ["secrets_aws_region", "secrets_aws_secret_id"]
            missing = [name for name in required if getattr(model, name) in (None, "")]
            if missing:
                raise ValueError(
                    "SECRETS_BACKEND=aws requires " + ", ".join(missing)
                )
            secrets = _load_aws_secret(model.secrets_aws_region, model.secrets_aws_secret_id)
        else:  # pragma: no cover - exhaustive Literal
            secrets = {}

        for field_name, secret_key in SECRET_FIELD_MAP.items():
            if getattr(model, field_name) in (None, "") and secret_key in secrets:
                setattr(model, field_name, secrets[secret_key])
        return model

    @model_validator(mode="after")
    def _validate_integrations(cls, model: "Settings") -> "Settings":
        if model.use_live_feed:
            missing = [
                field
                for field in ("live_exchange", "live_symbol", "live_api_key", "live_api_secret")
                if getattr(model, field) in (None, "")
            ]
            if missing:
                raise ValueError(
                    "Live feed enabled but missing: " + ", ".join(missing)
                )

        if model.use_ice_live:
            missing = [
                field
                for field in ("ice_api_url", "ice_api_key", "ice_api_secret", "ice_symbol")
                if getattr(model, field) in (None, "")
            ]
            if missing:
                raise ValueError(
                    "Missing ICE config: "
                    + ", ".join(missing)
                    + " – either set those env vars, or export USE_ICE_LIVE=0"
                )

        if model.use_web3_loan:
            missing = [
                field
                for field in (
                    "flash_loan_contract",
                    "receiver_address",
                    "lender_private_key",
                )
                if getattr(model, field) in (None, "")
            ]
            if missing:
                raise ValueError(
                    "USE_WEB3_LOAN=1 requires: " + ", ".join(missing)
                )

        return model


    class Config:
        env_file_encoding = "utf-8"
        case_sensitive    = False
        extra             = "ignore"

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()  # singleton
