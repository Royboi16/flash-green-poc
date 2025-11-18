# flash-green-poc

Proof-of-concept flash-loan energy/futures arbitrage bot. The project glues
simulated or live power feeds, a loan adapter, and orchestration logic.  The
configuration system now validates all sensitive feature toggles and can source
secrets from HashiCorp Vault or AWS Secrets Manager.

**Core idea – cross-market, on-chain vs. futures arbitrage**

| Leg | Action | Venue | Why the mis-pricing exists |
| --- | --- | --- | --- |
| A | Buy tokenised renewable-kWh when the UK grid goes negative | Powerledger P2P pool (on-chain, 24×7) | UK spot power regularly flips negative in oversupply hours. |
| B | Sell the matching delivery window on ICE UK Baseload futures | ICE Futures Europe (T+0 fills) | Futures curves price to average demand hours and rarely turn negative, leaving a premium. |

Because Leg A settles instantly on-chain and Leg B fills at the matching engine, only short-lived cash is required until both
legs confirm—mirroring a flash-loan pattern.

## Configuration workflow

1. Pick the closest environment template (`env.staging.example` or
   `env.production.example`).
2. Copy it to `.env` (or the location you pass to `Settings`).
3. Fill in the placeholders for the features you are enabling. **`API_KEY` is
   mandatory**; the FastAPI app refuses to start if it is missing or empty.
4. Optional – point `SECRETS_BACKEND` at Vault or AWS Secrets Manager if you do
   not want secrets committed to disk.

`python-dotenv` is already wired up in `app/config.py`, so `poetry run python -m
app.orchestrator` will load the `.env` file automatically.

API endpoints that expose metrics or trading data require a shared secret in the
`X-API-Key` header. Set `API_KEY` in your `.env` (or secret manager) and pass it
with each request to `/metrics`, `/pnl`, `/trades`, and `/orders/open`. The API
will fail FastAPI initialisation if `API_KEY` is not set and will return `503`
for any request when the key is missing. The control-plane endpoints that
start/stop the orchestrator or run tests **refuse all requests** when `API_KEY`
is missing or incorrect and are rate limited with audit logging. See
`docs/deployment.md` for the minimum security checklist before exposing the
service.

## Local API + UI

Run the FastAPI server with uvicorn and open the bundled control panel at `/ui`:

```bash
poetry install
poetry run uvicorn app.web:api --host 0.0.0.0 --port 8000
```

Then browse to `http://localhost:8000/ui` to:

- Supply the API base URL and optional `X-API-Key` used for authenticated calls.
- Start/stop the orchestrator process (`python -m app.orchestrator`) with
  optional `KEY=VALUE` overrides for the env.
- Kick off `poetry run pytest` runs and view stdout/stderr inline.
- Fetch `/healthz`, `/pnl`, `/trades`, `/orders/open`, and `/metrics` data
  directly from the browser.

### One-click macOS starter

The repository ships with a macOS helper that applies the latest `git` changes,
runs `poetry install`, loads your `.env`, starts uvicorn in the background, and
opens the control panel:

```bash
./scripts/start_macos.sh
```

Notes:

- The script exits early with an actionable message when Poetry is not
  installed (install via `pipx install poetry` on macOS).
- It expects a populated `.env` in the repo root. Set `ENV_FILE=/path/to/.env`
  to point to a different file. A simple preflight enforces `API_KEY` by
  default; disable it with `PREFLIGHT=0` if you are only exploring the UI.
- Uvicorn logs stream to `logs/uvicorn_macos.log` and the PID is stored in
  `logs/uvicorn.pid`.

### Create a double-clickable macOS app

Wrap `scripts/start_macos.sh` in an Automator Application so operators can
launch the API + UI from a desktop icon:

1. Open **Automator** → **New Document** → choose **Application**.
2. Add a **Run Shell Script** action.
   - Shell: `/bin/bash`
   - Pass input: *to stdin*
   - Script contents:

     ```bash
     /bin/bash /ABSOLUTE/PATH/TO/flash-green-poc/scripts/start_macos.sh
     ```

3. Save the application as `Flash Green API.app` (e.g., in `~/Applications`).
4. Right-click the saved app → **Make Alias**, then drag the alias to your
   Desktop for one-click access to `http://localhost:8000/ui`.
5. Double-click the Desktop alias to pull the latest code, refresh dependencies,
   and open the control panel in your default browser.

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

The production chassis is **Powerledger + ICE**. The optional CCXT feed is just a sandbox path for developers who want to plug
in any liquid symbol (e.g., BTC/USDT) while exercising the orchestration loop; it does **not** route to power tokens.

