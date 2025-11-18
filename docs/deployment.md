# Deployment and Access Controls

These steps harden the Flash-Green API before exposing it to any operators.

## Configure authentication

- **Set `API_KEY`** in the runtime environment before starting the FastAPI service. The API will fail to initialize without it, and a misconfigured deployment returns `503` for all dependency-injected routes. Requests that mutate state (e.g., orchestrator start/stop, test execution) are rejected when the header `X-API-Key` is missing or does not match `API_KEY`.
- If you use stronger auth (mTLS, OIDC), enforce it at the proxy or ingress layer and keep the API key check enabled as a defense in depth unless you explicitly replace it.

## Service startup checklist

1. Populate a secrets store or deployment environment with `API_KEY=<strong random value>`; deployments without it fail FastAPI startup.
2. Ensure only trusted operators can reach the API service port (network ACLs/firewalls).
3. If running behind a reverse proxy, forward the `X-API-Key` header and mTLS/OIDC identity to the FastAPI backend.
4. Apply rate limits at the edge if available; the API also enforces per-identity limits on control-plane actions.

## Operational notes

- Control-plane endpoints log audit events for orchestrator start/stop and test execution, including the authenticated key identifier and client address.
- Requests exceeding the configured per-identity rate window receive HTTP 429 responses; expand or externalize rate limiting at your ingress if higher throughput is needed.
