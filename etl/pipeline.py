"""Orchestrates one source file: fingerprint -> extract -> validate -> load -> audit trail."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from .config import SourceConfig, load_sources
from .entities import ENTITIES, LOAD_ORDER
from .extract import extract, file_sha256
from .load import known_hostnames, load_entity
from .validate import Issue, missing_columns, validate_records

log = logging.getLogger("etl")
ROW_DROP_THRESHOLD = 0.5  # a file shrinking below 50% of the previous load is suspicious


@dataclass
class RunResult:
    path: str
    status: str            # skipped | success | success_with_issues | failed
    run_id: int | None = None
    message: str = ""


def _store_issues(conn: psycopg.Connection, run_id: int, issues: list[Issue]) -> None:
    if not issues:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO validation_issues (run_id, row_number, entity, key, field, rule, message, raw) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [(run_id, i.row_number, i.entity, i.key, i.field, i.rule, i.message,
              Jsonb(i.raw) if i.raw is not None else None) for i in issues],
        )


def run_source(conn: psycopg.Connection, cfg: SourceConfig, data_dir: Path) -> RunResult:
    path = data_dir / cfg.path
    spec = ENTITIES[cfg.entity]

    if not path.exists():
        return RunResult(cfg.path, "failed", message=f"file not found: {path}")

    # 1. register this exact version of the file; skip if it was already loaded successfully
    sha = file_sha256(path)
    with conn.transaction():
        conn.execute(
            "INSERT INTO sources (path, format, sha256, size_bytes) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (path, sha256) DO NOTHING",
            (cfg.path, cfg.format, sha, path.stat().st_size),
        )
        source_id = conn.execute(
            "SELECT id FROM sources WHERE path = %s AND sha256 = %s", (cfg.path, sha)
        ).fetchone()[0]
        done = conn.execute(
            "SELECT id FROM load_runs WHERE source_id = %s AND status IN ('success', 'success_with_issues')",
            (source_id,),
        ).fetchone()
        if done:
            return RunResult(cfg.path, "skipped", done[0], "unchanged since last successful load")
        prev = conn.execute(
            "SELECT r.rows_read FROM load_runs r JOIN sources s ON s.id = r.source_id "
            "WHERE s.path = %s AND r.status IN ('success', 'success_with_issues') ORDER BY r.id DESC LIMIT 1",
            (cfg.path,),
        ).fetchone()
        run_id = conn.execute("INSERT INTO load_runs (source_id) VALUES (%s) RETURNING id", (source_id,)).fetchone()[0]

    # 2. the actual work, all-or-nothing
    try:
        with conn.transaction():
            columns, raw_records = extract(path, cfg)
            absent = missing_columns(cfg, columns)
            if absent:
                raise ValueError(f"source is missing mapped columns: {absent}")

            valid, issues = validate_records(cfg, raw_records)
            rows_read = len(raw_records)

            if cfg.entity == "interface":  # integrity: interface must belong to a known device
                hosts = known_hostnames(conn)
                kept = []
                for rec in valid:
                    if rec["hostname"] in hosts:
                        kept.append(rec)
                    else:
                        issues.append(Issue("interface", "unknown_device",
                                            f"device '{rec['hostname']}' is not in the inventory",
                                            key=f"{rec['hostname']}/{rec['name']}", field="hostname"))
                valid = kept

            close_missing = cfg.close_missing
            if prev and prev[0] and rows_read < prev[0] * ROW_DROP_THRESHOLD:
                issues.append(Issue(spec.name, "row_count_drop",
                                    f"{rows_read} rows vs {prev[0]} in the previous load; nothing was closed"))
                close_missing = False
            if close_missing and not valid:
                close_missing = False  # never wipe a table because of an empty/broken file

            now = datetime.now(timezone.utc)
            counts, load_issues = load_entity(
                conn, spec, valid, source_id=source_id, source_path=cfg.path,
                run_id=run_id, now=now, close_missing=close_missing,
            )
            issues += load_issues
            rejected = rows_read - len(valid)
            status = "success_with_issues" if issues else "success"
            _store_issues(conn, run_id, issues)
            conn.execute(
                "UPDATE load_runs SET finished_at = now(), status = %s, rows_read = %s, rows_valid = %s, "
                "rows_rejected = %s, rows_inserted = %s, rows_changed = %s, rows_unchanged = %s, rows_closed = %s "
                "WHERE id = %s",
                (status, rows_read, len(valid), rejected, counts.inserted, counts.changed,
                 counts.unchanged, counts.closed, run_id),
            )
        return RunResult(cfg.path, status, run_id,
                         f"read={rows_read} new={counts.inserted} changed={counts.changed} "
                         f"unchanged={counts.unchanged} closed={counts.closed} rejected={rejected}")
    except Exception as exc:  # transaction rolled back; keep an audit record of the failure
        log.exception("load of %s failed", cfg.path)
        conn.execute(
            "UPDATE load_runs SET finished_at = now(), status = 'failed', error = %s WHERE id = %s",
            (str(exc), run_id),
        )
        return RunResult(cfg.path, "failed", run_id, str(exc))


def run_all(conn: psycopg.Connection, config_path: str | Path, data_dir: str | Path) -> list[RunResult]:
    sources = sorted(load_sources(config_path), key=lambda c: LOAD_ORDER.index(c.entity))
    return [run_source(conn, cfg, Path(data_dir)) for cfg in sources]
