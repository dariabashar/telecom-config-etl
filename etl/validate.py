"""Mapping + validation of raw records into canonical, typed records.

Checks done here (per file):
  completeness  - mapped source columns exist; required fields are filled
  correctness   - every field parses (IP, hostname, enums, speeds ...)
  integrity     - duplicate keys inside the file are rejected
Cross-table checks (unknown device, key owned by another source) happen in load.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import SourceConfig
from .entities import ENTITIES, EntitySpec


@dataclass
class Issue:
    entity: str
    rule: str
    message: str
    row_number: int | None = None
    key: str | None = None
    field: str | None = None
    raw: dict[str, Any] | None = None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def missing_columns(cfg: SourceConfig, columns: list[str]) -> list[str]:
    """Mapped source columns that are not present in the file at all."""
    return sorted({src for src in cfg.mapping.values() if src not in columns})


def key_text(spec: EntitySpec, record: dict[str, Any]) -> str:
    return "/".join(str(record[k]) for k in spec.keys)


def validate_records(
    cfg: SourceConfig, raw_records: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[Issue]]:
    spec = ENTITIES[cfg.entity]
    valid: list[dict[str, Any]] = []
    issues: list[Issue] = []
    seen: dict[str, int] = {}

    for index, raw in enumerate(raw_records, start=1):
        record: dict[str, Any] = {}
        problems: list[Issue] = []
        for name in spec.all_fields:
            source_col = cfg.mapping.get(name)
            value = _clean(raw.get(source_col)) if source_col else None
            field = spec.fields[name]
            if value is None:
                if field.required:
                    problems.append(Issue(spec.name, "required", f"'{name}' is empty", index, field=name))
                record[name] = None
                continue
            try:
                record[name] = field.parse(value)
            except ValueError as exc:
                record[name] = None
                problems.append(Issue(spec.name, "format", str(exc), index, field=name))

        if not problems:
            key = key_text(spec, record)
            if key in seen:
                problems.append(
                    Issue(spec.name, "duplicate_key", f"'{key}' already appears in row {seen[key]}", index)
                )
            else:
                seen[key] = index

        if problems:
            key = key_text(spec, record) if all(record.get(k) for k in spec.keys) else None
            for problem in problems:
                problem.key, problem.raw = key, raw
            issues.extend(problems)
        else:
            valid.append(record)

    return valid, issues
