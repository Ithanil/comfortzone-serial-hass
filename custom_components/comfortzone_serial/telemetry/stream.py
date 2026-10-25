"""Bounded stream processing shared by live reception and offline replay."""

from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from ipaddress import IPv4Address
from math import isfinite

from .decoder import DECODED_REASONS, DecodeResult, DecoderProfile, decode_frame
from .framing import FrameBuffer, FramingStats, ReceivedFrame

MAX_DATAGRAM_BYTES = 65507
type Endpoint = tuple[str, int]


def ipv4(value: str, *, allow_unspecified: bool = False) -> str:
    """Validate numeric IPv4 without DNS or any network access."""
    if not isinstance(value, str):
        raise ValueError("An IPv4 address string is required")
    address = IPv4Address(value)
    if (
        address.is_multicast
        or address.is_reserved
        or (address.is_unspecified and not allow_unspecified)
    ):
        raise ValueError("A unicast IPv4 address is required")
    return str(address)


def port(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("Port must be an integer from 1 to 65535")
    return value


def finite_seconds(value: float) -> float:
    if type(value) not in (float, int):
        raise ValueError("Time must be a finite, nonnegative number")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError("Time must be a finite, nonnegative number") from error
    if not isfinite(result) or result < 0:
        raise ValueError("Time must be a finite, nonnegative number")
    return result


class Origin(StrEnum):
    LIVE = "live"
    REPLAY = "replay"


@dataclass(frozen=True, slots=True)
class Datagram:
    data: bytes
    source: Endpoint
    received_at: datetime
    stream_time: float
    index: int

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or len(self.data) > MAX_DATAGRAM_BYTES:
            raise ValueError("Datagram must be bytes, at most 65507 bytes")
        if not isinstance(self.source, tuple) or len(self.source) != 2:
            raise ValueError("Source must contain an IPv4 address and port")
        ipv4(self.source[0])
        port(self.source[1])
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise ValueError("Receive timestamp must include a timezone")
        object.__setattr__(self, "received_at", self.received_at.astimezone(UTC))
        finite_seconds(self.stream_time)
        if type(self.index) is not int or not 0 <= self.index < 2**63:
            raise ValueError("Record index must be a nonnegative 63-bit integer")


@dataclass(frozen=True, slots=True)
class Observation:
    result: DecodeResult
    origin: Origin
    session_id: str
    source: Endpoint
    received_at: datetime
    stream_time: float
    first_stream_time: float
    record_index: int

    def as_dict(self) -> dict:
        return {
            "type": "frame",
            "origin": self.origin.value,
            "session_id": self.session_id,
            "source": list(self.source),
            "received_at": self.received_at.isoformat(),
            "stream_time": self.stream_time,
            "first_stream_time": self.first_stream_time,
            "record_index": self.record_index,
            "profile": self.result.profile.value,
            "reason": self.result.reason.value,
            "command": self.result.frame.command,
            "register": self.result.frame.register.hex(),
            "raw_hex": self.result.frame.raw.hex(),
            "temperatures_celsius": {
                value.key: value.celsius for value in self.result.temperatures
            },
        }


@dataclass(slots=True)
class StreamStats:
    datagrams: int = 0
    bytes_received: int = 0
    decoded_frames: int = 0
    unknown_frames: int = 0
    source_evictions: int = 0
    discontinuities: int = 0
    gap_resets: int = 0


@dataclass(slots=True)
class _Source:
    buffer: FrameBuffer
    last_seen: float
    # At most 254 pending bytes, hence at most 254 nonempty datagrams plus
    # the current one need metadata. Empty datagrams do not evict timestamps.
    receipts: OrderedDict[int, datetime] = field(default_factory=OrderedDict)


class TelemetryPipeline:
    """Process a single session, isolating each (IPv4, port) sender's bytes."""

    def __init__(
        self,
        *,
        session_id: str,
        origin: Origin,
        profile: DecoderProfile = DecoderProfile.OBSERVE_ONLY,
        partial_timeout: float = 1.0,
        gap_timeout: float = 5.0,
        max_sources: int = 8,
        history_size: int = 64,
    ) -> None:
        if not isinstance(session_id, str) or not 1 <= len(session_id) <= 128:
            raise ValueError("Session ID must contain 1 to 128 characters")
        if not 0.01 <= finite_seconds(partial_timeout) <= 60:
            raise ValueError("Partial timeout must be between 0.01 and 60 seconds")
        if not partial_timeout <= finite_seconds(gap_timeout) <= 3600:
            raise ValueError("Gap timeout must be between partial timeout and 3600")
        for name, value, limit in (
            ("max_sources", max_sources, 32), ("history_size", history_size, 256)
        ):
            if type(value) is not int or not 1 <= value <= limit:
                raise ValueError(f"{name} must be an integer from 1 to {limit}")
        self.session_id = session_id
        self.origin = Origin(origin)
        self.profile = DecoderProfile(profile)
        self.partial_timeout = partial_timeout
        self.gap_timeout = gap_timeout
        self.max_sources = max_sources
        self.stats = StreamStats()
        self.recent_frames: deque[Observation] = deque(maxlen=history_size)
        self.recent_datagrams: deque[Datagram] = deque(maxlen=4)
        self.events: deque[dict] = deque(maxlen=history_size)
        self._sources: OrderedDict[Endpoint, _Source] = OrderedDict()
        self._retired = FramingStats()
        self._last_index: int | None = None
        self._time: float | None = None

    def feed(self, datagram: Datagram) -> list[Observation]:
        expected = 0 if self._last_index is None else self._last_index + 1
        if datagram.index != expected:
            self.stats.discontinuities += 1
            self.reset(reason="record_index_discontinuity")
        self._last_index = datagram.index
        observations = self.expire(now=datagram.stream_time)
        self.stats.datagrams += 1
        self.stats.bytes_received += len(datagram.data)
        self.recent_datagrams.append(datagram)
        source = self._sources.get(datagram.source)
        if source is None:
            if len(self._sources) == self.max_sources:
                endpoint, evicted = self._sources.popitem(last=False)
                self._retire(endpoint, evicted, "source_evicted")
                self.stats.source_evictions += 1
            source = _Source(
                FrameBuffer(partial_timeout=self.partial_timeout), datagram.stream_time
            )
            self._sources[datagram.source] = source
        elif datagram.stream_time - source.last_seen >= self.gap_timeout:
            self._event(datagram.source, source, "source_gap")
            source.buffer.reset()
            source.receipts.clear()
            self.stats.gap_resets += 1
        self._sources.move_to_end(datagram.source)
        source.last_seen = datagram.stream_time
        if datagram.data:
            source.receipts[datagram.index] = datagram.received_at
            if len(source.receipts) > 256:
                source.receipts.popitem(last=False)
        packets = source.buffer.feed(
            datagram.data, now=datagram.stream_time, record_index=datagram.index
        )
        observations.extend(self._observations(datagram.source, source, packets))
        return observations

    def expire(self, *, now: float) -> list[Observation]:
        finite_seconds(now)
        if self._time is not None and now < self._time:
            self.stats.discontinuities += 1
            self.reset(reason="clock_reversal")
        self._time = now
        observations = []
        for endpoint, source in self._sources.items():
            pending = source.buffer.pending
            before = source.buffer.stats.expired_partial_bytes
            packets = source.buffer.expire(now=now)
            if source.buffer.stats.expired_partial_bytes != before:
                self.events.append({
                    "reason": "partial_expiry", "source": list(endpoint),
                    "stream_time": now, "pending_before_hex": pending.hex(),
                })
            observations.extend(self._observations(endpoint, source, packets))
        return observations

    def reset(self, *, reason: str) -> None:
        """A session, socket or known recording discontinuity ends all partials."""
        for endpoint, source in self._sources.items():
            self._retire(endpoint, source, reason)
        self._sources.clear()
        self._time = None

    def diagnostics(self) -> dict:
        framing = asdict(self._retired)
        for source in self._sources.values():
            self._merge(framing, asdict(source.buffer.stats))
        return {
            "session_id": self.session_id,
            "origin": self.origin.value,
            "profile": self.profile.value,
            "stats": asdict(self.stats),
            "framing": framing,
            "sources": [
                {"source": list(endpoint), "pending_hex": source.buffer.pending.hex()}
                for endpoint, source in self._sources.items()
            ],
            "recent_frames": [item.as_dict() for item in self.recent_frames],
            "recent_datagrams": [
                {
                    "source": list(item.source), "index": item.index,
                    "received_at": item.received_at.isoformat(),
                    "stream_time": item.stream_time, "data_hex": item.data.hex(),
                }
                for item in self.recent_datagrams
            ],
            "events": list(self.events),
        }

    def _observations(
        self, endpoint: Endpoint, source: _Source, packets: list[ReceivedFrame]
    ) -> list[Observation]:
        observations = []
        for packet in packets:
            index = packet.record_index
            received_at = source.receipts[index]
            result = decode_frame(packet.frame, profile=self.profile)
            observation = Observation(
                result, self.origin, self.session_id, endpoint, received_at,
                packet.received_at, packet.first_received_at, index,
            )
            if result.reason in DECODED_REASONS:
                self.stats.decoded_frames += 1
            else:
                self.stats.unknown_frames += 1
            observations.append(observation)
            self.recent_frames.append(observation)
        return observations

    def _event(self, endpoint: Endpoint, source: _Source, reason: str) -> None:
        self.events.append({
            "reason": reason, "source": list(endpoint),
            "stream_time": self._time,
            "pending_before_hex": source.buffer.pending.hex(),
        })

    def _retire(self, endpoint: Endpoint, source: _Source, reason: str) -> None:
        self._event(endpoint, source, reason)
        source.buffer.reset()
        totals = asdict(self._retired)
        self._merge(totals, asdict(source.buffer.stats))
        self._retired = FramingStats(**totals)

    @staticmethod
    def _merge(total: dict, addition: dict) -> None:
        for key, value in addition.items():
            if key == "peak_buffer_bytes":
                total[key] = max(total[key], value)
            else:
                total[key] += value
