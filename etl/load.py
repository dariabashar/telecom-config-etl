"""Type 2 SCD loader: keeps the full history of every device and interface."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql

from .entities import EntitySpec
from .validate import Issue, key_text


@dataclass
class LoadCounts:
    inserted: int = 0
    changed: int = 0
    unchanged: int = 0
    closed: int = 0


def attrs_hash(spec: EntitySpec, record: dict[str, Any]) -> str:
    payload = json.dumps([record[a] for a in spec.attrs], default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def known_hostnames(conn: psycopg.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT hostname FROM device_versions WHERE is_current")}


def load_entity(
    conn: psycopg.Connection,
    spec: EntitySpec,
    records: list[dict[str, Any]],
    *,
    source_id: int,
    source_path: str,
    run_id: int,
    now: datetime,
    close_missing: bool,
) -> tuple[LoadCounts, list[Issue]]:
    """Apply `records` to the version table. Must run inside a transaction."""
    table = sql.Identifier(spec.table)
    key_cols = sql.SQL(", ").join(sql.Identifier(k) for k in spec.keys)
    counts, issues = LoadCounts(), []

    current = conn.execute(
        sql.SQL(
            "SELECT v.id, v.attrs_hash, s.path, {keys} FROM {t} v "
            "JOIN sources s ON s.id = v.source_id WHERE v.is_current"
        ).format(keys=sql.SQL(", ").join(sql.SQL("v.") + sql.Identifier(k) for k in spec.keys), t=table)
    ).fetchall()
    existing = {tuple(str(x) for x in row[3:]): row[:3] for row in current}  # key -> (id, hash, path)

    to_close: list[int] = []
    to_insert: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, ...]] = set()

    for record in records:
        key = tuple(str(record[k]) for k in spec.keys)
        seen_keys.add(key)
        record["_hash"] = attrs_hash(spec, record)
        found = existing.get(key)
        if found is None:
            to_insert.append(record)
            counts.inserted += 1
            continue
        row_id, old_hash, owner_path = found
        if owner_path != source_path:
            issues.append(
                Issue(spec.name, "source_conflict",
                      f"'{key_text(spec, record)}' is owned by '{owner_path}', skipped", key=key_text(spec, record))
            )
            continue
        if old_hash == record["_hash"]:
            counts.unchanged += 1
        else:
            to_close.append(row_id)
            to_insert.append(record)
            counts.changed += 1

    if close_missing:
        for key, (row_id, _hash, owner_path) in existing.items():
            if owner_path == source_path and key not in seen_keys:
                to_close.append(row_id)
                counts.closed += 1

    if to_close:
        conn.execute(
            sql.SQL("UPDATE {t} SET valid_to = %s, is_current = FALSE WHERE id = ANY(%s)").format(t=table),
            (now, to_close),
        )
    if to_insert:
        columns = list(spec.all_fields)
        insert = sql.SQL(
            "INSERT INTO {t} ({cols}, attrs_hash, valid_from, source_id, run_id) VALUES ({ph}, %s, %s, %s, %s)"
        ).format(
            t=table,
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in columns),
            ph=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        )
        with conn.cursor() as cur:
            cur.executemany(
                insert,
                [[r[c] for c in columns] + [r["_hash"], now, source_id, run_id] for r in to_insert],
            )
    return counts, issues
