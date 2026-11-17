"""Canonical entities and the field-level parsing / validation rules for each.

A parser takes the cleaned string from the source and returns the normalized
value, or raises ValueError with a human readable reason. Fields that are not
`required` may be empty (None) and are then skipped.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Callable

HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
SPEED_RE = re.compile(r"^(\d+)\s*([gm])?(?:bps)?$", re.IGNORECASE)

ROLES = {"core", "aggregation", "access", "edge", "firewall"}
STATUS_ALIASES = {
    "up": "up",
    "down": "down",
    "admin-down": "admin-down",
    "admin_down": "admin-down",
    "administratively down": "admin-down",
    "shutdown": "admin-down",
}


def parse_hostname(value: str) -> str:
    value = value.lower()
    if not HOSTNAME_RE.match(value):
        raise ValueError(f"'{value}' is not a valid hostname")
    return value


def parse_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        raise ValueError(f"'{value}' is not a valid IP address") from None


def parse_ip_interface(value: str) -> str:
    try:
        return str(ipaddress.ip_interface(value))
    except ValueError:
        raise ValueError(f"'{value}' is not a valid IP address or prefix") from None


def parse_role(value: str) -> str:
    value = value.lower()
    if value not in ROLES:
        raise ValueError(f"role '{value}' is not one of {sorted(ROLES)}")
    return value


def parse_status(value: str) -> str:
    status = STATUS_ALIASES.get(value.lower())
    if status is None:
        raise ValueError(f"status '{value}' is not one of up, down, admin-down")
    return status


def parse_speed_mbps(value: str) -> int:
    """'10G' -> 10000, '100M' -> 100, '1000' -> 1000 (bare numbers are Mbps)."""
    match = SPEED_RE.match(value.strip())
    if not match:
        raise ValueError(f"'{value}' is not a valid link speed (examples: 1000, 10G, 100M)")
    number, unit = int(match.group(1)), (match.group(2) or "m").lower()
    return number * 1000 if unit == "g" else number


def parse_text(value: str) -> str:
    return value


@dataclass(frozen=True)
class Field:
    parse: Callable[[str], Any] = parse_text
    required: bool = False


@dataclass(frozen=True)
class EntitySpec:
    name: str
    table: str
    keys: tuple[str, ...]
    attrs: tuple[str, ...]
    fields: dict[str, Field]

    @property
    def all_fields(self) -> tuple[str, ...]:
        return self.keys + self.attrs


DEVICE = EntitySpec(
    name="device",
    table="device_versions",
    keys=("hostname",),
    attrs=("vendor", "model", "site", "mgmt_ip", "role", "os_version"),
    fields={
        "hostname": Field(parse_hostname, required=True),
        "vendor": Field(required=True),
        "model": Field(),
        "site": Field(required=True),
        "mgmt_ip": Field(parse_ip, required=True),
        "role": Field(parse_role, required=True),
        "os_version": Field(),
    },
)

INTERFACE = EntitySpec(
    name="interface",
    table="interface_versions",
    keys=("hostname", "name"),
    attrs=("ip_address", "status", "speed_mbps", "description"),
    fields={
        "hostname": Field(parse_hostname, required=True),
        "name": Field(required=True),
        "ip_address": Field(parse_ip_interface),
        "status": Field(parse_status, required=True),
        "speed_mbps": Field(parse_speed_mbps),
        "description": Field(),
    },
)

ENTITIES: dict[str, EntitySpec] = {DEVICE.name: DEVICE, INTERFACE.name: INTERFACE}
# devices must be loaded before interfaces (interfaces reference devices)
LOAD_ORDER = ["device", "interface"]
