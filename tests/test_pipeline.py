"""End-to-end tests against a real PostgreSQL (set TEST_DATABASE_URL)."""
from etl.pipeline import run_all


def statuses(results):
    return {r.path: r.status for r in results}


def test_first_load(conn, config_path, v1):
    results = run_all(conn, config_path, v1)
    assert statuses(results) == {
        "devices.csv": "success_with_issues", "nodes.xml": "success",
        "interfaces.xlsx": "success_with_issues", "edge_interfaces.json": "success",
    }
    assert conn.execute("SELECT count(*) FROM device_versions WHERE is_current").fetchone()[0] == 10
    assert conn.execute("SELECT count(*) FROM interface_versions WHERE is_current").fetchone()[0] == 13
    # interface to a device that is not in the inventory is rejected, not loaded
    assert conn.execute("SELECT count(*) FROM validation_issues WHERE rule = 'unknown_device'").fetchone()[0] == 1


def test_rerun_of_same_files_is_a_noop(conn, config_path, v1):
    run_all(conn, config_path, v1)
    versions = conn.execute("SELECT count(*) FROM device_versions").fetchone()[0]
    again = run_all(conn, config_path, v1)
    assert set(statuses(again).values()) == {"skipped"}
    assert conn.execute("SELECT count(*) FROM device_versions").fetchone()[0] == versions


def test_changes_create_versions_and_keep_history(conn, config_path, v1, v2):
    run_all(conn, config_path, v1)
    results = {r.path: r for r in run_all(conn, config_path, v2)}
    assert results["nodes.xml"].status == "skipped"           # file did not change

    history = conn.execute(
        "SELECT os_version, is_current, valid_to IS NOT NULL FROM device_versions "
        "WHERE hostname = 'alm-core-01' ORDER BY valid_from"
    ).fetchall()
    assert history == [("V800R021", False, True), ("V800R022", True, False)]

    # versions of one device never overlap and are contiguous
    old_to, new_from = conn.execute(
        "SELECT (SELECT valid_to FROM device_versions WHERE hostname='alm-core-01' AND NOT is_current),"
        "       (SELECT valid_from FROM device_versions WHERE hostname='alm-core-01' AND is_current)"
    ).fetchone()
    assert old_to == new_from


def test_decommissioned_device_is_closed_not_deleted(conn, config_path, v1, v2):
    run_all(conn, config_path, v1)
    run_all(conn, config_path, v2)
    row = conn.execute("SELECT is_current, valid_to IS NOT NULL FROM device_versions WHERE hostname = 'alm-acc-07'").fetchone()
    assert row == (False, True)


def test_every_row_is_traceable_to_a_source_file(conn, config_path, v1):
    run_all(conn, config_path, v1)
    orphans = conn.execute(
        "SELECT count(*) FROM device_versions d LEFT JOIN sources s ON s.id = d.source_id "
        "LEFT JOIN load_runs r ON r.id = d.run_id WHERE s.id IS NULL OR r.id IS NULL"
    ).fetchone()[0]
    assert orphans == 0


def test_missing_column_fails_run_and_loads_nothing(conn, config_path, tmp_path):
    (tmp_path / "devices.csv").write_text("hostname,vendor\nalm-core-01,Huawei\n")
    result = next(r for r in run_all(conn, config_path, tmp_path) if r.path == "devices.csv")
    assert result.status == "failed" and "missing mapped columns" in result.message
    assert conn.execute("SELECT count(*) FROM device_versions").fetchone()[0] == 0


def test_empty_file_does_not_wipe_the_table(conn, config_path, v1, tmp_path):
    run_all(conn, config_path, v1)
    header = (v1 / "devices.csv").read_text().splitlines()[0]
    (tmp_path / "devices.csv").write_text(header + "\n")
    run_all(conn, config_path, tmp_path)
    still_open = conn.execute(
        "SELECT count(*) FROM device_versions d JOIN sources s ON s.id=d.source_id "
        "WHERE d.is_current AND s.path='devices.csv'"
    ).fetchone()[0]
    assert still_open == 7
    assert conn.execute("SELECT count(*) FROM validation_issues WHERE rule = 'row_count_drop'").fetchone()[0] == 1


def test_key_owned_by_another_source_is_not_overwritten(conn, config_path, v1, tmp_path):
    run_all(conn, config_path, v1)
    header = "hostname,vendor,model,site,mgmt_ip,role,os_version"
    # a second CSV-style source trying to claim a device that nodes.xml owns
    (tmp_path / "devices.csv").write_text(header + "\nakt-edge-01,Other,X,Aktau,10.9.9.9,edge,1\n")
    run_all(conn, config_path, tmp_path)
    vendor = conn.execute("SELECT vendor FROM device_versions WHERE hostname='akt-edge-01' AND is_current").fetchone()[0]
    assert vendor == "Huawei"
    assert conn.execute("SELECT count(*) FROM validation_issues WHERE rule='source_conflict'").fetchone()[0] == 1
