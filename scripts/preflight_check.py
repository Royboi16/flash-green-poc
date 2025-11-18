#!/usr/bin/env python
"""Preflight validation for deployments and CI.

This script validates the environment configuration, optional secret backends,
any live adapter requirements, and database connectivity before starting the
services. It exits non-zero on failure so callers can fail fast during deploys
or builds.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from app.config import Settings


def _load_env_file(env_file: Path) -> None:
    """Load key/value pairs from an ``.env`` file when present."""

    if not env_file.exists():
        raise FileNotFoundError(f"Missing env file: {env_file}")

    dotenv_spec = importlib.util.find_spec("dotenv")
    if dotenv_spec is not None:
        from dotenv import load_dotenv

        load_dotenv(env_file)
        return

    for line in env_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", maxsplit=1)
        os.environ.setdefault(key.strip(), value.strip())


def _fail_if_missing(vars_to_check: Iterable[str]) -> None:
    missing = [name for name in vars_to_check if os.environ.get(name) in (None, "")]
    if missing:
        joined = ", ".join(sorted(missing))
        raise SystemExit(f"Required environment variables are missing: {joined}")


def _check_database(url: str) -> None:
    engine = create_engine(url, pool_pre_ping=True, future=True)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate deployment prerequisites")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional .env file to load before validation",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip database connectivity check",
    )
    args = parser.parse_args()

    if args.env_file:
        _load_env_file(args.env_file)

    _fail_if_missing(["API_KEY"])

    try:
        settings = Settings()
    except Exception as exc:  # pragma: no cover - validated via integration usage
        raise SystemExit(f"Settings validation failed: {exc}") from exc

    if not args.skip_db:
        try:
            _check_database(settings.database_url)
        except Exception as exc:  # pragma: no cover - depends on target DB
            raise SystemExit(f"Database connectivity failed: {exc}") from exc

    print("Preflight checks passed:")
    print(f"- Identity: {'OIDC' if settings.oidc_issuer else 'mTLS header'} configured")
    print(f"- Secrets backend: {settings.secrets_backend or 'environment' }")
    print(f"- Live feed enabled: {settings.use_live_feed}")
    print(f"- ICE live enabled: {settings.use_ice_live}")
    print(f"- Powerledger live enabled: {settings.use_powerledger_live}")
    print(f"- Web3 loan enabled: {settings.use_web3_loan}")
    if not args.skip_db:
        print(f"- Database reachable at {settings.database_url}")


if __name__ == "__main__":
    main()
