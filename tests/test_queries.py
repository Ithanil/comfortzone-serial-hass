"""Query mapping checks against preserved captures, without network access."""

from dataclasses import replace
from pathlib import Path

import pytest

from custom_components.comfortzone_serial.telemetry.decoder import (
    DecoderProfile,
    decode_frame,
)
from custom_components.comfortzone_serial.telemetry.framing import (
    Frame,
    FrameBuffer,
    crc8_maxim,
)
from custom_components.comfortzone_serial.telemetry.polling import (
    PollingSettings,
    read_request,
)
from custom_components.comfortzone_serial.telemetry.queries import (
    ALLOWED_READS,
    CAPTURED_LAYOUTS,
    POWER_READ,
    PREFIX,
    QUERY_GROUPS,
    TEMPERATURE_READ,
    query_reads,
)
from custom_components.comfortzone_serial.telemetry.readings import decode_readings

DATA = Path(__file__).parent / "data"


def captured_frames():
    buffer = FrameBuffer()
    frames = []
    for line in (DATA / "pump-reply-datagrams.hex").read_text().splitlines():
        frames.extend(p.frame for p in buffer.feed(bytes.fromhex(line), now=0))
    assert not buffer.pending
    return {f.register: f for f in frames}


def reply(suffix):
    return captured_frames()[PREFIX + bytes.fromhex(suffix)]


def fields(suffix):
    return {field.key: field for field in decode_readings(reply(suffix)).fields}


def corrected(raw):
    raw = bytearray(raw)
    raw[10] = len(raw)
    raw[-1] = crc8_maxim(raw[:-1])
    return Frame(bytes(raw))


def test_requests_exactly_reproduce_captured_reads_and_layouts():
    requests = [
        Frame(bytes.fromhex(line))
        for line in (DATA / "loggamera-request-cycle.hex").read_text().splitlines()
    ]
    frames = captured_frames()
    assert len(requests) == len(frames) == len(CAPTURED_LAYOUTS) == 46
    assert dict(CAPTURED_LAYOUTS) == {
        f.register: len(f.payload) for f in frames.values()
    }
    for read in ALLOWED_READS:
        original = next(f for f in requests if f.register == read.register)
        assert read_request(read) == original.raw
        assert original.command == ord("R")
        assert original.payload == bytes([read.payload_length])
        assert PollingSettings().matches(frames[read.register], read)
        changed = Frame(read_request(read, "12345678"))
        assert changed.raw[:4] == bytes.fromhex("12345678")
        assert changed.raw[4] == crc8_maxim(changed.raw[:4])
        assert changed.raw[5] == crc8_maxim(bytes(b ^ 255 for b in changed.raw[:4]))
        assert changed.raw[6:-1] == original.raw[6:-1]


def test_query_expansion_preserves_order_and_deduplicates_shared_reads():
    assert PollingSettings().reads == (TEMPERATURE_READ,)
    reads = query_reads(("power", "operation", "misc", "temperature", "power"))
    assert [r.name for r in reads] == [
        "power",
        "temperature",
        "compressor",
        "calibration",
        "ui_identity",
    ]
    assert len(query_reads(tuple(QUERY_GROUPS))) == 9
    assert all(read.register[6] in (0, 1, 5) for read in ALLOWED_READS)


@pytest.mark.parametrize("groups", [(), ("history",), ("write",), "power", (1,)])
def test_invalid_queries(groups):
    with pytest.raises(ValueError):
        PollingSettings(queries=groups)


def test_arbitrary_reads_are_rejected():
    for read in [
        replace(POWER_READ, payload_length=52),
        replace(POWER_READ, register=PREFIX + b"\x03\x00\x00"),
    ]:
        with pytest.raises(ValueError, match="captured"):
            read_request(read)


@pytest.mark.parametrize(
    "suffix,expected",
    [
        (
            "015203",
            {
                "compressor_heat_output": 1340,
                "auxiliary_heat_output": 0,
                "total_heat_output_1": 1340,
                "total_heat_output_2": 1340,
                "compressor_electrical_input": 400,
            },
        ),
        (
            "052000",
            {
                "compressor_energy": 2644.08,
                "auxiliary_energy": 393.52,
                "hot_water_energy": 2177.64,
                "compressor_runtime": 98503,
                "total_runtime": 317186,
            },
        ),
        ("007202", {"heating_curve": 3.0, "calculated_heating_setting": 21.0}),
        (
            "002403",
            {
                "hot_water_setpoint": 50.0,
                "hot_water_hysteresis": 5.0,
                "extra_hot_water_setpoint": 55.0,
                "extra_hot_water_duration": 180,
            },
        ),
        (
            "00e003",
            {
                "normal_fan_setting": 80.0,
                "reduced_fan_setting": -30.0,
                "high_fan_setting": 30.0,
            },
        ),
        ("019905", {"ui_software_version": "2.30.0", "ui_hardware_revision_code": 10}),
    ],
)
def test_captured_values(suffix, expected):
    actual = fields(suffix)
    assert {k: f.value for k, f in actual.items()} == expected
    assert all(f.status == "decoded" for f in actual.values())


