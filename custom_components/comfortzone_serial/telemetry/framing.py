"""Bounded ComfortZone framing, verified against captured EX35 traffic.

No synchronization marker is established. CRC/length checks can accidentally
accept noise; a valid envelope is not evidence of a supported measurement layout.
See docs/protocol.md and docs/references.md for provenance and limitations.
"""

from collections import deque
from dataclasses import dataclass
from math import isfinite

HEADER_SIZE = 21
LENGTH_OFFSET = 10
MIN_FRAME_SIZE = HEADER_SIZE + 1
MAX_FRAME_SIZE = 255
DEFAULT_PARTIAL_TIMEOUT = 1.0
REFERENCE_COMMANDS = frozenset(b"RrWw")


def _crc_table() -> tuple[int, ...]:
    """Construct the CRC-8/MAXIM-DOW byte transition table (reflected 0x31)."""
    table = []
    for initial in range(256):
        remainder = initial
        for _ in range(8):
            low_bit = remainder & 1
            remainder >>= 1
            if low_bit:
                remainder ^= 0x8C
        table.append(remainder)
    return tuple(table)


_CRC_TABLE = _crc_table()


def crc8_maxim(data: bytes | bytearray) -> int:
    """CRC-8/MAXIM-DOW: init=0, refin/refout=true, xorout=0; check=0xA1."""
    result = 0
    for value in data:
        result = _CRC_TABLE[result ^ value]
    return result


@dataclass(frozen=True, slots=True)
class Frame:
    """An immutable, length- and CRC-validated reference frame."""

    raw: bytes

    def __post_init__(self) -> None:
        # Copy mutable callers' buffers; validation must remain true for this object.
        object.__setattr__(self, "raw", bytes(self.raw))
        if not MIN_FRAME_SIZE <= len(self.raw) <= MAX_FRAME_SIZE:
            raise ValueError("Frame length must be between 22 and 255 bytes")
        if self.raw[LENGTH_OFFSET] != len(self.raw):
            raise ValueError("Frame length field does not match its size")
        if crc8_maxim(self.raw[:-1]) != self.raw[-1]:
            raise ValueError("Frame CRC mismatch")

    @property
    def command(self) -> int:
        return self.raw[11]

    @property
    def register(self) -> bytes:
        return self.raw[12:HEADER_SIZE]

    @property
    def payload(self) -> bytes:
        return self.raw[HEADER_SIZE:-1]


@dataclass(frozen=True, slots=True)
class ReceivedFrame:
    """A frame and the arrival times of its first and last byte.

    Times use the caller's monotonic stream clock, not a pump measurement clock.
    Replay must use recorded time offsets, never the time the replay is run.
    """

    frame: Frame
    first_received_at: float
    received_at: float
    record_index: int | None = None


@dataclass(slots=True)
class FramingStats:
    """Counters for one stream; rejected candidates are not necessarily frames."""

    bytes_received: int = 0
    frames_received: int = 0
    bytes_discarded: int = 0
    invalid_length_candidates: int = 0
    crc_failures: int = 0
    expired_partial_bytes: int = 0
    resets: int = 0
    peak_buffer_bytes: int = 0


class FrameBuffer:
    """Reassemble one sender/session stream, retaining at most 255 bytes.

    Complete candidates at the current boundary take precedence. An incomplete
    candidate waits at most partial_timeout from its first byte, even under a
    continuous trickle of traffic. Expiry resumes the byte-by-byte search and
    can recover a valid complete suffix. Call expire() during silence.
    """

    def __init__(self, *, partial_timeout: float = DEFAULT_PARTIAL_TIMEOUT) -> None:
        if not isfinite(partial_timeout) or partial_timeout <= 0:
            raise ValueError("Partial timeout must be finite and positive")
        self.partial_timeout = partial_timeout
        self.stats = FramingStats()
        self._buffer = bytearray()
        self._arrivals: deque[float] = deque()
        self._record_indices: deque[int | None] = deque()
        self._last_time: float | None = None
        self._recovering = False

    @property
    def pending(self) -> bytes:
        """Return an immutable diagnostic snapshot of the incomplete tail."""
        return bytes(self._buffer)

    def reset(self) -> None:
        """Discard partial state at a known stream discontinuity."""
        self.stats.resets += 1
        self._discard(len(self._buffer))
        self._last_time = None
        self._recovering = False

    def feed(
        self, data: bytes, *, now: float, record_index: int | None = None
    ) -> list[ReceivedFrame]:
        """Consume bytes without ever retaining an entire incoming datagram."""
        frames = self.expire(now=now)
        self.stats.bytes_received += len(data)
        offset = 0
        while offset < len(data):
            size = min(MAX_FRAME_SIZE - len(self._buffer), len(data) - offset)
            self._buffer.extend(data[offset : offset + size])
            self._arrivals.extend([now] * size)
            self._record_indices.extend([record_index] * size)
            offset += size
            self.stats.peak_buffer_bytes = max(
                self.stats.peak_buffer_bytes, len(self._buffer)
            )
            frames.extend(self._drain(now))
        return frames

    def expire(self, *, now: float) -> list[ReceivedFrame]:
        """Expire partial candidates and recover complete frames during silence."""
        if not isfinite(now):
            raise ValueError("Stream time must be finite")
        if self._last_time is not None and now < self._last_time:
            # A recording clock/session discontinuity must not join byte streams.
            self.reset()
        self._last_time = now
        return self._drain(now)

    def _drain(self, now: float) -> list[ReceivedFrame]:
        frames = []
        while self._buffer:
            if len(self._buffer) > LENGTH_OFFSET:
                size = self._buffer[LENGTH_OFFSET]
                if size < MIN_FRAME_SIZE:
                    self.stats.invalid_length_candidates += 1
                    self._discard(1)
                    continue
                if len(self._buffer) >= size:
                    raw = bytes(self._buffer[:size])
                    if crc8_maxim(raw[:-1]) == raw[-1]:
                        if self._recovering and raw[11] not in REFERENCE_COMMANDS:
                            # CRC-8 alone is weak boundary evidence. After corruption,
                            # prefer a complete overlapping frame with a documented
                            # command, while still accepting unknown commands when
                            # there is no stronger candidate in the bounded buffer.
                            boundary = self._reference_boundary()
                            if boundary is not None:
                                self._discard(boundary)
                                continue
                        frames.append(
                            ReceivedFrame(
                                Frame(raw), self._arrivals[0], self._arrivals[size - 1],
                                self._record_indices[size - 1],
                            )
                        )
                        self.stats.frames_received += 1
                        self._consume(size)
                        self._recovering = False
                    else:
                        self.stats.crc_failures += 1
                        self._discard(1)
                    continue
            if now - self._arrivals[0] >= self.partial_timeout:
                self.stats.expired_partial_bytes += 1
                self._discard(1)
                continue
            break
        return frames

    def _reference_boundary(self) -> int | None:
        for start in range(1, len(self._buffer) - MIN_FRAME_SIZE + 1):
            size = self._buffer[start + LENGTH_OFFSET]
            if (
                size >= MIN_FRAME_SIZE
                and start + size <= len(self._buffer)
                and self._buffer[start + 11] in REFERENCE_COMMANDS
            ):
                raw = self._buffer[start : start + size]
                if crc8_maxim(raw[:-1]) == raw[-1]:
                    return start
        return None

    def _consume(self, size: int) -> None:
        del self._buffer[:size]
        for _ in range(size):
            self._arrivals.popleft()
            self._record_indices.popleft()

    def _discard(self, size: int) -> None:
        self.stats.bytes_discarded += size
        self._consume(size)
        self._recovering = True
