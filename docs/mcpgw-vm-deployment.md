# mcpgw-vm Deployment Runtime

This repository remains the Workstreams MCP application source. The public edge,
Keycloak realm, TLS certificates, and nginx gateway live outside this repository.
This document records the expected application container runtime on `mcpgw-vm`
without storing secrets.

## Runtime Shape

The deployed service uses the same Docker image in two containers:

| Container | Purpose | Auth mode | Exposure |
| --- | --- | --- | --- |
| `workstream-mcp` | LAB/private MCP endpoint for direct operational checks | `none` | `10.10.10.20:8000 -> 8000/tcp` |
| `workstream-mcp-public` | Public ChatGPT/OAuth MCP endpoint behind nginx | `oauth` | Docker-network-only upstream for `mcpgw-public-gateway` |

Both containers should:

- run the same `dougal-workstream-mcp:<version>` image tag;
- attach to the `mcpgw_default` Docker network;
- use restart policy `unless-stopped`;
- mount the shared `workstream-data` Docker volume at `/data`;
- mount `/home/dougalb/workstream-exports` at `/exports`;
- mount `/home/dougalb/workstream-config` at `/config:ro`;
- mount `/home/dougalb/workstream-logs` at `/logs`;
- run `workstream serve --transport http --host 0.0.0.0 --port 8000`;
- use the container healthcheck against `http://127.0.0.1:8000/healthz`.

The shared SQLite database remains the source of truth in `/data/workstream.db`.
The two containers are separate MCP surfaces over the same ledger, not separate
databases.

## LAB Container

`workstream-mcp` is the no-auth private endpoint used for controlled LAN/LAB
verification.

Expected non-secret environment:

```text
WORKSTREAM_AUTH_MODE=none
WORKSTREAM_PUBLIC_BASE_URL=http://10.10.10.20:8000
WORKSTREAM_ALLOWED_HOSTS=10.10.10.20,10.10.10.20:8000,mcpgw-vm,localhost,localhost:8000,127.0.0.1,127.0.0.1:8000
WORKSTREAM_TRUST_PROXY_HEADERS=false
WORKSTREAM_DB_PATH=/data/workstream.db
WORKSTREAM_EXPORT_DIR=/exports
WORKSTREAM_CONFIG_PATH=/config/workstream.yaml
```

Expected direct checks:

```bash
curl -sS http://10.10.10.20:8000/readyz
curl -sS -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -X POST http://10.10.10.20:8000/mcp \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"verify","version":"1"}}}'
```

## Public OAuth Container

`workstream-mcp-public` is the OAuth-protected MCP endpoint used by ChatGPT and
other public MCP clients. It is not published directly on a host port; nginx in
`mcpgw-public-gateway` forwards public traffic to this container on the
`mcpgw_default` network.

Expected non-secret environment:

```text
WORKSTREAM_AUTH_MODE=oauth
WORKSTREAM_PUBLIC_BASE_URL=https://mcpgw.dmz.dougal.io
WORKSTREAM_ALLOWED_HOSTS=mcpgw.dmz.dougal.io,mcpgw.dmz.dougal.io:443,10.10.10.20,10.10.10.20:3000,workstream-mcp-public,workstream-mcp-public:8000,localhost,localhost:8000,127.0.0.1,127.0.0.1:8000
WORKSTREAM_TRUST_PROXY_HEADERS=true
WORKSTREAM_OAUTH_ISSUER=https://mcpgw.dmz.dougal.io/keycloak/realms/workstream
WORKSTREAM_OAUTH_AUDIENCE=https://mcpgw.dmz.dougal.io
WORKSTREAM_OAUTH_JWKS_URL=https://mcpgw.dmz.dougal.io/keycloak/realms/workstream/protocol/openid-connect/certs
WORKSTREAM_OAUTH_AUTHORIZATION_URL=https://mcpgw.dmz.dougal.io/keycloak/realms/workstream/protocol/openid-connect/auth
WORKSTREAM_OAUTH_TOKEN_URL=https://mcpgw.dmz.dougal.io/keycloak/realms/workstream/protocol/openid-connect/token
WORKSTREAM_OAUTH_CLIENT_ID=chatgpt-workstream
WORKSTREAM_DB_PATH=/data/workstream.db
WORKSTREAM_EXPORT_DIR=/exports
WORKSTREAM_CONFIG_PATH=/config/workstream.yaml
```

Expected public checks:

```bash
curl -sS https://mcpgw.dmz.dougal.io/readyz
curl -sSI https://mcpgw.dmz.dougal.io/mcp
curl -sS https://mcpgw.dmz.dougal.io/.well-known/oauth-protected-resource
```

The unauthenticated `/mcp` response should be `401 Unauthorized` with a
`WWW-Authenticate` header pointing at
`https://mcpgw.dmz.dougal.io/.well-known/oauth-protected-resource`.

## Deploy Checklist

Use this sequence when deploying a new application image:

1. Build the new image from the committed application checkout.
2. Recreate `workstream-mcp` with the same LAB environment, network, mounts, and
   port binding.
3. Recreate `workstream-mcp-public` with the same OAuth environment, network,
   and mounts.
4. Restart `mcpgw-public-gateway` so nginx reconnects to the recreated public
   upstream container.
5. Verify both containers are healthy.
6. Verify LAB `/readyz`, public `/readyz`, and public `/mcp` OAuth challenge.
7. Verify MCP `initialize` reports the expected server version.
8. Verify `tools/list` advertises the expected Apps UI metadata and
   `resources/list` includes current and compatibility `ui://` resources.

Do not commit browser HAR files, OAuth tokens, bearer tokens, TLS private keys,
Keycloak admin credentials, database snapshots, or raw private records. If a HAR
is temporarily needed for diagnosis, keep it untracked and delete it when no
longer needed.
