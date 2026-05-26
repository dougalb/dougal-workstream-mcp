# Codex Prompt: Build External NGINX Stack for dougal-workstream-mcp

You are working in a separate infrastructure repository. Create an external NGINX reverse-proxy stack for `dougal-workstream-mcp`.

## Goal

Expose a private `dougal-workstream-mcp` container to the public internet through HTTPS while preserving MCP Streamable HTTP and SSE behavior. NGINX is managed in this infrastructure repo, not in the `dougal-workstream-mcp` app repo.

## Upstream Contract

The application listens on the Docker host at:

```text
http://127.0.0.1:8000
```

Proxy these paths unchanged:

- `/mcp`
- `/sse`
- `/messages/`
- `/.well-known/oauth-protected-resource`
- `/healthz`
- `/readyz`

Preserve these headers:

- `Authorization`
- `Host`
- `X-Forwarded-Proto`
- `X-Forwarded-Host`
- `X-Forwarded-For`

## Required Proxy Behavior

- Terminate HTTPS for the chosen public domain.
- Use HTTP/1.1 to the upstream.
- Disable proxy buffering for `/mcp`, `/sse`, and `/messages/`.
- Use long proxy read/send timeouts for streaming endpoints.
- Support Server-Sent Events.
- Do not store TLS private keys, OAuth client secrets, provider secrets, bearer tokens, or API keys in git.
- Keep NGINX authentication optional. App-level OAuth remains enforced by `dougal-workstream-mcp`.
- Forward the `Authorization` header intact so the app can verify Bearer JWTs.

## App Environment Expected

The app container should be configured separately with:

```bash
WORKSTREAM_PUBLIC_BASE_URL=https://YOUR_PUBLIC_DOMAIN
WORKSTREAM_TRUST_PROXY_HEADERS=true
WORKSTREAM_AUTH_MODE=oauth
WORKSTREAM_OAUTH_ISSUER=https://YOUR_AUTH_ISSUER
WORKSTREAM_OAUTH_AUDIENCE=https://YOUR_PUBLIC_DOMAIN
WORKSTREAM_OAUTH_JWKS_URL=https://YOUR_AUTH_ISSUER/.well-known/jwks.json
```

The OAuth provider must issue tokens whose issuer, audience/resource, expiry, and scopes can be verified by the app.

## Deliverables

- NGINX config or compose stack suitable for this host.
- Clear volume layout for certs/logs/config.
- Healthcheck instructions using `/healthz` and `/readyz`.
- A short README explaining how to point the public domain at the proxy and validate `/mcp`, `/sse`, and `/.well-known/oauth-protected-resource`.

Do not modify the `dougal-workstream-mcp` application repository.
