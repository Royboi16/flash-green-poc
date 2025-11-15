# flash-green-poc

This repository contains a proof-of-concept flash-loan arbitrage bot that combines
on-chain data with exchange data to explore green energy trades.

## Development setup

1. Install Poetry 1.4 or newer.
2. Install all dependencies, including the development group used for linting:
   ```bash
   poetry install --with dev
   ```
3. Run the FastAPI/worker stack as needed via `docker compose` (see the
   environment manifests for details).

## Linting with Flake8

Pull requests are now validated with `flake8`. Run the linter locally before
submitting patches:

```bash
poetry run flake8
```

The configuration lives in `pyproject.toml` and enforces a 100 character line
limit while ignoring the standard `E203`/`W503` whitespace conflicts.
