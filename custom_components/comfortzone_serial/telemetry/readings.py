"""Read-only EX35 field inspection, separate from Home Assistant profiles.

Only captured layouts are accepted. A memory window must contain an entire
field; no joining of different replies, value guessing or firmware detection.
"""

from dataclasses import asdict, dataclass
from datetime import datetime

from .decoder import EX35_CHANNELS, EX35_TEMPERATURE_KEYS
from .framing import Frame, crc8_maxim
from .queries import CAPTURED_LAYOUTS


@dataclass(frozen=True, slots=True)
class Reading:
    key: str
    group: str
    value: int | float | str | None
    unit: str | None
    status: str
    offset: int
    raw_hex: str


@dataclass(frozen=True, slots=True)
class UnknownRegion:
    offset: int
    raw_hex: str


@dataclass(frozen=True, slots=True)
class Readings:
    reason: str
    fields: tuple[Reading, ...] = ()
    unknown_regions: tuple[UnknownRegion, ...] = ()

    @property
    def decoded(self) -> bool:
        return any(field.status != "unknown" for field in self.fields)

    def as_dict(self) -> dict:
        return {
            "fields": [asdict(field) for field in self.fields],
            "unknown_regions": [asdict(region) for region in self.unknown_regions],
        }


@dataclass(frozen=True, slots=True)
class _Field:
    key: str
    group: str
    bank: int
    address: int
    size: int
    unit: str | None = None
    scale: int = 1
    signed: bool = False
    encoding: str = "integer"


# Independently mapped capture addresses, not an upstream implementation/table.
_FIELDS = (
    _Field("compressor_heat_output", "power", 1, 0x352, 2, "W"),
    _Field("auxiliary_heat_output", "power", 1, 0x354, 4, "W"),
    _Field("total_heat_output_1", "power", 1, 0x358, 4, "W"),
    _Field("total_heat_output_2", "power", 1, 0x35C, 4, "W"),
    _Field("compressor_electrical_input", "power", 1, 0x360, 2, "W"),
    _Field("compressor_energy", "counters", 5, 0x2C, 4, "kWh", 100),
    _Field("auxiliary_energy", "counters", 5, 0x30, 4, "kWh", 100),
    _Field("hot_water_energy", "counters", 5, 0x34, 4, "kWh", 100),
    _Field("compressor_runtime", "counters", 5, 0x38, 4, "min"),
    _Field("total_runtime", "counters", 5, 0x3C, 4, "min"),
    _Field("pump_clock", "misc", 1, 0x04, 6, encoding="clock"),
    _Field("pump_weekday", "misc", 1, 0x0A, 1, encoding="weekday"),
    _Field("heating_curve", "settings", 0, 0x28D, 1, scale=10),
    _Field("calculated_heating_setting", "settings", 0, 0x28E, 2, "°C", 10, True),
    _Field("hot_water_setpoint", "settings", 0, 0x349, 2, "°C", 10, True),
    _Field("hot_water_hysteresis", "settings", 0, 0x34B, 2, "°C", 10, True),
    _Field("extra_hot_water_setpoint", "settings", 0, 0x3C2, 2, "°C", 10, True),
    _Field("extra_hot_water_duration", "settings", 0, 0x3C4, 2, "min"),
    _Field("normal_fan_setting", "settings", 0, 0x3E1, 2, "%", 10, True),
    _Field("reduced_fan_setting", "settings", 0, 0x3E3, 2, "%", 10, True),
    _Field("high_fan_setting", "settings", 0, 0x3E5, 2, "%", 10, True),
    _Field("ui_software_version", "misc", 1, 0x599, 3, encoding="version"),
    _Field("ui_hardware_revision_code", "misc", 1, 0x59C, 1),
    *(
        _Field(f"te{i}_calibration", "misc", 0, 0x7F + i, 1, "°C", 10, True)
        for i in range(10)
    ),
    *(
        _Field(
            key, "temperature", 1, 0x3B + 2 * channel, 2, "°C", 10, True, "temperature"
        )
        for key, channel in zip(EX35_TEMPERATURE_KEYS, EX35_CHANNELS, strict=True)
    ),
    # Scope is the whole candidate region, not an asserted field location.
    # Zero bytes here must never turn into a fabricated "no alarm" reading.
    _Field("operating_mode", "operation", 1, 0x0F, 44, encoding="unknown"),
    _Field("alarm_flags", "operation", 1, 0x0F, 44, encoding="unknown"),
    _Field("compressor_state", "operation", 1, 0x0F, 44, encoding="unknown"),
    _Field("compressor_frequency", "operation", 1, 0x2E3, 59, "Hz", encoding="unknown"),
)


def _value(spec: _Field, raw: bytes) -> tuple[int | float | str | None, str]:
    if spec.encoding == "unknown":
        return None, "unknown"
    if spec.encoding == "clock":
        hour, minute, second, day, month, year = raw
        try:
            clock = datetime(2000 + year, month, day, hour, minute, second)
        except ValueError:
            return None, "unknown"
        return clock.isoformat(), "decoded"  # Pump-local, no invented timezone.
    if spec.encoding == "weekday":
        days = (
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        )
        return (days[raw[0] - 1], "decoded") if 1 <= raw[0] <= 7 else (None, "unknown")
    if spec.encoding == "version":
        return ".".join(str(part) for part in raw), "decoded"
    value = int.from_bytes(raw, "little", signed=spec.signed)
    if spec.encoding == "temperature" and value == -990:
        return None, "unavailable"
    return (value if spec.scale == 1 else value / spec.scale), "decoded"


def decode_readings(frame: Frame) -> Readings:
    """Inspect all supported fields in a validated frame, regardless of query."""
    if frame.command != ord("r"):
        return Readings("unknown_command")
    if frame.register not in CAPTURED_LAYOUTS:
        return Readings("unknown_register")
    if len(frame.payload) != CAPTURED_LAYOUTS[frame.register]:
        return Readings("unknown_payload_length")
    if (
        frame.raw[:4] != b"ADDR"
        or frame.raw[4] != crc8_maxim(frame.raw[:4])
        or frame.raw[5] != crc8_maxim(bytes(b ^ 0xFF for b in frame.raw[:4]))
    ):
        return Readings("invalid_address")
    bank = frame.register[6]
    address = int.from_bytes(frame.register[7:9], "little")
    payload = frame.payload
    covered = bytearray(len(payload))
    fields = []
    for spec in _FIELDS:
        offset = spec.address - address
        if spec.bank != bank or offset < 0 or offset + spec.size > len(payload):
            continue
        raw = payload[offset : offset + spec.size]
        value, status = _value(spec, raw)
        fields.append(
            Reading(spec.key, spec.group, value, spec.unit, status, offset, raw.hex())
        )
        if status != "unknown":
            covered[offset : offset + spec.size] = b"\x01" * spec.size
    unknown = []
    start = 0
    while start < len(payload):
        if covered[start]:
            start += 1
            continue
        end = start + 1
        while end < len(payload) and not covered[end]:
            end += 1
        unknown.append(UnknownRegion(start, payload[start:end].hex()))
        start = end
    decoded = any(field.status != "unknown" for field in fields)
    return Readings(
        "decoded" if decoded else "unmapped_payload", tuple(fields), tuple(unknown)
    )
