# app/config.py

"""
Centralised runtime settings.

Priority:
 1. .env file (if python-dotenv is installed)
 2. real environment vars
 3. hard-coded defaults
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional
from pydantic import Field, AnyHttpUrl
from typing import Literal, Optional

# ── Pydantic v1 ⇆ v2 compatibility ───────────────────────────────────────────
try:
    from pydantic_settings import BaseSettings    # v2+ settings package
except ImportError:
    from pydantic import BaseSettings             # v1 fallback

from pydantic import AnyUrl, Field, PositiveFloat, conint

# ── auto-load .env ────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ModuleNotFoundError:
    pass
    


class Settings(BaseSettings):
    # strategy knobs
    neg_threshold: float = Field(0, description="Spot ≤ this triggers buy (£/MWh)")
    spread_min:   PositiveFloat = Field(50, description="Min fut-spot spread (£/MWh)")
    kelly_bank_gbp: PositiveFloat = Field(50_000, description="Kelly bank size (£)")

    # ── Phase 4: risk & limit knobs ────────────────────────────────────────
    trading_enabled:       bool    = Field(True,     description="Global master switch")
    max_notional_per_trade:float   = Field(10_000.0, description="Max exposure per cycle (£)")
    max_daily_loss_gbp:    float   = Field(500.0,    description="Stop trading after this daily loss (£)")

    # ── Phase 8: live‐feed knobs ───────────────────────────────────────────
    use_live_feed:     bool           = Field(False,
                                              description="Enable live CCXT feed")
    live_exchange:     str            = Field("binance",
                                              description="CCXT exchange id")
    live_symbol:       str            = Field("BTC/USDT",
                                              description="CCXT symbol to poll")
    live_api_key:      Optional[str]  = Field(None,
                                              env="LIVE_API_KEY",
                                              description="(Optional) CCXT API key")
    live_api_secret:   Optional[str]  = Field(None,
                                              env="LIVE_API_SECRET",
                                              description="(Optional) CCXT API secret")    
    

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
    # On-chain flash-loan contract (Hardhat/EVM)
    # ----------------------------------------------------------------------
    flash_loan_contract: Optional[str] = Field(
        None,
        env="FLASH_LOAN_CONTRACT",
        description="Deployed FlashLoan contract address (required if USE_WEB3_LOAN=1)",
    )
    
    # ----------------------------------------------------------------------
    # On-chain flash-loan receiver contract address
    # ----------------------------------------------------------------------
    receiver_address: Optional[str] = Field(
        None,
        env="FLASH_LOAN_RECEIVER",
        description="Address of the deployed TestReceiver contract (required if USE_WEB3_LOAN=1)",
    )
    
    # ── Phase 2: order‐book micro‐sim knobs ────────────────────────────
    use_depth_sim:       bool    = Field(False, description="Enable orderbook micro-sim")
    exec_latency_ms:     int     = Field(100,   description="Simulated execution latency (ms)")
    slippage_bp:         float   = Field(5.0,   description="Slippage in basis points (1 bp = 0.01%)")
    book_levels:         int     = Field(5,     description="Number of depth levels per side")
    book_size_mwh:       float   = Field(100.0, description="Quantity at each depth level (MWh)")

    # ----------------------------------------------------------------------
    # Logging
    # ----------------------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        "INFO",
        description="Log level",
    )

    # Live-trading knobs
    use_live_feed: bool = Field(
        False, env="USE_LIVE_FEED",
        description="If true, pull quotes from CCXT instead of CSV"
    )
    live_exchange: Optional[str] = Field(
        None, env="LIVE_EXCHANGE",
        description="CCXT exchange id, e.g. 'binance'"
    )
    live_symbol: Optional[str] = Field(
        None, env="LIVE_SYMBOL",
        description="Trading symbol, e.g. 'BTC/USDT'"
    )
    live_api_key: Optional[str] = Field(
        None, env="LIVE_API_KEY",
        description="CCXT API key"
    )
    live_api_secret: Optional[str] = Field(
        None, env="LIVE_API_SECRET",
        description="CCXT API secret"
    )
    
    # Live ICE integration
    ice_api_url: AnyUrl = Field(..., env="ICE_API_URL", description="Base URL for ICE REST API")
    ice_api_key: str    = Field(..., env="ICE_API_KEY", description="API key for ICE orders")
    ice_api_secret: str = Field(..., env="ICE_API_SECRET", description="API secret for ICE orders")
    ice_symbol: str     = Field("UK_BASELOAD_Q2_2025", env="ICE_SYMBOL", description="ICE symbol")
    use_ice_live: bool  = Field(False, env="USE_ICE_LIVE", description="Enable ICE live trading")


    class Config:
        env_file_encoding = "utf-8"
        case_sensitive    = False
        extra             = "ignore"

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()  # singleton
