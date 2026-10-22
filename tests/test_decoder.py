"""Reference-layout behavior only; all measurements here are invented fixtures."""

import pytest

from custom_components.comfortzone_serial.telemetry.decoder import (
    DecodeReason,
    DecoderProfile,
    decode_frame,
)
from custom_components.comfortzone_serial.telemetry.framing import Frame

from .fixtures import make_frame, temperature_frame


def test_default_observation_profile_does_not_publish_even_matching_frames():
    frame = Frame(temperature_frame())
    result = decode_frame(frame)
    assert result.reason is DecodeReason.OBSERVE_ONLY
    assert result.temperatures == ()
    assert result.frame is frame


def test_explicit_profile_decodes_signed_temperature_order_and_scaling():
    frame = Frame(temperature_frame())
    result = decode_frame(frame, profile=DecoderProfile.CZBRIDGE_RX50)
    assert result.reason is DecodeReason.DECODED
    assert result.frame is frame
    assert {value.key: value.celsius for value in result.temperatures} == {
        "outdoor_temperature": -12.5,
        "flow_water_temperature": 33.5,
        "return_water_temperature": 28.1,
        "indoor_temperature": 21.0,
        "hot_gas_temperature": 65.4,
        "exchanger_outlet_temperature": 15.2,
        "evaporator_inlet_temperature": -3.7,
        "exhaust_air_temperature": 5.3,
    }


def test_signed_limits_are_not_clamped_or_assumed_fault_codes():
    frame = Frame(temperature_frame((-32768, -1, 0, 1, 32767, 100, -100, 10)))
    result = decode_frame(frame, profile=DecoderProfile.CZBRIDGE_RX50)
    assert tuple(t.celsius for t in result.temperatures) == (
        -3276.8, -0.1, 0.0, 0.1, 3276.7, 10.0, -10.0, 1.0
    )


@pytest.mark.parametrize("command", [ord("R"), ord("w"), ord("W"), 0, 255])
def test_other_commands_remain_unknown(command):
    frame = Frame(make_frame(payload=bytes(114), command=command))
    result = decode_frame(frame, profile=DecoderProfile.CZBRIDGE_RX50)
    assert result.reason is DecodeReason.UNKNOWN_COMMAND
    assert result.temperatures == ()
    assert result.frame is frame


@pytest.mark.parametrize("byte_offset", range(9))
def test_every_register_byte_is_required(byte_offset):
    register = bytearray.fromhex("010203040b0d010400")
    register[byte_offset] ^= 1
    frame = Frame(make_frame(payload=bytes(114), register=register))
    result = decode_frame(frame, profile=DecoderProfile.CZBRIDGE_RX50)
    assert result.reason is DecodeReason.UNKNOWN_REGISTER
    assert result.temperatures == ()
    assert result.frame is frame


@pytest.mark.parametrize("size", [0, 67, 68, 113, 115, 233])
def test_payload_must_match_exactly_even_when_temperature_offsets_fit(size):
    frame = Frame(make_frame(payload=bytes(size)))
    result = decode_frame(frame, profile=DecoderProfile.CZBRIDGE_RX50)
    assert result.reason is DecodeReason.UNKNOWN_PAYLOAD_LENGTH
    assert result.temperatures == ()
    assert result.frame is frame


@pytest.mark.parametrize("profile", ["ex35", "1.60", "1.80", "2.21", "2.50", "auto"])
def test_unimplemented_profiles_never_silently_fall_back(profile):
    with pytest.raises(ValueError):
        decode_frame(Frame(temperature_frame()), profile=profile)
