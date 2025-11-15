# flash-green-poc

This repository contains a proof-of-concept flash-loan arbitrage bot that combines
on-chain data with exchange data to explore green energy trades.

## Development setup

The project targets Python 3.11 and works best when you point Poetry at a
system-wide interpreter instead of relying on pyenv shims. Ensure the following
prerequisites are available:

- Python 3.11 (including the `python3.11-venv` and `python3.11-dev` packages so
  native dependencies such as `cryptography`, `llvmlite`, and `numba` can build)
- Poetry 1.4 or newer

On Ubuntu 24.04+, you can install Python 3.11 from the deadsnakes PPA:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install python3.11 python3.11-venv python3.11-dev
```

With those prerequisites satisfied, bootstrap the project like so:

```bash
cd flash-green-poc
poetry env use python3.11
poetry install --with dev
```

Running `poetry install --with dev` after a clean checkout has been verified to
succeed with the prerequisites above.

Finally, run the FastAPI/worker stack as needed via `docker compose` (see the
environment manifests for details).

## Linting with Flake8

Pull requests are now validated with `flake8`. Run the linter locally before
submitting patches:

```bash
poetry run flake8
```

The configuration lives in `pyproject.toml` and enforces a 100 character line
limit while ignoring the standard `E203`/`W503` whitespace conflicts.
