# Operations Runbook

This runbook captures the actions and expectations for shipping and operating Flash Green across environments.

## Preflight and rollout
1. **Populate environment variables** using the appropriate template (`env.staging.example` or `env.production.example`). Ensure the following are present before rollout:
   - `API_KEY` plus either `CLIENT_CERT_SUBJECT_HEADER` or the `OIDC_ISSUER`/`OIDC_AUDIENCE` pair.
   - Database coordinates (`DATABASE_URL` or the `DB_*` trio), and any live adapters you plan to enable (`USE_LIVE_FEED`, `USE_ICE_LIVE`, `USE_POWERLEDGER_LIVE`, `USE_WEB3_LOAN`).
   - Secret backend settings when used: `VAULT_ADDR`/`VAULT_TOKEN`/`VAULT_SECRET_PATH` for Vault, or `AWS_SECRETS_REGION`/`AWS_SECRETS_ID` for AWS.
2. **Run the preflight validator** before the first pod/task starts:
   ```bash
   python scripts/preflight_check.py --env-file /path/to/.env
   ```
   This fails fast if critical env vars are empty, secrets cannot be loaded, or the database is unreachable.
3. **Deploy** (Helm/k8s, ECS task, or Docker Compose). The container entrypoint also executes the same preflight before applying migrations and launching services.

## Rollback
1. Stop the newly deployed task/pod version and redeploy the last known-good image tag (e.g., `:previous` or a pinned SHA).
2. If migrations were applied, use Alembic to downgrade to the prior revision:
   ```bash
   alembic downgrade -1
   ```
3. Verify the service returns healthy status and reconciles order flows before re-opening traffic.

## Logging and metrics
- **Application logs:** emitted to stdout/stderr and collected by the platform log shipper (e.g., Kubernetes sidecar or ECS FireLens). Ensure log routing points to the central SIEM/observability stack used by your environment.
- **Metrics:** Prometheus-format metrics are exposed on `:${METRICS_PORT:-8000}/metrics`. Scrape via Prometheus/Grafana Agent or configure an OpenMetrics scrape in your collector.

## Database backup/restore
- **Engine:** PostgreSQL is the default managed database. Use your platform backup tooling (e.g., RDS snapshots) or scheduled `pg_dump` exports.
- **Ad-hoc backup:**
  ```bash
  pg_dump "$DATABASE_URL" > flash-green-backup.sql
  ```
- **Restore:**
  ```bash
  psql "$DATABASE_URL" < flash-green-backup.sql
  ```
- **Validation:** After restores, rerun `python scripts/preflight_check.py` to ensure connectivity and launch the service in read-only mode to confirm data integrity before resuming trading.
