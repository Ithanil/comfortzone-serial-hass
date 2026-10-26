"""Asyncio UDP reception with optional, bounded captured EX35 read polling."""

import asyncio
import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .decoder import DecoderProfile
from .polling import (
    RESPONSE_TIMEOUT,
    PollingSettings,
    PollingStats,
    read_request,
)
from .queries import TEMPERATURE_READ, ReadDefinition
from .stream import Datagram, Observation, Origin, TelemetryPipeline, ipv4, port


@dataclass(frozen=True, slots=True)
class NetworkSettings:
    source_ip: str
    bind_host: str = "0.0.0.0"
    bind_port: int = 4001
    source_port: int | None = None

    def __post_init__(self) -> None:
        ipv4(self.source_ip)
        ipv4(self.bind_host, allow_unspecified=True)
        port(self.bind_port)
        if self.source_port is not None:
            port(self.source_port)

    def accepts(self, endpoint: tuple[str, int]) -> bool:
        return endpoint[0] == self.source_ip and (
            self.source_port is None or endpoint[1] == self.source_port
        )


@dataclass(slots=True)
class ReceiverStats:
    received: int = 0
    accepted: int = 0
    rejected: int = 0
    bytes_received: int = 0
    errors: int = 0


class UDPReceiver(asyncio.DatagramProtocol):
    """One-shot receiver. Close is idempotent; a new instance starts a new session.

    Callbacks run in the event loop and must be fast and nonblocking. Callback or
    transport failure closes the socket and is reported to the owner for recovery.
    """

    def __init__(
        self,
        settings: NetworkSettings,
        on_datagram: Callable[[Datagram], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        self.settings = settings
        self.on_datagram = on_datagram
        self.on_error = on_error
        self.stats = ReceiverStats()
        self.started_at: datetime | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._transport: asyncio.DatagramTransport | None = None
        self._closed: asyncio.Future | None = None
        self._closing = False
        self._started = False
        self._opening = False
        self._origin = 0.0

    @property
    def running(self) -> bool:
        return self._transport is not None and not self._closing

    @property
    def elapsed(self) -> float:
        return self._loop.time() - self._origin if self._loop else 0.0

    async def start(self) -> None:
        if self._started or self._closing:
            raise RuntimeError("Create a new receiver to start another session")
        self._started = True
        self._opening = True
        self._loop = asyncio.get_running_loop()
        self._closed = self._loop.create_future()
        self._origin = self._loop.time()
        self.started_at = datetime.now(UTC)
        try:
            await self._loop.create_datagram_endpoint(
                lambda: self,
                local_addr=(self.settings.bind_host, self.settings.bind_port),
                family=socket.AF_INET,
            )
        except BaseException:
            self._opening = False
            self.close()
            await self.wait_closed()
            raise
        self._opening = False
        if self._closing:
            self.close()

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport
        if self._closing:
            transport.close()

    def send_temperature_read(self, settings: PollingSettings) -> None:
        """Compatibility wrapper for the original temperature-only operation."""
        self.send_read(settings, TEMPERATURE_READ)

    def send_read(self, settings: PollingSettings, read: ReadDefinition) -> None:
        """Send a supported captured read through the bound receive socket."""
        if not self.running:
            raise OSError("UDP receiver is not running")
        self._transport.sendto(
            read_request(read, settings.address),
            (self.settings.source_ip, settings.destination_port),
        )

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self._closing:
            return
        self.stats.received += 1
        self.stats.bytes_received += len(data)
        if not self.settings.accepts(addr):
            self.stats.rejected += 1
            return
        try:
            datagram = Datagram(
                data, addr, datetime.now(UTC), self.elapsed, self.stats.accepted
            )
            self.stats.accepted += 1
            self.on_datagram(datagram)
        except Exception as error:
            self._fail(error)

    def error_received(self, exc: Exception) -> None:
        self._fail(exc)

    def connection_lost(self, exc: Exception | None) -> None:
        unexpected = not self._closing
        self._transport = None
        if self._closed is not None and not self._closed.done():
            self._closed.set_result(None)
        if unexpected:
            self._fail(exc or OSError("UDP transport closed unexpectedly"))

    def close(self) -> None:
        self._closing = True
        if self._transport is not None:
            self._transport.close()
        elif not self._opening and self._closed is not None and not self._closed.done():
            self._closed.set_result(None)

    async def wait_closed(self) -> None:
        if self._closed is not None:
            await asyncio.shield(self._closed)

    def _fail(self, error: Exception) -> None:
        if self._closing:
            return
        self.stats.errors += 1
        self.close()
        try:
            self.on_error(error)
        except Exception as callback_error:
            if self._loop is not None:
                self._loop.call_exception_handler(
                    {
                        "message": "ComfortZone UDP error callback failed",
                        "exception": callback_error,
                    }
                )


class TelemetryListener:
    """Own a live pipeline, socket and partial-expiry timer as one lifecycle."""

    def __init__(
        self,
        settings: NetworkSettings,
        pipeline: TelemetryPipeline,
        on_observations: Callable[[list[Observation]], None],
        on_error: Callable[[Exception], None],
        *,
        polling: PollingSettings | None = None,
        on_poll_progress: Callable[[], None] | None = None,
    ) -> None:
        if pipeline.origin is not Origin.LIVE:
            raise ValueError("A live listener requires a live pipeline")
        if polling is not None and pipeline.profile is not DecoderProfile.EX35_0B15:
            raise ValueError("Polling requires the EX35 0b15 profile")
        self.pipeline = pipeline
        self.on_observations = on_observations
        self.on_error = on_error
        self.receiver = UDPReceiver(settings, self._datagram, self._error)
        self._timer: asyncio.TimerHandle | None = None
        self.polling = polling
        self.on_poll_progress = on_poll_progress
        self.poll_stats = PollingStats()
        self._poll_timer: asyncio.TimerHandle | None = None
        self._response_timer: asyncio.TimerHandle | None = None
        self._sent_at: float | None = None
        self._read_index = 0
        self._cycle_started_at: float | None = None
        self.last_read: ReadDefinition | None = None
        self.last_timeout: ReadDefinition | None = None

    async def start(self) -> None:
        try:
            await self.receiver.start()
            if self.receiver.running:
                self._schedule()
                if self.polling is not None:
                    self._poll_timer = asyncio.get_running_loop().call_soon(self._poll)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        for timer in (self._poll_timer, self._response_timer):
            if timer is not None:
                timer.cancel()
        self._poll_timer = self._response_timer = None
        self._sent_at = None
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self.receiver.close()
        self.pipeline.reset(reason="listener_closed")

    async def wait_closed(self) -> None:
        await self.receiver.wait_closed()

    def _datagram(self, datagram: Datagram) -> None:
        self._emit(self.pipeline.feed(datagram))

    def _emit(self, observations: list[Observation]) -> None:
        if self.polling is not None:
            accepted = []
            for observation in observations:
                if (
                    self._sent_at is not None
                    and observation.first_stream_time >= self._sent_at
                    and self.polling.matches(observation.result.frame, self.last_read)
                ):
                    accepted.append(observation)
                    self.poll_stats.replies_received += 1
                    self._sent_at = None
                    if self._response_timer is not None:
                        self._response_timer.cancel()
                        self._response_timer = None
                    self._schedule_next_read()
                else:
                    self.poll_stats.ignored_frames += 1
            observations = accepted
        if observations:
            self.on_observations(observations)

    def _poll(self) -> None:
        self._poll_timer = None
        if not self.receiver.running or self.polling is None:
            return
        if self._sent_at is not None:
            # Even a delayed/reentered callback must not overlap a pending read.
            if not self.polling.cycle:
                self._poll_timer = asyncio.get_running_loop().call_later(
                    self.polling.interval, self._poll
                )
            return
        try:
            self.pipeline.reset(reason="read_request")
            reads = self.polling.reads
            self.last_read = reads[self._read_index]
            self._sent_at = self.receiver.elapsed
            if self._read_index == 0:
                self._cycle_started_at = self._sent_at
            self.receiver.send_read(self.polling, self.last_read)
            if not self.receiver.running:
                return  # An asynchronous transport error may close synchronously.
            self.poll_stats.requests_sent += 1
            self._read_index = (self._read_index + 1) % len(reads)
            loop = asyncio.get_running_loop()
            self._response_timer = loop.call_later(RESPONSE_TIMEOUT, self._timeout)
            if not self.polling.cycle:
                self._poll_timer = loop.call_later(self.polling.interval, self._poll)
            if self.on_poll_progress is not None:
                self.on_poll_progress()
        except Exception as error:
            self._error(error)

    def _timeout(self) -> None:
        self._response_timer = None
        if self._sent_at is None:
            return
        self.poll_stats.timeouts += 1
        self.last_timeout = self.last_read
        self._sent_at = None
        self.pipeline.reset(reason="read_timeout")
        try:
            self._schedule_next_read()
            if self.on_poll_progress is not None:
                self.on_poll_progress()
        except Exception as error:
            self._error(error)

    def _schedule_next_read(self) -> None:
        """Advance this listener's cycle after a compatible reply or timeout.

        Other pollers remain independent. The captured protocol has no request
        ID, so a matching response may have been triggered by another client.
        """
        if not self.receiver.running or self.polling is None or not self.polling.cycle:
            return
        delay = self.polling.request_delay
        if self._read_index == 0:
            elapsed = self.receiver.elapsed - self._cycle_started_at
            delay = max(delay, self.polling.interval - elapsed)
        # Actual next-cycle start becomes its new origin. Slow cycles never
        # overlap or accumulate catch-up polls. Even zero delay yields the loop.
        self._poll_timer = asyncio.get_running_loop().call_later(delay, self._poll)

    def _schedule(self) -> None:
        self._timer = asyncio.get_running_loop().call_later(
            min(self.pipeline.partial_timeout / 2, 0.25), self._expire
        )

    def _expire(self) -> None:
        self._timer = None
        try:
            self._emit(self.pipeline.expire(now=self.receiver.elapsed))
            if self.receiver.running:
                self._schedule()
        except Exception as error:
            self._error(error)

    def _error(self, error: Exception) -> None:
        self.close()
        self.on_error(error)
