from __future__ import annotations

import contextvars
import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier

from .config import WorkstreamConfig, load_config

READ_SCOPE = "workstream.read"
WRITE_SCOPE = "workstream.write"
SENSITIVE_SCOPE = "workstream.sensitive"
SUPPORTED_SCOPES = [READ_SCOPE, WRITE_SCOPE, SENSITIVE_SCOPE]

_current_access_token: contextvars.ContextVar[AccessToken | None] = contextvars.ContextVar(
    "workstream_access_token",
    default=None,
)


@dataclass(frozen=True)
class OAuthChallenge:
    resource_metadata_url: str
    scope: str = READ_SCOPE

    def header_value(self) -> str:
        return f'Bearer resource_metadata="{self.resource_metadata_url}", scope="{self.scope}"'


def oauth_enabled(config: WorkstreamConfig | None = None) -> bool:
    return (config or load_config()).auth_mode == "oauth"


def protected_resource_metadata(config: WorkstreamConfig | None = None) -> dict[str, Any]:
    config = config or load_config()
    if config.auth_mode != "oauth":
        return {
            "resource": config.public_base_url,
            "authorization_servers": [],
            "scopes_supported": [],
        }
    _validate_oauth_config(config)
    return {
        "resource": config.oauth_audience or config.public_base_url,
        "authorization_servers": [config.oauth_issuer],
        "scopes_supported": SUPPORTED_SCOPES,
    }


def oauth_challenge(config: WorkstreamConfig | None = None, scope: str = READ_SCOPE) -> OAuthChallenge:
    config = config or load_config()
    return OAuthChallenge(
        resource_metadata_url=f"{config.public_base_url}/.well-known/oauth-protected-resource",
        scope=scope,
    )


def current_access_token() -> AccessToken | None:
    return _current_access_token.get()


def current_scopes() -> set[str]:
    token = current_access_token()
    return set(token.scopes) if token else set()


def has_scope(scope: str) -> bool:
    token = current_access_token()
    if token is not None:
        return scope in set(token.scopes)
    return not oauth_enabled()


def require_scope(scope: str) -> None:
    token = current_access_token()
    if token is None and not oauth_enabled():
        return
    if token is None or scope not in set(token.scopes):
        raise PermissionError(f"Missing required OAuth scope: {scope}")


def set_current_access_token(access_token: AccessToken | None):
    return _current_access_token.set(access_token)


def reset_current_access_token(token) -> None:
    _current_access_token.reset(token)


def _validate_oauth_config(config: WorkstreamConfig) -> None:
    missing = [
        name
        for name, value in {
            "WORKSTREAM_PUBLIC_BASE_URL": config.public_base_url,
            "WORKSTREAM_OAUTH_ISSUER": config.oauth_issuer,
            "WORKSTREAM_OAUTH_AUDIENCE": config.oauth_audience,
            "WORKSTREAM_OAUTH_JWKS_URL": config.oauth_jwks_url,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"OAuth mode requires: {', '.join(missing)}")


def _scopes_from_payload(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("scope", payload.get("scp", payload.get("scopes", [])))
    if isinstance(raw, str):
        return [scope for scope in raw.split() if scope]
    if isinstance(raw, list):
        return [str(scope) for scope in raw if str(scope)]
    return []


def _matches_audience(payload: dict[str, Any], audience: str) -> bool:
    raw_audience = payload.get("aud")
    audiences = raw_audience if isinstance(raw_audience, list) else [raw_audience]
    return audience in audiences or payload.get("resource") == audience


def _load_jwks(jwks_url: str) -> dict[str, Any]:
    parsed = urlparse(jwks_url)
    if parsed.scheme == "file":
        return json.loads(Path(parsed.path).read_text(encoding="utf-8"))
    with urllib.request.urlopen(jwks_url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


class JWTTokenVerifier(TokenVerifier):
    def __init__(self, config: WorkstreamConfig | None = None):
        self.config = config or load_config()
        _validate_oauth_config(self.config)
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_loaded_at = 0.0

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            payload = self.verify_claims(token)
        except jwt.PyJWTError:
            return None
        except (OSError, ValueError, KeyError):
            return None

        scopes = _scopes_from_payload(payload)
        return AccessToken(
            token=token,
            client_id=str(payload.get("client_id") or payload.get("azp") or payload.get("sub") or "unknown"),
            scopes=scopes,
            expires_at=payload.get("exp"),
            resource=str(payload.get("resource") or self.config.oauth_audience),
        )

    def verify_claims(self, token: str) -> dict[str, Any]:
        if not self.config.oauth_issuer or not self.config.oauth_audience or not self.config.oauth_jwks_url:
            raise ValueError("OAuth verifier is not fully configured")

        key = self._signing_key(token)
        payload = jwt.decode(
            token,
            key=key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            issuer=self.config.oauth_issuer,
            options={"verify_aud": False},
            leeway=30,
        )
        if not _matches_audience(payload, self.config.oauth_audience):
            raise jwt.InvalidAudienceError("Token audience/resource does not match this MCP server")
        return payload

    def _jwks(self) -> dict[str, Any]:
        now = time.time()
        if self._jwks_cache is None or now - self._jwks_loaded_at > 300:
            if not self.config.oauth_jwks_url:
                raise ValueError("JWKS URL is not configured")
            self._jwks_cache = _load_jwks(self.config.oauth_jwks_url)
            self._jwks_loaded_at = now
        return self._jwks_cache

    def _signing_key(self, token: str) -> Any:
        header = jwt.get_unverified_header(token)
        key_id = header.get("kid")
        for jwk in self._jwks().get("keys", []):
            if jwk.get("kid") == key_id:
                return jwt.PyJWK.from_dict(jwk).key
        raise jwt.InvalidTokenError("Token signing key was not found in JWKS")
