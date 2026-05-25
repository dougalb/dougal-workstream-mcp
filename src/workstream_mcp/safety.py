from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


ALLOWED_SECRET_REFERENCE_PREFIXES = ("1password://", "op://", "vault://")


@dataclass(frozen=True)
class SecretFinding:
    path: str
    kind: str


class SecretDetectedError(ValueError):
    def __init__(self, findings: list[SecretFinding]):
        self.findings = findings
        rendered = ", ".join(f"{finding.kind} at {finding.path}" for finding in findings)
        super().__init__(
            "Secret-like content was rejected. Store references only, such as "
            "1password://..., op://..., or vault://.... Findings: " + rendered
        )


SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    (
        "secret_assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|client[_-]?secret|oauth[_-]?secret|password|passwd|token|secret)\b"
            r"\s*[:=]\s*['\"]?[^\s'\"]{8,}"
        ),
    ),
]

HIGH_ENTROPY_CANDIDATE = re.compile(r"\b[A-Za-z0-9+/_=-]{40,}\b")


def _is_allowed_reference(value: str) -> bool:
    return value.strip().startswith(ALLOWED_SECRET_REFERENCE_PREFIXES)


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {char: value.count(char) for char in set(value)}
    return -sum((count / len(value)) * math.log2(count / len(value)) for count in counts.values())


def _has_multiple_character_classes(value: str) -> bool:
    classes = 0
    classes += any(char.islower() for char in value)
    classes += any(char.isupper() for char in value)
    classes += any(char.isdigit() for char in value)
    classes += any(not char.isalnum() for char in value)
    return classes >= 3


def _scan_string(value: str, path: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for kind, pattern in SECRET_PATTERNS:
        if pattern.search(value):
            findings.append(SecretFinding(path=path, kind=kind))

    for candidate in HIGH_ENTROPY_CANDIDATE.findall(value):
        if _is_allowed_reference(candidate):
            continue
        if _has_multiple_character_classes(candidate) and _entropy(candidate) >= 4.5:
            findings.append(SecretFinding(path=path, kind="high_entropy_secret"))
            break

    return findings


def _scan_value(value: Any, path: str) -> list[SecretFinding]:
    if isinstance(value, str):
        return _scan_string(value, path)
    if isinstance(value, Mapping):
        findings: list[SecretFinding] = []
        for key, item in value.items():
            findings.extend(_scan_value(item, f"{path}.{key}"))
        return findings
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        findings = []
        for index, item in enumerate(value):
            findings.extend(_scan_value(item, f"{path}[{index}]"))
        return findings
    return []


def assert_safe_to_store(payload: Any) -> None:
    findings = _scan_value(payload, "$")
    if findings:
        raise SecretDetectedError(findings)
