"""Pure-Python tests: no database needed."""
import pytest

from etl.config import load_sources
from etl.entities import parse_speed_mbps, parse_status
from etl.extract import extract
from etl.validate import missing_columns, validate_records


@pytest.fixture
def sources(config_path):
    return {s.path: s for s in load_sources(config_path)}


@pytest.mark.parametrize("name,expected_rows", [
    ("devices.csv", 11), ("nodes.xml", 3), ("interfaces.xlsx", 13), ("edge_interfaces.json", 4),
])
def test_every_format_is_read(sources, v1, name, expected_rows):
    cfg = sources[name]
    columns, records = extract(v1 / name, cfg)
    assert len(records) == expected_rows
    assert missing_columns(cfg, columns) == []


def test_excel_numbers_do_not_become_floats(sources, v1):
    _, records = extract(v1 / "interfaces.xlsx", sources["interfaces.xlsx"])
    assert {r["Speed"] for r in records} >= {"1000", "10G"}  # not "1000.0"


def test_json_nested_interfaces_inherit_hostname(sources, v1):
    _, records = extract(v1 / "edge_interfaces.json", sources["edge_interfaces.json"])
    assert records[0]["hostname"] == "akt-edge-01" and records[0]["name"] == "100GE0/1/0"


def test_device_validation_rejects_bad_rows(sources, v1):
    cfg = sources["devices.csv"]
    _, raw = extract(v1 / "devices.csv", cfg)
    valid, issues = validate_records(cfg, raw)
    rules = {(i.rule, i.field) for i in issues}
    assert len(valid) == 7
    assert ("format", "mgmt_ip") in rules      # 10.30.2.999
    assert ("format", "role") in rules         # gateway
    assert ("format", "hostname") in rules     # Bad Host!
    assert any(i.rule == "duplicate_key" for i in issues)
    assert all(i.raw for i in issues)          # the offending source row is kept for debugging


def test_interface_validation(sources, v1):
    cfg = sources["interfaces.xlsx"]
    _, raw = extract(v1 / "interfaces.xlsx", cfg)
    valid, issues = validate_records(cfg, raw)
    assert len(valid) == 10 and {i.field for i in issues} == {"status", "ip_address", "speed_mbps"}
    first = valid[0]
    assert first["status"] == "up" and first["speed_mbps"] == 100_000 and first["ip_address"] == "10.100.0.1/30"


def test_missing_required_column_is_detected(sources):
    assert missing_columns(sources["devices.csv"], ["hostname", "vendor"])  # others are absent


@pytest.mark.parametrize("raw,expected", [("10G", 10_000), ("100M", 100), ("1000", 1000), ("1g", 1000)])
def test_speed_parser(raw, expected):
    assert parse_speed_mbps(raw) == expected


def test_status_aliases():
    assert parse_status("Admin_Down") == "admin-down"
    with pytest.raises(ValueError):
        parse_status("flapping")
