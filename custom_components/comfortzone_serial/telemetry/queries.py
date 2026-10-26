"""Captured EX35 read definitions; no arbitrary commands.

Register/length pairs are facts from the owner's capture. Mapping provenance
and unresolved fields are recorded in docs/query-mapping.md.
"""

from dataclasses import dataclass
from types import MappingProxyType

PREFIX = bytes.fromhex("010203040b15")


@dataclass(frozen=True, slots=True)
class ReadDefinition:
    name: str
    register: bytes
    payload_length: int


def _read(name: str, suffix: str, length: int) -> ReadDefinition:
    return ReadDefinition(name, PREFIX + bytes.fromhex(suffix), length)


TEMPERATURE_READ = _read("temperature", "010400", 117)
POWER_READ = _read("power", "015203", 53)
COMPRESSOR_READ = _read("compressor", "01e302", 59)
COUNTERS_READ = _read("counters", "052000", 32)
HEATING_READ = _read("heating_settings", "007202", 178)
HOT_WATER_READ = _read("hot_water_settings", "002403", 176)
FAN_READ = _read("fan_settings", "00e003", 99)
CALIBRATION_READ = _read("calibration", "007f00", 10)
IDENTITY_READ = _read("ui_identity", "019905", 38)

QUERY_GROUPS = MappingProxyType(
    {
        "temperature": (TEMPERATURE_READ,),
        "power": (POWER_READ,),
        "operation": (TEMPERATURE_READ, COMPRESSOR_READ, POWER_READ),
        "counters": (COUNTERS_READ,),
        "settings": (HEATING_READ, HOT_WATER_READ, FAN_READ),
        "misc": (TEMPERATURE_READ, CALIBRATION_READ, IDENTITY_READ),
    }
)
ALLOWED_READS = frozenset(read for reads in QUERY_GROUPS.values() for read in reads)
READS_BY_NAME = MappingProxyType(
    {
        read.name: read
        for read in (
            TEMPERATURE_READ,
            POWER_READ,
            COUNTERS_READ,
            HEATING_READ,
            HOT_WATER_READ,
            CALIBRATION_READ,
            IDENTITY_READ,
            FAN_READ,
            COMPRESSOR_READ,
        )
    }
)


def individual_reads(names: tuple[str, ...]) -> tuple[ReadDefinition, ...]:
    """Resolve individual operations, preserving order and removing duplicates."""
    if not isinstance(names, tuple) or not names:
        raise ValueError("Select one or more individual reads")
    if any(not isinstance(name, str) or name not in READS_BY_NAME for name in names):
        raise ValueError("Unknown individual read")
    return tuple(READS_BY_NAME[name] for name in dict.fromkeys(names))


def query_reads(groups: tuple[str, ...]) -> tuple[ReadDefinition, ...]:
    """Expand in selection order; each shared register is polled once per cycle."""
    if not isinstance(groups, tuple) or not groups:
        raise ValueError("Select one or more query groups")
    reads = {}
    for group in groups:
        if not isinstance(group, str) or group not in QUERY_GROUPS:
            raise ValueError(f"Unknown query group: {group!r}")
        for read in QUERY_GROUPS[group]:
            reads[read] = None
    return tuple(reads)


# Additional exact reply layouts from the capture. They are reception-only:
# shared fields can be decoded from overlapping windows without polling broad
# dumps, alarm history, or unrelated settings. No arbitrary layout inference.
CAPTURED_LAYOUTS = MappingProxyType(
    {
        PREFIX + bytes.fromhex(suffix): length
        for suffix, length in (
            ("007f00", 10),
            ("002701", 4),
            ("007202", 178),
            ("002403", 176),
            ("009804", 169),
            ("006b05", 53),
            ("008106", 2),
            ("014a01", 22),
            ("01aa01", 8),
            ("01fc01", 126),
            ("01e302", 59),
            ("015203", 53),
            ("01d003", 86),
            ("016204", 22),
            ("019905", 38),
            ("030b0d", 178),
            ("03bd0d", 178),
            ("03fc0e", 41),
            ("052000", 32),
            ("010400", 117),
            ("000000", 177),
            ("00b100", 177),
            ("006201", 178),
            ("001402", 178),
            ("00c602", 177),
            ("007703", 177),
            ("002804", 178),
            ("00da04", 178),
            ("008c05", 177),
            ("003d06", 98),
            ("010000", 177),
            ("01b100", 177),
            ("016201", 176),
            ("011202", 177),
            ("01c302", 177),
            ("017403", 178),
            ("012604", 177),
            ("01d704", 177),
            ("018805", 103),
            ("037f0c", 54),
            ("00e003", 99),
            ("036f0e", 178),
            ("03210f", 87),
            ("049c3e", 178),
            ("044e3f", 22),
            ("050000", 64),
        )
    }
)
