from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class WorkstreamConfig:
    db_path: Path
    export_dir: Path
    config_path: Path
    log_dir: Path | None
    public_base_url: str
    auth_mode: str
    oauth_issuer: str | None
    oauth_audience: str | None
    oauth_jwks_url: str | None
    oauth_authorization_url: str | None
    oauth_token_url: str | None
    oauth_client_id: str | None
    trust_proxy_headers: bool
    allowed_hosts: list[str]


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        import yaml
    except ImportError:
        logging.getLogger(__name__).warning("PyYAML is not installed; ignoring %s", path)
        return {}

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _config_value(file_config: dict[str, Any], env_name: str, key: str, default: Any = None) -> Any:
    return os.environ.get(env_name, file_config.get(key, default))


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _clean_url(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.rstrip("/") if text else None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _host_values(public_base_url: str) -> list[str]:
    parsed = urlparse(public_base_url)
    netloc = parsed.netloc
    hostname = parsed.hostname
    values = ["localhost", "localhost:8000", "127.0.0.1", "127.0.0.1:8000"]
    if netloc:
        values.append(netloc)
    if hostname:
        values.append(hostname)
    return list(dict.fromkeys(values))


def load_config() -> WorkstreamConfig:
    config_path = Path(os.environ.get("WORKSTREAM_CONFIG_PATH", "/config/workstream.yaml"))
    file_config = _read_config_file(config_path)

    db_path = Path(
        os.environ.get(
            "WORKSTREAM_DB_PATH",
            str(file_config.get("db_path", ".workstream/workstream.db")),
        )
    )
    export_dir = Path(
        os.environ.get(
            "WORKSTREAM_EXPORT_DIR",
            str(file_config.get("export_dir", "exports")),
        )
    )
    log_dir_value = os.environ.get("WORKSTREAM_LOG_DIR", file_config.get("log_dir"))
    log_dir = Path(log_dir_value) if log_dir_value else None
    auth_mode = str(_config_value(file_config, "WORKSTREAM_AUTH_MODE", "auth_mode", "none")).strip().lower()
    if auth_mode not in {"none", "oauth"}:
        auth_mode = "none"

    public_base_url = (
        _clean_url(_config_value(file_config, "WORKSTREAM_PUBLIC_BASE_URL", "public_base_url", "http://localhost:8000"))
        or "http://localhost:8000"
    )
    allowed_hosts = _host_values(public_base_url)
    allowed_hosts.extend(_as_list(_config_value(file_config, "WORKSTREAM_ALLOWED_HOSTS", "allowed_hosts")))

    return WorkstreamConfig(
        db_path=db_path,
        export_dir=export_dir,
        config_path=config_path,
        log_dir=log_dir,
        public_base_url=public_base_url,
        auth_mode=auth_mode,
        oauth_issuer=_clean_url(_config_value(file_config, "WORKSTREAM_OAUTH_ISSUER", "oauth_issuer")),
        oauth_audience=_clean_url(_config_value(file_config, "WORKSTREAM_OAUTH_AUDIENCE", "oauth_audience")),
        oauth_jwks_url=_clean_url(_config_value(file_config, "WORKSTREAM_OAUTH_JWKS_URL", "oauth_jwks_url")),
        oauth_authorization_url=_clean_url(
            _config_value(file_config, "WORKSTREAM_OAUTH_AUTHORIZATION_URL", "oauth_authorization_url")
        ),
        oauth_token_url=_clean_url(_config_value(file_config, "WORKSTREAM_OAUTH_TOKEN_URL", "oauth_token_url")),
        oauth_client_id=_clean_url(_config_value(file_config, "WORKSTREAM_OAUTH_CLIENT_ID", "oauth_client_id")),
        trust_proxy_headers=_as_bool(
            _config_value(file_config, "WORKSTREAM_TRUST_PROXY_HEADERS", "trust_proxy_headers", False)
        ),
        allowed_hosts=list(dict.fromkeys(allowed_hosts)),
    )


def configure_logging(config: WorkstreamConfig | None = None) -> None:
    config = config or load_config()
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if config.log_dir is not None:
        config.log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(config.log_dir / "workstream.log", encoding="utf-8"))

    logging.basicConfig(
        level=os.environ.get("WORKSTREAM_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )
