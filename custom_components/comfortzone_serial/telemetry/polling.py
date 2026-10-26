"""Scheduling settings for captured EX35 reads and monitor query groups."""

from dataclasses import dataclass

from .framing import Frame, crc8_maxim
from .queries import (
    ALLOWED_READS,
    TEMPERATURE_READ,
    ReadDefinition,
    individual_reads,
    query_reads,
)
from .stream import finite_seconds, port

CLIENT_ADDRESS = b"ADDR"
DEFAULT_PUMP_ADDRESS = "656fde02"
RESPONSE_TIMEOUT = 10.0


def pump_address(value: str) -> bytes:
    if not isinstance(value, str) or len(value) != 8:
        raise ValueError("Pump address must be exactly eight hexadecimal characters")
    try:
        result = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError("Invalid pump address") from error
    if len(result) != 4:
        raise ValueError("Pump address must encode four bytes")
    return result


def temperature_request(address: str = DEFAULT_PUMP_ADDRESS) -> bytes:
    """Compatibility helper for the original captured temperature request."""
    return read_request(TEMPERATURE_READ, address)


def read_request(read: ReadDefinition, address: str = DEFAULT_PUMP_ADDRESS) -> bytes:
    """Build only a whitelisted captured R operation; never accept arbitrary bytes."""
    if read not in ALLOWED_READS:
        raise ValueError("Only supported captured read operations may be sent")
    destination = pump_address(address)
    raw = (
        destination
        + bytes(
            [crc8_maxim(destination), crc8_maxim(bytes(b ^ 0xFF for b in destination))]
        )
        + CLIENT_ADDRESS
        + bytes([23, ord("R")])
        + read.register
        + bytes([read.payload_length])
    )
    return raw + bytes([crc8_maxim(raw)])


@dataclass(frozen=True, slots=True)
class PollingSettings:
    interval: float = 30.0
    destination_port: int = 4001
    address: str = DEFAULT_PUMP_ADDRESS
    queries: tuple[str, ...] = ("temperature",)
    cycle: bool = False
    request_delay: float = 0.25
    read_names: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if type(self.cycle) is not bool:
            raise ValueError("Cycle scheduling must be a boolean")
        interval = finite_seconds(self.interval)
        if self.cycle and not 0 < interval <= 3600:
            raise ValueError(
                "Cycle interval must be greater than 0 and at most 3600 seconds"
            )
        if not self.cycle and not 15 <= interval <= 3600:
            raise ValueError("Polling interval must be between 15 and 3600 seconds")
        if finite_seconds(self.request_delay) > 3600:
            raise ValueError("Request delay must be between 0 and 3600 seconds")
        port(self.destination_port)
        pump_address(self.address)
        if self.read_names is not None and self.queries != ("temperature",):
            raise ValueError("Select individual reads or groups, not both")
        _ = self.reads  # Validate the selection before starting a transport.

    @property
    def reads(self) -> tuple[ReadDefinition, ...]:
        if self.read_names is not None:
            return individual_reads(self.read_names)
        return query_reads(self.queries)

    def matches(self, frame: Frame, read: ReadDefinition | None = None) -> bool:
        read = read or self.reads[0]
        return (
            frame.raw[:4] == CLIENT_ADDRESS
            and frame.raw[4:6] == bytes([0x07, 0x8A])
            and frame.raw[6:10] == pump_address(self.address)
            and frame.command == ord("r")
            and frame.register == read.register
            and len(frame.payload) == read.payload_length
        )


@dataclass(slots=True)
class PollingStats:
    requests_sent: int = 0
    replies_received: int = 0
    timeouts: int = 0
    ignored_frames: int = 0