def test_clock_temperatures_calibration_and_unknown_operation():
    actual = fields("010400")
    assert actual["pump_clock"].value == "2026-10-24T21:27:54"
    assert actual["pump_weekday"].value == "Saturday"
    assert actual["outdoor_temperature"].value == 10.3
    assert actual["hot_water_temperature"].value == 46.9
    assert actual["hot_water_temperature"].offset == 103
    for key in ("operating_mode", "alarm_flags", "compressor_state"):
        assert actual[key].status == "unknown" and actual[key].value is None
        assert actual[key].raw_hex == reply("010400").payload[11:55].hex()
    compressor = fields("01e302")["compressor_frequency"]
    assert compressor.status == "unknown" and compressor.value is None
    assert compressor.raw_hex == reply("01e302").payload.hex()
    calibration = fields("007f00")
    assert [f.value for f in calibration.values()] == [
        0,
        1.3,
        0.9,
        0,
        0,
        0.7,
        0,
        0,
        0,
        0,
    ]


def test_overlapping_windows_decode_same_fields_without_joining_replies():
    for short, broad in [
        ("052000", "050000"),
        ("007f00", "000000"),
        ("00e003", "007703"),
        ("007202", "001402"),
        ("019905", "018805"),
    ]:
        narrow, wide = fields(short), fields(broad)
        for key, field in narrow.items():
            assert field.value == wide[key].value
            assert field.raw_hex == wide[key].raw_hex
    # The broad 0x2c6 window contains setpoint/hysteresis, not the later extras.
    assert fields("00c602")["hot_water_setpoint"].value == 50
    assert "extra_hot_water_setpoint" not in fields("00c602")


@pytest.mark.parametrize(
    "offset,value,reason",
    [
        (11, ord("W"), "unknown_command"),
        (17, 0x10, "unknown_register"),
        (0, 0, "invalid_address"),
        (4, 0, "invalid_address"),
        (5, 0, "invalid_address"),
    ],
)
def test_rejects_nonmatching_envelopes(offset, value, reason):
    raw = bytearray(reply("015203").raw)
    raw[offset] = value
    result = decode_readings(corrected(raw))
    assert result.reason == reason and not result.fields


def test_length_guard_corruption_and_invalid_clock():
    raw = reply("015203").raw
    assert (
        decode_readings(corrected(raw[:-2] + raw[-1:])).reason
        == "unknown_payload_length"
    )
    corrupt = bytearray(raw)
    corrupt[22] ^= 1
    with pytest.raises(ValueError, match="CRC"):
        Frame(corrupt)
    raw = bytearray(reply("010400").raw)
    raw[21 + 4] = 13  # Invalid month must not discard valid temperatures.
    raw[21 + 6] = 0  # Unknown weekday must not index the final weekday.
    raw[21 + 55 : 21 + 57] = bytes.fromhex("22fc")
    actual = {f.key: f for f in decode_readings(corrected(raw)).fields}
    assert actual["pump_clock"].status == actual["pump_weekday"].status == "unknown"
    assert actual["outdoor_temperature"].status == "unavailable"
    assert actual["outdoor_temperature"].value is None
    assert actual["indoor_temperature"].value == 22.2


def test_counter_unsigned_width_and_unknown_bytes_are_preserved():
    raw = bytearray(reply("052000").raw)
    raw[21 + 24 : 21 + 28] = bytes.fromhex("ffffffff")
    actual = {f.key: f for f in decode_readings(corrected(raw)).fields}
    assert actual["compressor_runtime"].value == 4294967295
    for frame in captured_frames().values():
        result = decode_readings(frame)
        known = set()
        for field in result.fields:
            size = len(bytes.fromhex(field.raw_hex))
            assert (
                field.raw_hex == frame.payload[field.offset : field.offset + size].hex()
            )
            if field.status != "unknown":
                known.update(range(field.offset, field.offset + size))
        unknown = set()
        for region in result.unknown_regions:
            size = len(bytes.fromhex(region.raw_hex))
            assert (
                region.raw_hex
                == frame.payload[region.offset : region.offset + size].hex()
            )
            unknown.update(range(region.offset, region.offset + size))
        assert known.isdisjoint(unknown)
        assert known | unknown == set(range(len(frame.payload)))


def test_legacy_temperature_decoder_api_and_excluded_history():
    for read in ALLOWED_READS - {TEMPERATURE_READ}:
        result = decode_frame(
            captured_frames()[read.register], profile=DecoderProfile.EX35_0B15
        )
        assert not result.temperatures
    history = decode_readings(reply("030b0d"))
    assert not history.fields and not history.decoded
    assert history.unknown_regions[0].raw_hex == reply("030b0d").payload.hex()
