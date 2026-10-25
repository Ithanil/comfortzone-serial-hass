"""Explicit captured EX35 and legacy reference layouts; no heuristic decoding."""

from dataclasses import dataclass
from enum import StrEnum

from .framing import Frame, crc8_maxim


class DecoderProfile(StrEnum):
    """A reference layout is not a detected controller or heat-pump model."""

    OBSERVE_ONLY = "observe_only"
    CZBRIDGE_RX50 = "czbridge_rx50_temperatures_v1"
    EX35_0B15 = "ex35_0b15_temperatures_v1"


class DecodeReason(StrEnum):
    DECODED = "decoded_provisional"
    DECODED_EX35 = "decoded_ex35"
    OBSERVE_ONLY = "observe_only"
    UNKNOWN_COMMAND = "unknown_command"
    UNKNOWN_REGISTER = "unknown_register"
    UNKNOWN_PAYLOAD_LENGTH = "unknown_payload_length"
    INVALID_ADDRESS = "invalid_address"


# Protocol facts from the project's reference notes. These do not identify EX35
# compatibility or map any of the cloud integration's measurement fields.
TEMPERATURE_REGISTER = bytes.fromhex("010203040b0d010400")
TEMPERATURE_KEYS = (
    "outdoor_temperature",
    "flow_water_temperature",
    "return_water_temperature",
    "indoor_temperature",
    "hot_gas_temperature",
    "exchanger_outlet_temperature",
    "evaporator_inlet_temperature",
    "exhaust_air_temperature",
)
EX35_REGISTER = bytes.fromhex("010203040b15010400")
EX35_TEMPERATURE_KEYS = (*TEMPERATURE_KEYS, "hot_water_temperature")
EX35_CHANNELS = (*range(8), 24)
DISPLAY_CONFIRMED_KEYS = frozenset(
    {
        "outdoor_temperature",
        "indoor_temperature",
        "hot_water_temperature",
    }
)
DECODED_REASONS = frozenset({DecodeReason.DECODED, DecodeReason.DECODED_EX35})


def temperature_keys(profile: DecoderProfile) -> tuple[str, ...]:
    if profile is DecoderProfile.EX35_0B15:
        return EX35_TEMPERATURE_KEYS
    if profile is DecoderProfile.CZBRIDGE_RX50:
        return TEMPERATURE_KEYS
    return ()


@dataclass(frozen=True, slots=True)
class Temperature:
    key: str
    celsius: float | None


@dataclass(frozen=True, slots=True)
class DecodeResult:
    """Retain the exact source frame even when no measurements are recognized."""

    frame: Frame
    profile: DecoderProfile
    reason: DecodeReason
    temperatures: tuple[Temperature, ...] = ()


def decode_frame(
    frame: Frame, *, profile: DecoderProfile = DecoderProfile.OBSERVE_ONLY
) -> DecodeResult:
    """Decode only an explicitly selected and exactly matching reference layout.

    The EX35 profile suppresses the observed unused-channel marker -990.
    No controller auto-detection or general fault-code interpretation is attempted.
    """
    profile = DecoderProfile(profile)  # Reject unsupported names, never fall back.
    if profile is DecoderProfile.OBSERVE_ONLY:
        reason = DecodeReason.OBSERVE_ONLY
    elif frame.command != ord("r"):
        reason = DecodeReason.UNKNOWN_COMMAND
    elif frame.register != (
        EX35_REGISTER if profile is DecoderProfile.EX35_0B15 else TEMPERATURE_REGISTER
    ):
        reason = DecodeReason.UNKNOWN_REGISTER
    elif len(frame.payload) != (117 if profile is DecoderProfile.EX35_0B15 else 114):
        reason = DecodeReason.UNKNOWN_PAYLOAD_LENGTH
    elif profile is DecoderProfile.EX35_0B15 and (
        frame.raw[:4] != b"ADDR"
        or frame.raw[4] != crc8_maxim(frame.raw[:4])
        or frame.raw[5] != crc8_maxim(bytes(b ^ 0xFF for b in frame.raw[:4]))
    ):
        reason = DecodeReason.INVALID_ADDRESS
    else:
        payload = frame.payload
        ex35 = profile is DecoderProfile.EX35_0B15
        start = 55 if ex35 else 52
        channels = EX35_CHANNELS if ex35 else range(8)
        temperatures = tuple(
            Temperature(
                key,
                None if ex35 and raw == -990 else raw / 10,
            )
            for key, i in zip(temperature_keys(profile), channels, strict=True)
            for raw in [
                int.from_bytes(
                    payload[start + 2 * i : start + 2 * i + 2], "little", signed=True
                )
            ]
        )
        reason = DecodeReason.DECODED_EX35 if ex35 else DecodeReason.DECODED
        return DecodeResult(frame, profile, reason, temperatures)
    return DecodeResult(frame, profile, reason)
