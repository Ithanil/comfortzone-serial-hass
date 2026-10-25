"""One captured EX35 read operation; there is no arbitrary command/write API."""

from dataclasses import dataclass

from .decoder import EX35_REGISTER
from .framing import Frame, crc8_maxim
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
    """Reproduce the captured R request, changing only its destination/checksums."""
    destination = pump_address(address)
    raw = (
        destination
        + bytes(
            [crc8_maxim(destination), crc8_maxim(bytes(b ^ 0xFF for b in destination))]
        )
        + CLIENT_ADDRESS
        + bytes([23, ord("R")])
        + EX35_REGISTER
        + bytes([117])
    )
    return raw + bytes([crc8_maxim(raw)])


@dataclass(frozen=True, slots=True)
class PollingSettings:
    interval: float = 30.0
    destination_port: int = 4001
    address: str = DEFAULT_PUMP_ADDRESS

    def __post_init__(self) -> None:
        if not 15 <= finite_seconds(self.interval) <= 3600:
            raise ValueError("Polling interval must be between 15 and 3600 seconds")
        port(self.destination_port)
        pump_address(self.address)

    def matches(self, frame: Frame) -> bool:
        return (
            frame.raw[:4] == CLIENT_ADDRESS
            and frame.raw[4:6] == bytes([0x07, 0x8A])
            and frame.raw[6:10] == pump_address(self.address)
            and frame.command == ord("r")
            and frame.register == EX35_REGISTER
            and len(frame.payload) == 117
        )


@dataclass(slots=True)
class PollingStats:
    requests_sent: int = 0
    replies_received: int = 0
    timeouts: int = 0
    ignored_frames: int = 0
