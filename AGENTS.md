# Flash Green POC — Agent Guide

This repository hosts a proof-of-concept arbitrage bot that connects simulated or live power feeds, ICE, and a flash-loan adapter. Use this guide to keep changes consistent and safe.

## Project orientation
- **Runtime entry point:** `app/orchestrator.py` wires together feeds, exchanges, storage, and risk controls. It is the best starting point for understanding the control flow.
- **Configuration:** `app/config.py` defines `Settings` with Pydantic-based validation and secret loading from Vault/AWS. `.env` files are loaded automatically if present.
- **Adapters:**
  - Market data abstractions live in `app/feeds/` and `app/feed.py`.
  - Exchange logic is split between `app/exchange.py` (sim/CCXT) and `app/exchange_ice.py` (ICE REST).
  - On-chain flash loans and Hardhat integration are in `app/loan_web3.py` plus the `Hardhat/` project.
- **Risk/strategy:** `app/strategy.py`, `app/risk.py`, and `app/orderbook.py` hold the trading logic and safeguards.

## Environment & dependencies
- Target Python **3.11**; dependencies are managed with **Poetry** (`pyproject.toml`). Run `poetry install` to set up a virtualenv.
- Extras:
  - `poetry install --with hardhat` pulls in Web3 + dotenv for the flash-loan path.
  - AWS/Vault helpers require the optional `boto3` or `hvac` packages; see `app/config.py` for expectations.
- Configuration workflow mirrors the README: copy `env.staging.example` or `env.production.example` to `.env`, then fill in the placeholders. Secrets can be fetched from Vault (`SECRETS_BACKEND=vault`) or AWS (`SECRETS_BACKEND=aws`).

## Running the system
- Local orchestration: `poetry run python -m app.orchestrator` auto-loads `.env` and starts the components.
- The API server lives in `app/web.py` (FastAPI + Prometheus metrics). Adjust ports via `Settings.api_port` / `metrics_port`.
- Hardhat flash-loan demos expect `Hardhat/` to be built separately; keep RPC endpoints (`HARDHAT_RPC`) in sync with the `.env` you load.

## Testing & quality
- Default suite: `poetry run pytest` (tests live under `tests/` and use `pythonpath = ["app"]`).
- Fast checks for configuration changes: `poetry run pytest -k config` exercises the validation and secret-loading paths.
- Linting uses `flake8` with a **120** character line limit (`[tool.flake8]` in `pyproject.toml`).
- Avoid wrapping imports in `try/except` unless the module is optional (follow existing patterns in `app/config.py`).

## Development tips
- Keep feature toggles (`USE_LIVE_FEED`, `USE_ICE_LIVE`, `USE_WEB3_LOAN`) consistent with the credentials you supply; missing values raise `ValueError` at startup.
- Structure new adapters like the existing ones: pure data/IO in adapter modules, orchestration and decision-making in `app/orchestrator.py` and `app/strategy.py`.
- Tests rely on deterministic, in-memory components; prefer injecting fakes/mocks over global state when adding new behaviors.
