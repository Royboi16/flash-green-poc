# flash-green-poc

Proof-of-concept flash-loan energy/futures arbitrage bot. The project glues
simulated or live power feeds, a loan adapter, and orchestration logic.  The
configuration system now validates all sensitive feature toggles and can source
secrets from HashiCorp Vault or AWS Secrets Manager.

## Configuration workflow

1. Pick the closest environment template (`env.staging.example` or
   `env.production.example`).
2. Copy it to `.env` (or the location you pass to `Settings`).
3. Fill in the placeholders for the features you are enabling.
4. Optional – point `SECRETS_BACKEND` at Vault or AWS Secrets Manager if you do
   not want secrets committed to disk.

`python-dotenv` is already wired up in `app/config.py`, so `poetry run python -m
app.orchestrator` will load the `.env` file automatically.

API endpoints that expose metrics or trading data require a shared secret in the
`X-API-Key` header. Set `API_KEY` in your `.env` (or secret manager) and pass it
with each request to `/metrics`, `/pnl`, `/trades`, and `/orders/open`.

### Environment templates

| File | When to use | Highlights |
| --- | --- | --- |
| `env.staging.example` | Dry-run / internal testing | Live feed + ICE disabled by default, secrets pulled from Vault, Prometheus binds to 8000 |
| `env.production.example` | Fully live trading | Enables live feeds, ICE and on-chain loan toggles; references AWS Secrets Manager |

Copy the right template and then edit the `LIVE_*`, `ICE_*`, and loan settings
as required. Comments in each template explain which values are required and who
issues them (e.g. trading desk vs. infra). Operators should never guess – the
placeholders match the validation errors raised by `Settings`.

### Secrets manager integration

`app/config.py` can hydrate sensitive values from Vault or AWS before
validating:

* `SECRETS_BACKEND=vault` – provide `VAULT_ADDR`, `VAULT_TOKEN`, and
  `VAULT_SECRET_PATH`. The secret at that path must be a KV-v2 document with
  keys matching the environment variable names (e.g. `LIVE_API_KEY`).
* `SECRETS_BACKEND=aws` – provide `AWS_SECRETS_REGION` and `AWS_SECRETS_ID`.
  The referenced secret must contain a JSON object with the same keys.

Only the fields listed below are fetched from a secret backend:
`LIVE_API_KEY`, `LIVE_API_SECRET`, `ICE_API_KEY`, `ICE_API_SECRET`,
`FLASH_LOAN_CONTRACT`, `FLASH_LOAN_RECEIVER`, `LENDER_KEY`, and `API_KEY`.

Validation runs **after** secrets are loaded, so misconfigured environments fail
fast with actionable error messages.

### Feature toggles

| Toggle | Description | Required credentials |
| --- | --- | --- |
| `USE_LIVE_FEED` | Consume CCXT live data | `LIVE_EXCHANGE`, `LIVE_SYMBOL`, `LIVE_API_KEY`, `LIVE_API_SECRET` |
| `USE_ICE_LIVE` | Route trades to the ICE adapter | `ICE_API_URL`, `ICE_API_KEY`, `ICE_API_SECRET`, `ICE_SYMBOL` |
| `USE_WEB3_LOAN` | Use the on-chain Hardhat/Web3 flash loan | `FLASH_LOAN_CONTRACT`, `FLASH_LOAN_RECEIVER`, `LENDER_KEY`, `HARDHAT_RPC` |

Any missing credential raises a `ValueError` during `Settings` initialisation.
This prevents the orchestrator from starting if a release misses an env var.

### Tests

Configuration regressions are caught via `pytest -k config`, which instantiates
`Settings` under multiple feature combinations.
