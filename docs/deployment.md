# Deployment and Access Controls

These steps harden the Flash-Green API before exposing it to any operators.

## Configure authentication

- **Set `API_KEY`** in the runtime environment before starting the FastAPI service. The API will fail to initialize without it, and a misconfigured deployment returns `503` for all dependency-injected routes. Requests that mutate state (e.g., orchestrator start/stop, test execution) are rejected when the header `X-API-Key` is missing or does not match `API_KEY`.
- **Choose an identity provider**: the API refuses to start unless at least one of the following is configured:
  - **OIDC/JWT**: set `OIDC_ISSUER`, `OIDC_AUDIENCE`, and `OIDC_JWKS_URL`. Tokens must present the configured audience and issuer; roles/scopes in the token are mapped to FastAPI permissions. Override allowed algorithms with `OIDC_ALLOWED_ALGS` if your issuer requires it.
  - **mTLS**: terminate TLS at the ingress and forward the verified subject/CN with `CLIENT_CERT_SUBJECT_HEADER`. Restrict access using `MTLS_ALLOWED_SUBJECTS` (comma-separated) and grant roles with `MTLS_ASSIGNED_ROLES`.
- **API key remains in force** as a defense-in-depth control: identity (OIDC or mTLS) is verified before the `X-API-Key` check is evaluated.

## TLS termination and HTTPS enforcement

- Require HTTPS for all callers (`REQUIRE_HTTPS=1`). When running behind a proxy, set `FORWARDED_PROTO_HEADER` to the header that conveys the original scheme (default: `x-forwarded-proto`).
- Terminate TLS either at the service (`TLS_CERTFILE`, `TLS_KEYFILE`, optional `TLS_CLIENT_CA` for local mTLS) or at an ingress/gateway. If TLS is offloaded, ensure the ingress passes the client certificate subject header for mTLS enforcement and blocks plaintext traffic.
 
## Scope control-plane access

- Control-plane routes (`/ui/services/*`, `/ui/tests/run`) are restricted to principals whose roles intersect `CONTROL_PLANE_ROLES` (default `admin`). Use `MTLS_ASSIGNED_ROLES` or OIDC role/scopes to grant access to operators.
- Audit logs now include structured principal metadata (subject, roles, auth_method, client address) for each control-plane action.

## Service startup checklist

1. Populate a secrets store or deployment environment with `API_KEY=<strong random value>`; deployments without it fail FastAPI startup.
2. Ensure only trusted operators can reach the API service port (network ACLs/firewalls).
3. If running behind a reverse proxy, forward the `X-API-Key` header and mTLS/OIDC identity to the FastAPI backend.
4. Apply rate limits at the edge if available; the API also enforces per-identity limits on control-plane actions.

## Operational notes

- Control-plane endpoints log audit events for orchestrator start/stop and test execution, including the authenticated key identifier and client address.
- Requests exceeding the configured per-identity rate window receive HTTP 429 responses; expand or externalize rate limiting at your ingress if higher throughput is needed.
