# telecom-config-etl

ETL pipeline that collects technical information about network equipment from files in different formats (CSV, Excel, JSON, XML), validates it, and loads it into a single PostgreSQL database **with full change history**. A small REST API serves the data to other systems.

> All devices, addresses and customers in `data/` are synthetic.

```
 devices.csv ─┐                                         ┌──────────────┐
 nodes.xml ───┤  extract ─► map ─► validate ─► load ───►│  PostgreSQL  │◄── FastAPI
 interfaces.xlsx                    │            (SCD2)  │  versions +  │     /devices
 edge_interfaces.json               ▼                    │  audit trail │     /history
                              validation_issues          └──────────────┘     /runs ...
        Airflow DAG (hourly) or `python -m etl run`
```

## What it does

| Requirement | How it is done |
|---|---|
| Several input formats | One reader per format (`etl/extract.py`); a YAML file (`config/sources.yaml`) maps each source's own column / tag / key names to the canonical model, so adding a source is configuration, not code |
| Single database schema | `sql/schema.sql`: `device_versions`, `interface_versions` plus `sources`, `load_runs`, `validation_issues` |
| Automatic update and sync | Each file is fingerprinted with SHA-256. Unchanged file = skipped. Changed file = diffed against the current state. Keys that vanish from a source are **closed** (decommissioned), never deleted |
| Completeness, integrity, correctness | Missing columns fail the run. Required fields, IP / hostname / role / status / speed parsing, duplicate keys, interfaces pointing at unknown devices, keys already owned by another source - all become rows in `validation_issues` with the original source row attached. A file that shrinks below 50% of the previous load, or is empty, never closes anything |
| History, versions, sources | Type 2 slowly changing dimension: a change closes the old row (`valid_to`) and opens a new one. Every version points at the exact file version (`sources.sha256`) and run that produced it. `?as_of=` on the API returns the state at any past moment |
| API | FastAPI, read-only, see below |
| Atomicity | One transaction per file: either everything is loaded or nothing is; a failed run is still recorded with its error |

## Quick start

```bash
docker compose up -d --build                      # Postgres + API on :8000
docker compose run --rm etl --data-dir data/v1    # first export (has broken rows on purpose)
docker compose run --rm etl --data-dir data/v1    # again: every file "skipped"
docker compose run --rm etl --data-dir data/v2    # later export: upgrades, new + decommissioned device
```

Output of the v2 load:

```
success   devices.csv            read=9  new=3 changed=2 unchanged=4 closed=1 rejected=0
skipped   nodes.xml              unchanged since last successful load
success   interfaces.xlsx        read=10 new=1 changed=2 unchanged=7 closed=0 rejected=0
success   edge_interfaces.json   read=4  new=0 changed=1 unchanged=3 closed=0 rejected=0
```

Without Docker: create a database, `pip install -r requirements.txt`, set `DATABASE_URL`, then `python -m etl run --data-dir data/v1` and `uvicorn api.main:app`.

## API

| Endpoint | Description |
|---|---|
| `GET /devices?site=&vendor=&role=&as_of=` | current (or historical) devices, filterable, paginated |
| `GET /devices/{hostname}` | one device, optionally `as_of` a past moment |
| `GET /devices/{hostname}/history` | every version with the source file and run that produced it |
| `GET /devices/{hostname}/interfaces` | interfaces of a device |
| `GET /sources`, `GET /runs`, `GET /runs/{id}/issues` | audit trail: what was loaded, from which file, what was rejected and why |

Interactive docs at `http://localhost:8000/docs`.

## Design notes

- **One owner per key.** If two source files describe the same hostname, the second one is rejected with `source_conflict` instead of silently flip-flopping the history.
- **Change detection by hash** of the business attributes, so reloading identical data creates no versions.
- **Partial unique index** `WHERE is_current` guarantees at most one open version per device / interface at the database level, and a CHECK ties `is_current` to `valid_to`.
- **XML is parsed with `defusedxml`**, since configuration files can come from outside.

## Scheduling

`dags/config_sync_dag.py` is an Airflow DAG that runs the same pipeline hourly (retries, fails loudly when any source fails). Because unchanged files are skipped by hash, frequent runs are cheap.

## Tests

```bash
export TEST_DATABASE_URL=postgresql://etl:etl@localhost:5432/etl_test   # empty throw-away DB
pytest -q
```

Unit tests for parsers and validation need no database. Integration tests cover first load, idempotent re-run, versioning, decommissioning, failure handling, and the API. CI runs them against a Postgres service (`.github/workflows/ci.yml`).

## Layout

```
etl/        entities.py (fields + rules)  extract.py  validate.py  load.py (SCD2)  pipeline.py  __main__.py
api/        FastAPI app
sql/        schema.sql
config/     sources.yaml
dags/       Airflow DAG
data/       synthetic v1 / v2 exports, generated by scripts/make_sample_data.py
tests/
```
