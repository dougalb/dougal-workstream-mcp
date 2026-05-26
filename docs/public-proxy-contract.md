# Public Proxy Contract

`dougal-workstream-mcp` does not manage the public reverse proxy. Run the container on a private or host-local port and place an external HTTPS proxy in front of it.

## Upstream

Default local upstream:

```text
http://127.0.0.1:8000
```

The compose file binds the container to `127.0.0.1:8000:8000` by default so it is not directly exposed on every host interface.

## Required Paths

Forward these paths to the upstream unchanged:

- `/mcp`
- `/sse`
- `/messages/`
- `/.well-known/oauth-protected-resource`
- `/healthz`
- `/readyz`

`/mcp` is the primary Streamable HTTP MCP endpoint. `/sse` and `/messages/` are the SSE compatibility endpoints.

## Required Headers

Preserve these request headers:

- `Authorization`
- `Host`
- `X-Forwarded-Proto`
- `X-Forwarded-Host`
- `X-Forwarded-For`

Set `WORKSTREAM_PUBLIC_BASE_URL` to the public HTTPS origin, for example `https://workstream.example.com`.

Set `WORKSTREAM_TRUST_PROXY_HEADERS=true` only when the proxy is trusted and forwards correct `X-Forwarded-*` headers.

## Streaming Requirements

The proxy must not buffer MCP/SSE responses. Configure long read/send timeouts for:

- `/mcp`
- `/sse`
- `/messages/`

The proxy must support Server-Sent Events and long-lived HTTP responses.

## Authentication Boundary

NGINX or another reverse proxy may add optional IP allowlists, mTLS, or additional authentication. That is not a replacement for app-level OAuth.

When `WORKSTREAM_AUTH_MODE=oauth`, the application verifies Bearer JWTs on protected MCP paths and requires:

- `workstream.read` for MCP access.
- `workstream.write` for write tools.
- `workstream.sensitive` for sensitive rows to appear in ChatGPT-facing structured output.

The reverse proxy must forward the `Authorization` header intact.

## Healthchecks

Use unauthenticated health endpoints:

- `GET /healthz`
- `GET /readyz`

Both return JSON and verify SQLite readability/writability.

## Secrets

Do not store TLS private keys, OAuth client secrets, provider secrets, or bearer tokens in this repository. Store only references such as `op://...`, `1password://...`, or `vault://...` where needed.
