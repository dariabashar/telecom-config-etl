"""Airflow DAG: re-ingest all configured sources every hour.

Unchanged files are skipped by content hash, so frequent runs are cheap.
Set DATABASE_URL, ETL_CONFIG and ETL_DATA_DIR in the Airflow environment.
"""
import os
from datetime import datetime, timedelta

from airflow.decorators import dag, task

CONFIG = os.environ.get("ETL_CONFIG", "/opt/etl/config/sources.yaml")
DATA_DIR = os.environ.get("ETL_DATA_DIR", "/opt/etl/data/incoming")


@dag(
    dag_id="telecom_config_sync",
    schedule="@hourly",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["etl", "telecom"],
)
def telecom_config_sync():
    @task
    def sync() -> dict:
        from etl.db import connect, init_db
        from etl.pipeline import run_all

        with connect() as conn:
            init_db(conn)
            results = run_all(conn, CONFIG, DATA_DIR)
        failed = [r for r in results if r.status == "failed"]
        if failed:
            raise RuntimeError("; ".join(f"{r.path}: {r.message}" for r in failed))
        return {r.path: r.status for r in results}

    sync()


telecom_config_sync()
