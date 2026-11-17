import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DB = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="session", autouse=True)
def _sample_data():
    """Make sure data/v1 and data/v2 exist."""
    if not (ROOT / "data" / "v1" / "devices.csv").exists():
        from scripts import make_sample_data  # noqa: F401  (imported lazily)
        make_sample_data.main()


@pytest.fixture
def conn(monkeypatch):
    """Fresh schema in the database given by TEST_DATABASE_URL (skipped when not set)."""
    if not TEST_DB:
        pytest.skip("TEST_DATABASE_URL is not set")
    import psycopg
    from etl.db import init_db

    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    connection = psycopg.connect(TEST_DB, autocommit=True)
    connection.execute(
        "DROP TABLE IF EXISTS validation_issues, interface_versions, device_versions, load_runs, sources CASCADE"
    )
    init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def config_path():
    return ROOT / "config" / "sources.yaml"


@pytest.fixture
def v1():
    return ROOT / "data" / "v1"


@pytest.fixture
def v2():
    return ROOT / "data" / "v2"
