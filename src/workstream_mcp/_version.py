from __future__ import annotations

from importlib import metadata
from pathlib import Path
import tomllib

PACKAGE_NAME = "dougal-workstream-mcp"


def get_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return _version_from_pyproject() or "0+unknown"


def _version_from_pyproject() -> str | None:
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if not pyproject.exists():
            continue
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        version = data.get("project", {}).get("version")
        return version if isinstance(version, str) else None
    return None


__version__ = get_version()
