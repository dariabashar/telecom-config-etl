"""Readers for CSV, Excel, JSON and XML. Every reader returns (columns, records) where
records is a list of flat dicts of raw values (strings or None) - no business logic here."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as ET  # safe against entity-expansion attacks
from openpyxl import load_workbook

from .config import SourceConfig

Record = dict[str, Any]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # Excel stores 1000 as 1000.0
    return str(value)


def read_csv(path: Path, cfg: SourceConfig) -> tuple[list[str], list[Record]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, delimiter=cfg.delimiter)
        records = [{k: _text(v) for k, v in row.items() if k is not None} for row in reader]
        return list(reader.fieldnames or []), records


def read_excel(path: Path, cfg: SourceConfig) -> tuple[list[str], list[Record]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook[cfg.sheet] if cfg.sheet else workbook.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        header = [str(c).strip() if c is not None else "" for c in next(rows, ())]
        records = [
            {h: _text(v) for h, v in zip(header, row) if h}
            for row in rows
            if any(v is not None for v in row)
        ]
        return [h for h in header if h], records
    finally:
        workbook.close()


def read_json(path: Path, cfg: SourceConfig) -> tuple[list[str], list[Record]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data[cfg.root_key] if cfg.root_key else data
    if not isinstance(items, list):
        raise ValueError(f"{path.name}: expected a list of records")
    records: list[Record] = []
    for item in items:
        if cfg.explode:
            parent = {k: _text(item.get(k)) for k in cfg.inherit}
            for child in item.get(cfg.explode) or []:
                records.append({**parent, **{k: _text(v) for k, v in child.items()}})
        else:
            records.append({k: _text(v) for k, v in item.items()})
    columns = sorted({k for r in records for k in r})
    return columns, records


def read_xml(path: Path, cfg: SourceConfig) -> tuple[list[str], list[Record]]:
    root = ET.parse(path).getroot()
    records: list[Record] = []
    for element in root.findall(cfg.record_xpath):
        record: Record = dict(element.attrib)                  # <node hostname="...">
        for child in element:                                  # <vendor>...</vendor>
            record[child.tag] = child.text.strip() if child.text else None
        records.append(record)
    columns = sorted({k for r in records for k in r})
    return columns, records


READERS = {"csv": read_csv, "excel": read_excel, "json": read_json, "xml": read_xml}


def extract(path: Path, cfg: SourceConfig) -> tuple[list[str], list[Record]]:
    return READERS[cfg.format](path, cfg)
