"""Loads config/sources.yaml - the list of files to ingest and how their columns map to canonical fields."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .entities import ENTITIES

FORMATS = {"csv", "excel", "json", "xml"}


@dataclass
class SourceConfig:
    path: str                      # relative to the data directory; also the identity of the source
    format: str
    entity: str
    mapping: dict[str, str]        # canonical field -> column / key / tag name in the source
    close_missing: bool = False    # close versions whose key vanished from this source
    # format specific options
    sheet: str | None = None       # excel
    delimiter: str = ","           # csv
    root_key: str | None = None    # json: key holding the list of records (None = top-level list)
    explode: str | None = None     # json: nested list to flatten into one record per element
    inherit: list[str] = field(default_factory=list)  # json: parent keys copied into each child
    record_xpath: str | None = None  # xml: xpath of one record element


def load_sources(config_path: str | Path) -> list[SourceConfig]:
    raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    sources = []
    for item in raw.get("sources", []):
        cfg = SourceConfig(**item)
        if cfg.format not in FORMATS:
            raise ValueError(f"{cfg.path}: unsupported format '{cfg.format}'")
        if cfg.entity not in ENTITIES:
            raise ValueError(f"{cfg.path}: unknown entity '{cfg.entity}'")
        if cfg.format == "xml" and not cfg.record_xpath:
            raise ValueError(f"{cfg.path}: xml sources need record_xpath")
        spec = ENTITIES[cfg.entity]
        unknown = set(cfg.mapping) - set(spec.all_fields)
        if unknown:
            raise ValueError(f"{cfg.path}: mapping has unknown fields {sorted(unknown)}")
        sources.append(cfg)
    return sources
