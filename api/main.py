"""Read-only REST API over the warehouse. Run: uvicorn api.main:app"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from etl.db import database_url

DEVICE_COLS = "hostname, vendor, model, site, host(mgmt_ip) AS mgmt_ip, role, os_version, valid_from, valid_to"
IFACE_COLS = "hostname, name, ip_address::text AS ip_address, status, speed_mbps, description, valid_from, valid_to"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = ConnectionPool(database_url(), kwargs={"row_factory": dict_row}, min_size=1, max_size=5, open=True)
    yield
    app.state.pool.close()


app = FastAPI(title="Telecom config warehouse API", version="1.0.0", lifespan=lifespan)


def get_conn():
    with app.state.pool.connection() as conn:
        yield conn


Conn = Annotated[Any, Depends(get_conn)]
AsOf = Annotated[datetime | None, Query(description="Return the state at this moment (ISO 8601 with timezone)")]


def _time_filter(as_of: datetime | None) -> tuple[str, dict[str, Any]]:
    if as_of is None:
        return "is_current", {}
    return "valid_from <= %(as_of)s AND (valid_to IS NULL OR valid_to > %(as_of)s)", {"as_of": as_of}


@app.get("/health")
def health(conn: Conn):
    conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/devices")
def list_devices(
    conn: Conn,
    as_of: AsOf = None,
    site: str | None = None,
    vendor: str | None = None,
    role: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    where, params = _time_filter(as_of)
    for column, value in (("site", site), ("vendor", vendor), ("role", role)):
        if value is not None:
            where += f" AND lower({column}) = lower(%({column})s)"
            params[column] = value
    params.update(limit=limit, offset=offset)
    return conn.execute(
        f"SELECT {DEVICE_COLS} FROM device_versions WHERE {where} ORDER BY hostname LIMIT %(limit)s OFFSET %(offset)s",
        params,
    ).fetchall()


@app.get("/devices/{hostname}")
def get_device(hostname: str, conn: Conn, as_of: AsOf = None):
    where, params = _time_filter(as_of)
    row = conn.execute(
        f"SELECT {DEVICE_COLS} FROM device_versions WHERE hostname = %(h)s AND {where}", {**params, "h": hostname.lower()}
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"device '{hostname}' not found")
    return row


@app.get("/devices/{hostname}/history")
def device_history(hostname: str, conn: Conn):
    rows = conn.execute(
        "SELECT d.id AS version_id, d.hostname, d.vendor, d.model, d.site, host(d.mgmt_ip) AS mgmt_ip, d.role, "
        "d.os_version, d.valid_from, d.valid_to, d.is_current, s.path AS source, s.sha256 AS source_sha256, "
        "d.run_id FROM device_versions d JOIN sources s ON s.id = d.source_id "
        "WHERE d.hostname = %s ORDER BY d.valid_from, d.id",
        (hostname.lower(),),
    ).fetchall()
    if not rows:
        raise HTTPException(404, f"device '{hostname}' not found")
    return rows


@app.get("/devices/{hostname}/interfaces")
def device_interfaces(hostname: str, conn: Conn, as_of: AsOf = None):
    where, params = _time_filter(as_of)
    return conn.execute(
        f"SELECT {IFACE_COLS} FROM interface_versions WHERE hostname = %(h)s AND {where} ORDER BY name",
        {**params, "h": hostname.lower()},
    ).fetchall()


@app.get("/sources")
def list_sources(conn: Conn):
    return conn.execute(
        "SELECT s.id, s.path, s.format, s.sha256, s.size_bytes, s.first_seen, "
        "(SELECT max(r.id) FROM load_runs r WHERE r.source_id = s.id) AS last_run_id "
        "FROM sources s ORDER BY s.path, s.id"
    ).fetchall()


@app.get("/runs")
def list_runs(conn: Conn, status: str | None = None, limit: int = Query(50, ge=1, le=500)):
    return conn.execute(
        "SELECT r.*, s.path AS source FROM load_runs r JOIN sources s ON s.id = r.source_id "
        "WHERE (%(status)s::text IS NULL OR r.status = %(status)s) ORDER BY r.id DESC LIMIT %(limit)s",
        {"status": status, "limit": limit},
    ).fetchall()


@app.get("/runs/{run_id}/issues")
def run_issues(run_id: int, conn: Conn):
    if conn.execute("SELECT 1 FROM load_runs WHERE id = %s", (run_id,)).fetchone() is None:
        raise HTTPException(404, f"run {run_id} not found")
    return conn.execute(
        "SELECT row_number, entity, key, field, rule, message, raw FROM validation_issues "
        "WHERE run_id = %s ORDER BY id", (run_id,)
    ).fetchall()
