"""
Centralised runtime settings.

Priority order:
1. Dot‑env file (.env)  – only if python‑dotenv installed
2. Real env vars        – e.g. BMRS_API_KEY, ICE_USER, ICE_PASS
3. Defaults hard‑coded below
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import AnyUrl, BaseSettings, Field, PositiveFloat, conint

# ---------------------------------------------------------------------
# Load .env automatically if present
# ---------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ModuleNotFoundError:
    pass

# ---------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------
class Settings(BaseSettings):
    # --- strategy knobs ---
    neg_threshold: float = Field(
        0, description="Buy power when spot ≤ this price (£/MWh)"
    )
    spread_min:   PositiveFloat = Field(
        50, description="Execute only if futures‑spot ≥ this (£/MWh)"
    )
    kelly_bank_gbp: PositiveFloat = 50_000

    # --- mocking parameters  ---
    pl_sigma: PositiveFloat = 25     # spot price std‑dev for mock
    fut_mu:   float          = 65    # mean futures price

    # --- external services (placeholders) ---
    bmrs_api_key: Optional[str] = None
    ice_user:     Optional[str] = None
    ice_pass:     Optional[str] = None
    hardhat_rpc:  Optional[AnyUrl] = "http://127.0.0.1:8545"

    # --- prometheus ---
    metrics_port: conint(gt=0, lt=65535) = 8000

    # --- environment ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    class Config:
        env_file_encoding = "utf-8"
        case_sensitive    = False
        extra             = "ignore"


@lru_cache
def get_settings() -> Settings:      # import‑safe singleton
    return Settings()


settings = get_settings()            # auto‑instantiated at import

