from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from etl.pipeline import run_all


@pytest.fixture
def client(conn, config_path, v1, v2):
    run_all(conn, config_path, v1)
    run_all(conn, config_path, v2)
    from api.main import app
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_list_and_filter_devices(client):
    all_devices = client.get("/devices").json()
    assert len(all_devices) == 12  # 9 from devices.csv + 3 from nodes.xml; decommissioned device excluded
    huawei = client.get("/devices", params={"vendor": "huawei", "role": "core"}).json()
    assert {d["hostname"] for d in huawei} == {"alm-core-01", "alm-core-02"}


def test_device_and_404(client):
    device = client.get("/devices/ALM-core-01").json()
    assert device["os_version"] == "V800R022" and device["mgmt_ip"] == "10.10.0.1"
    assert client.get("/devices/nope").status_code == 404


def test_history_has_two_versions_with_source(client):
    history = client.get("/devices/alm-core-01/history").json()
    assert [h["os_version"] for h in history] == ["V800R021", "V800R022"]
    assert all(h["source"] == "devices.csv" and len(h["source_sha256"]) == 64 for h in history)


def test_as_of_returns_the_old_state(client):
    long_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert client.get("/devices", params={"as_of": long_ago}).json() == []
    first = client.get("/devices/alm-core-01/history").json()[0]
    moment = datetime.fromisoformat(first["valid_from"]) + timedelta(microseconds=1)
    old = client.get("/devices/alm-core-01", params={"as_of": moment.isoformat()}).json()
    assert old["os_version"] == "V800R021"


def test_interfaces(client):
    ifaces = client.get("/devices/alm-core-01/interfaces").json()
    by_name = {i["name"]: i for i in ifaces}
    assert by_name["Hu0/0/2"]["status"] == "down" and by_name["Hu0/0/1"]["speed_mbps"] == 100_000


def test_runs_and_issues(client):
    failed_or_issues = client.get("/runs", params={"status": "success_with_issues"}).json()
    assert failed_or_issues and failed_or_issues[-1]["rows_rejected"] > 0
    oldest = failed_or_issues[-1]
    issues = client.get(f"/runs/{oldest['id']}/issues").json()
    assert issues and {"rule", "message", "raw"} <= set(issues[0])
    assert client.get("/runs/99999/issues").status_code == 404
    assert len(client.get("/sources").json()) >= 6
