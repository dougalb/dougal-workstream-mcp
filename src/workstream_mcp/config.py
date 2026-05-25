from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkstreamConfig:
    db_path: Path
    export_dir: Path
    config_path: Path
    log_dir: Path | None


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

    return WorkstreamConfig(
        db_path=db_path,
        export_dir=export_dir,
        config_path=config_path,
        log_dir=log_dir,
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
