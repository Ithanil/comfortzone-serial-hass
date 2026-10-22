"""Explicit, provisional measurement profiles; unknown layouts stay unknown."""

from dataclasses import dataclass
from enum import StrEnum

from .framing import Frame


class DecoderProfile(StrEnum):
    """A reference layout is not a detected controller or heat-pump model."""

    OBSERVE_ONLY = "observe_only"
    CZBRIDGE_RX50 = "czbridge_rx50_temperatures_v1"


class DecodeReason(StrEnum):
    DECODED = "decoded_provisional"
    OBSERVE_ONLY = "observe_only"
    UNKNOWN_COMMAND = "unknown_command"
    UNKNOWN_REGISTER = "unknown_register"
    UNKNOWN_PAYLOAD_LENGTH = "unknown_payload_length"


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


@dataclass(frozen=True, slots=True)
class Temperature:
    key: str
    celsius: float


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

    No controller auto-detection, plausibility heuristics, or fault/sentinel
    interpretation is justified by the available evidence.
    """
    profile = DecoderProfile(profile)  # Reject unsupported names, never fall back.
    if profile is DecoderProfile.OBSERVE_ONLY:
        reason = DecodeReason.OBSERVE_ONLY
    elif frame.command != ord("r"):
        reason = DecodeReason.UNKNOWN_COMMAND
    elif frame.register != TEMPERATURE_REGISTER:
        reason = DecodeReason.UNKNOWN_REGISTER
    elif len(frame.payload) != 114:
        reason = DecodeReason.UNKNOWN_PAYLOAD_LENGTH
    else:
        payload = frame.payload
        temperatures = tuple(
            Temperature(
                key,
                int.from_bytes(payload[52 + 2 * i : 54 + 2 * i], "little", signed=True)
                / 10,
            )
            for i, key in enumerate(TEMPERATURE_KEYS)
        )
        return DecodeResult(frame, profile, DecodeReason.DECODED, temperatures)
    return DecodeResult(frame, profile, reason)
