"""Generates the synthetic demo data in data/v1 and data/v2 (all devices and addresses are made up).

v1 is the first export and contains deliberately broken rows to show validation.
v2 is a later export: OS upgrades, a decommissioned device, a new device, changed ports.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from xml.sax.saxutils import escape

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent / "data"

DEVICE_COLUMNS = ["hostname", "vendor", "model", "site", "mgmt_ip", "role", "os_version"]
DEVICES_V1 = [
    ["alm-core-01", "Huawei", "NE40E-X8A", "Almaty", "10.10.0.1", "core", "V800R021"],
    ["alm-core-02", "Huawei", "NE40E-X8A", "Almaty", "10.10.0.2", "core", "V800R021"],
    ["alm-agg-01", "Cisco", "ASR9006", "Almaty", "10.10.1.1", "aggregation", "7.5.2"],
    ["ast-core-01", "Nokia", "7750 SR-12", "Astana", "10.20.0.1", "core", "23.3.R1"],
    ["ast-agg-01", "Nokia", "7250 IXR-R6", "Astana", "10.20.1.1", "aggregation", "23.3.R1"],
    ["shy-acc-01", "ZTE", "ZXR10 5952E", "Shymkent", "10.30.2.1", "access", "V2.05"],
    ["shy-acc-02", "ZTE", "ZXR10 5952E", "Shymkent", "10.30.2.999", "access", "V2.05"],   # bad IP
    ["alm-agg-01", "Cisco", "ASR9006", "Almaty", "10.10.1.1", "aggregation", "7.5.2"],     # duplicate key
    ["ast-fw-01", "Juniper", "SRX4600", "Astana", "10.20.9.1", "gateway", "22.4R2"],      # unknown role
    ["Bad Host!", "Cisco", "C9300", "Almaty", "10.10.2.1", "access", "17.9"],             # bad hostname
    ["alm-acc-07", "Huawei", "S6730", "Almaty", "10.10.2.7", "access", "V200R022"],       # decommissioned in v2
]
# changes in v2: upgrades, decommission (alm-acc-07 removed), new device, broken rows fixed
DEVICES_V2 = [
    ["alm-core-01", "Huawei", "NE40E-X8A", "Almaty", "10.10.0.1", "core", "V800R022"],    # upgraded
    ["alm-core-02", "Huawei", "NE40E-X8A", "Almaty", "10.10.0.2", "core", "V800R021"],
    ["alm-agg-01", "Cisco", "ASR9006", "Almaty", "10.10.1.1", "aggregation", "7.5.2"],
    ["ast-core-01", "Nokia", "7750 SR-12", "Astana", "10.20.0.1", "core", "23.3.R1"],
    ["ast-agg-01", "Nokia", "7250 IXR-R6", "Astana", "10.20.1.1", "aggregation", "24.3.R1"],  # upgraded
    ["shy-acc-01", "ZTE", "ZXR10 5952E", "Shymkent", "10.30.2.1", "access", "V2.05"],
    ["shy-acc-02", "ZTE", "ZXR10 5952E", "Shymkent", "10.30.2.2", "access", "V2.05"],     # IP fixed
    ["ast-fw-01", "Juniper", "SRX4600", "Astana", "10.20.9.1", "firewall", "22.4R2"],     # role fixed
    ["akt-agg-01", "Cisco", "ASR9006", "Aktau", "10.40.1.1", "aggregation", "7.5.2"],     # new
]

# Interfaces exported to Excel; columns are named differently from the canonical fields.
IFACE_HEADER = ["Host", "Interface", "IP", "State", "Speed", "Description"]
IFACES_V1 = [
    ["alm-core-01", "Hu0/0/1", "10.100.0.1/30", "UP", "100G", "to ast-core-01"],
    ["alm-core-01", "Hu0/0/2", "10.100.0.5/30", "UP", "100G", "to alm-core-02"],
    ["alm-core-02", "Hu0/0/1", "10.100.0.6/30", "UP", "100G", "to alm-core-01"],
    ["alm-agg-01", "Te0/1/0/1", "10.101.0.1/30", "UP", "10G", "to alm-core-01"],
    ["alm-agg-01", "Te0/1/0/2", None, "admin_down", "10G", "spare"],
    ["ast-core-01", "1/1/c1/1", "10.100.0.2/30", "Up", "100G", "to alm-core-01"],
    ["ast-agg-01", "1/1/c1/1", "10.102.0.1/30", "up", "10G", "to ast-core-01"],
    ["shy-acc-01", "GE0/0/1", None, "up", "1000", "customer: Acme LLP"],
    ["shy-acc-01", "GE0/0/2", None, "down", "1G", "customer: Beta Telecom"],
    ["ghost-01", "GE0/0/1", None, "up", "1000", "device not in inventory"],            # unknown device
    ["ast-agg-01", "1/1/c1/2", "10.102.0.5/30", "flapping", "10G", "bad state"],      # bad status
    ["alm-agg-01", "Te0/1/0/3", "10.101.0.999/30", "up", "10G", "bad ip"],            # bad IP
    ["ast-agg-01", "1/1/c1/3", None, "up", "fast", "bad speed"],                      # bad speed
]
IFACES_V2 = [dict(zip(IFACE_HEADER, row)) for row in IFACES_V1[:9]]
IFACES_V2[1]["State"] = "down"                       # alm-core-01 Hu0/0/2 went down
IFACES_V2[7]["Description"] = "customer: Acme LLP (upgraded to 10G)"
IFACES_V2[7]["Speed"] = "10G"
IFACES_V2.append(dict(zip(IFACE_HEADER, ["shy-acc-02", "GE0/0/1", None, "up", "1000", "customer: Gamma JSC"])))

# Second device inventory, exported as XML by a different management system (disjoint hostnames).
NODES = [
    ("akt-edge-01", "Huawei", "NetEngine 8000 M8", "Aktau", "10.40.0.1", "edge", "V800R023"),
    ("pvl-edge-01", "Huawei", "NetEngine 8000 M8", "Pavlodar", "10.50.0.1", "edge", "V800R023"),
    ("kar-edge-01", "Nokia", "7750 SR-1", "Karaganda", "10.60.0.1", "edge", "23.3.R1"),
]
# JSON interface dump for those edge nodes (nested structure, different key names).
EDGE_IFACES_V1 = {"generated_by": "edge-mgmt", "devices": [
    {"hostname": "akt-edge-01", "interfaces": [
        {"name": "100GE0/1/0", "ip": "10.110.0.1/30", "oper_status": "up", "speed": "100G", "descr": "to alm-core-01"},
        {"name": "10GE0/2/0", "ip": None, "oper_status": "down", "speed": "10G", "descr": "customer: Delta Oil"}]},
    {"hostname": "pvl-edge-01", "interfaces": [
        {"name": "100GE0/1/0", "ip": "10.111.0.1/30", "oper_status": "up", "speed": "100G", "descr": "to ast-core-01"}]},
    {"hostname": "kar-edge-01", "interfaces": [
        {"name": "1/1/c1/1", "ip": "10.112.0.1/30", "oper_status": "up", "speed": "100G", "descr": "to ast-core-01"}]},
]}


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def write_xlsx(path: Path, rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Interfaces"
    ws.append(IFACE_HEADER)
    for row in rows:
        ws.append(row)
    wb.create_sheet("Notes").append(["Export of port inventory (synthetic data)"])
    wb.save(path)


def write_nodes_xml(path: Path) -> None:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<inventory>"]
    for name, vendor, model, location, address, function, software in NODES:
        lines += [
            f'  <node name="{escape(name)}">',
            f"    <vendor>{escape(vendor)}</vendor>",
            f"    <model>{escape(model)}</model>",
            f"    <location>{escape(location)}</location>",
            f"    <address>{escape(address)}</address>",
            f"    <function>{escape(function)}</function>",
            f"    <software>{escape(software)}</software>",
            "  </node>",
        ]
    lines.append("</inventory>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    for version, devices, ifaces in (("v1", DEVICES_V1, IFACES_V1),
                                     ("v2", DEVICES_V2, [list(d.values()) for d in IFACES_V2])):
        out = ROOT / version
        out.mkdir(parents=True, exist_ok=True)
        write_csv(out / "devices.csv", DEVICE_COLUMNS, devices)
        write_xlsx(out / "interfaces.xlsx", ifaces)
        write_nodes_xml(out / "nodes.xml")
        edge = json.loads(json.dumps(EDGE_IFACES_V1))
        if version == "v2":
            edge["devices"][0]["interfaces"][1]["oper_status"] = "up"   # customer port came up
        (out / "edge_interfaces.json").write_text(json.dumps(edge, indent=2) + "\n", encoding="utf-8")
    print("sample data written to", ROOT)


if __name__ == "__main__":
    main()