| Toggle | Description | Required credentials |
| --- | --- | --- |
| `USE_LIVE_FEED` | Consume CCXT live data for dev/testing (not used for power tokens) | `LIVE_EXCHANGE`, `LIVE_SYMBOL`, `LIVE_API_KEY`, `LIVE_API_SECRET` |
| `USE_POWERLEDGER_LIVE` | Pull power-leg prices/orders from Powerledger | `POWERLEDGER_API_URL`, `POWERLEDGER_API_TOKEN`, `POWERLEDGER_ORG`, `POWERLEDGER_MARKET` |
| `USE_ICE_LIVE` | Route trades to the ICE adapter | `ICE_API_URL`, `ICE_API_KEY`, `ICE_API_SECRET`, `ICE_SYMBOL` |
| `USE_WEB3_LOAN` | Use the on-chain Hardhat/Web3 flash loan | `FLASH_LOAN_CONTRACT`, `FLASH_LOAN_RECEIVER`, `LENDER_KEY`, `HARDHAT_RPC` |

Trading cadence is governed by `TRADING_WINDOW_UTC` (default `05:00-21:00`) and
`ALLOW_WEEKEND_TRADING` (default `0`). The orchestrator will block cycles when
running outside the UTC window or during Saturday/Sunday if the weekend flag is
off.

Any missing credential raises a `ValueError` during `Settings` initialisation.
This prevents the orchestrator from starting if a release misses an env var –
including the mandatory `API_KEY`.

### Tests

Configuration regressions are caught via `pytest -k config`, which instantiates
`Settings` under multiple feature combinations.

## Operational runbooks (atomic energy-versus-futures arbitrage)

### Live Powerledger + ICE connectivity

1. Set `USE_POWERLEDGER_LIVE=1` and `USE_ICE_LIVE=1` in `.env`.
2. Populate Powerledger requirements:
   - `POWERLEDGER_API_URL` – e.g. `https://api.powerledger.io/trading` (or the
     UAT endpoint noted in `env.staging.example`).
   - `POWERLEDGER_API_TOKEN` – org-scoped bearer issued by Powerledger ops.
   - `POWERLEDGER_ORG` – trading org/desk identifier used on every order
     payload.
   - `POWERLEDGER_MARKET` – market code for the physical leg (example:
     `uk-grid-24h-ahead`).
3. Populate ICE live settings (`ICE_API_URL`, `ICE_API_KEY`, `ICE_API_SECRET`,
   `ICE_SYMBOL`). The live adapter polls
   `GET {ICE_API_URL}/marketdata/{ICE_SYMBOL}/price` and posts orders to
   `/orders`.
4. Confirm the trading window (`TRADING_WINDOW_UTC`) spans the desired desk
   hours, then start the orchestrator with `poetry run python -m
   app.orchestrator`.
5. Inspect `/healthz` and `/metrics` to verify Powerledger and ICE sessions are
   reachable before opening risk limits.

### Wholesale-CBDC settlement

1. Enable `USE_WEB3_LOAN=1` and point `HARDHAT_RPC` at the wholesale-CBDC node
   or sandbox RPC. For an Infura-style endpoint, keep HTTPS and ensure the
   backend supports flash-loan atomicity.
2. Set `FLASH_LOAN_CONTRACT` (deployed flash-loan contract),
   `FLASH_LOAN_RECEIVER` (TestReceiver or production receiver), and `LENDER_KEY`
   (custodied signing key with access to the CBDC settlement account).
3. Allocate sufficient CBDC float to the lender wallet to cover the
   `LOAN_LIMIT_GBP` setting (default £100k) plus gas.
4. When the orchestrator executes, the power-leg order is paired with the
   futures-leg exit and the CBDC loan in a single cycle. Failed CBDC settlement
   triggers the existing `trades_blocked` Prometheus counter and logs a
   stacktrace for triage.

### 24×7 monitoring and alerting

- Prometheus: scrape `METRICS_PORT` (default 8000 in staging, 9000 in prod).
  Alert on `trades_blocked` spikes, `profit_negative` growth, and exporter
  liveness. Suggested alert: no successful `trade executed` log line within
  10 minutes while markets are open.
- Logs: ship `app/logger` output to a central stack (e.g. Loki/ELK) with
  filters on `Powerledger` and `ICE` to catch intermittent HTTP failures.
- Health: `/healthz` should return 200; `/metrics` includes `daily_loss` and
  spread gauges used by Grafana dashboards. Add blackbox probes for the
  Powerledger and ICE base URLs noted above.

### Controls for weekend/after-hours execution

- `TRADING_WINDOW_UTC` constrains trading to a UTC window. Overnight windows are
  supported by specifying an end earlier than the start (e.g. `22:00-06:00`).
- `ALLOW_WEEKEND_TRADING=0` blocks cycles on Saturday/Sunday; set to `1` only
  when authorised for continuous operations.
- The orchestrator enforces both guards before reading market data, ensuring the
  atomic power-versus-futures loop cannot start outside authorised hours even if
  the process is left running unattended.
