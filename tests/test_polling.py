"""Only captured reads may be sent; reply gates, timeouts and cleanup are bounded."""

import asyncio

import pytest

from custom_components.comfortzone_serial.telemetry.decoder import DecoderProfile
from custom_components.comfortzone_serial.telemetry.framing import Frame
from custom_components.comfortzone_serial.telemetry.polling import (
    PollingSettings,
    temperature_request,
)
from custom_components.comfortzone_serial.telemetry.stream import (
    Origin,
    TelemetryPipeline,
)
from custom_components.comfortzone_serial.telemetry.udp import (
    NetworkSettings,
    TelemetryListener,
)
from tests.test_ex35 import corrected, datagrams
from tests.test_udp import FakeTransport


class PollTransport(FakeTransport):
    def __init__(self, protocol):
        super().__init__(protocol)
        self.sent = []
        self.send_error = None

    def sendto(self, data, endpoint):
        assert not self.closed
        if self.send_error:
            raise self.send_error
        assert Frame(data).command == ord("R")
        self.sent.append((data, endpoint))


def test_polling_split_response_timeout_recovery_and_close(monkeypatch):
    async def scenario():
        async def endpoint(factory, **kwargs):
            protocol = factory()
            transport = PollTransport(protocol)
            protocol.connection_made(transport)
            return transport, protocol

        monkeypatch.setattr(
            asyncio.get_running_loop(), "create_datagram_endpoint", endpoint
        )
        received, errors = [], []
        listener = TelemetryListener(
            NetworkSettings("192.0.2.1", source_port=4001),
            TelemetryPipeline(
                session_id="test", origin=Origin.LIVE, profile=DecoderProfile.EX35_0B15
            ),
            received.extend,
            errors.append,
            polling=PollingSettings(),
        )
        await listener.start()
        await asyncio.sleep(0)
        transport = listener.receiver._transport
        assert transport.sent == [(temperature_request(), ("192.0.2.1", 4001))]
        chunks = datagrams("standalone-split-reply.hex")
        # A wrong sender, pump address or register must not satisfy the request.
        listener.receiver.datagram_received(b"".join(chunks), ("192.0.2.2", 4001))
        listener.receiver.datagram_received(b"".join(chunks), ("192.0.2.1", 4002))
        for index in (6, 17):
            wrong = bytearray(b"".join(chunks))
            wrong[index] ^= 1
            listener.receiver.datagram_received(
                corrected(wrong).raw, ("192.0.2.1", 4001)
            )
        assert not received
        listener.receiver.datagram_received(chunks[0], ("192.0.2.1", 4001))
        assert not received
        listener.receiver.datagram_received(chunks[1], ("192.0.2.1", 4001))
        assert len(received) == 1 and listener.poll_stats.replies_received == 1
        # Duplicates after a completed request cannot refresh measurements.
        listener.receiver.datagram_received(b"".join(chunks), ("192.0.2.1", 4001))
        assert len(received) == 1
        listener._poll_timer.cancel()
        listener._poll()
        listener.receiver.datagram_received(chunks[0], ("192.0.2.1", 4001))
        listener._response_timer.cancel()
        listener._timeout()
        assert listener.poll_stats.timeouts == 1
        listener.receiver.datagram_received(chunks[1], ("192.0.2.1", 4001))
        assert len(received) == 1
        listener._poll_timer.cancel()
        listener._poll()
        listener.receiver.datagram_received(b"".join(chunks), ("192.0.2.1", 4001))
        assert len(received) == 2
        assert listener.poll_stats.requests_sent == 3
        timer = listener._poll_timer
        listener.close()
        await listener.wait_closed()
        listener._poll()
        assert timer.cancelled() and len(transport.sent) == 3 and not errors

    asyncio.run(scenario())


def test_poll_send_failure_closes_and_reports_once(monkeypatch):
    async def scenario():
        async def endpoint(factory, **kwargs):
            protocol = factory()
            transport = PollTransport(protocol)
            transport.send_error = OSError("send failed")
            protocol.connection_made(transport)
            return transport, protocol

        monkeypatch.setattr(
            asyncio.get_running_loop(), "create_datagram_endpoint", endpoint
        )
        errors = []
        listener = TelemetryListener(
            NetworkSettings("192.0.2.1"),
            TelemetryPipeline(
                session_id="test", origin=Origin.LIVE, profile=DecoderProfile.EX35_0B15
            ),
            lambda _: None,
            errors.append,
            polling=PollingSettings(),
        )
        await listener.start()
        await asyncio.sleep(0)
        await listener.wait_closed()
        assert len(errors) == 1 and not listener.receiver.running
        assert listener._poll_timer is listener._response_timer is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"interval": 0},
        {"interval": 14},
        {"interval": float("nan")},
        {"destination_port": 0},
        {"address": "123"},
        {"address": "zzzzzzzz"},
    ],
)
def test_invalid_polling_settings(kwargs):
    with pytest.raises(ValueError):
        PollingSettings(**kwargs)


def test_polling_requires_supported_profile():
    with pytest.raises(ValueError, match="EX35"):
        TelemetryListener(
            NetworkSettings("192.0.2.1"),
            TelemetryPipeline(session_id="test", origin=Origin.LIVE),
            lambda _: None,
            lambda _: None,
            polling=PollingSettings(),
        )


def test_localhost_request_and_split_reply_use_the_same_bound_socket():
    import socket

    async def scenario():
        loop = asyncio.get_running_loop()
        # Both endpoints are localhost. Never resolve/contact a LAN device.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
            peer.bind(("127.0.0.1", 0))
            peer.setblocking(False)
            peer_port = peer.getsockname()[1]
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.bind(("127.0.0.1", 0))
                local_port = probe.getsockname()[1]
            emitted = asyncio.Event()
            received, errors = [], []

            def observe(items):
                received.extend(items)
                emitted.set()

            listener = TelemetryListener(
                NetworkSettings("127.0.0.1", "127.0.0.1", local_port, peer_port),
                TelemetryPipeline(
                    session_id="loopback",
                    origin=Origin.LIVE,
                    profile=DecoderProfile.EX35_0B15,
                ),
                observe,
                errors.append,
                polling=PollingSettings(destination_port=peer_port),
            )
            try:
                await listener.start()
                request, source = await asyncio.wait_for(
                    loop.sock_recvfrom(peer, 255), 1
                )
                assert source == ("127.0.0.1", local_port)
                assert request == temperature_request()
                for chunk in datagrams("standalone-split-reply.hex"):
                    await loop.sock_sendto(peer, chunk, source)
                await asyncio.wait_for(emitted.wait(), 1)
                assert len(received) == 1
                assert len(received[0].result.frame.raw) == 139
                assert listener.poll_stats.replies_received == 1 and not errors
            finally:
                listener.close()
                await listener.wait_closed()

    asyncio.run(scenario())


def test_multiple_queries_rotate_match_only_pending_read_and_never_overlap(monkeypatch):
    from custom_components.comfortzone_serial.telemetry.polling import read_request
    from tests.test_queries import captured_frames

    async def scenario():
        async def endpoint(factory, **kwargs):
            protocol = factory()
            transport = PollTransport(protocol)
            protocol.connection_made(transport)
            return transport, protocol

        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "create_datagram_endpoint", endpoint)
        emitted, errors = [], []
        settings = PollingSettings(queries=("power", "counters", "operation"))
        listener = TelemetryListener(
            NetworkSettings("192.0.2.1", source_port=4001),
            TelemetryPipeline(
                session_id="multi", origin=Origin.LIVE, profile=DecoderProfile.EX35_0B15
            ),
            emitted.extend,
            errors.append,
            polling=settings,
        )
        frames = captured_frames()
        await listener.start()
        await asyncio.sleep(0)
        transport = listener.receiver._transport
        try:
            assert len(settings.reads) == 4
            assert settings.reads[0].name == "power"
            # The normal 30-second spacing applies even after a quick reply.
            assert 29 < listener._poll_timer.when() - loop.time() <= 30
            # A second poll while waiting cannot create a second outstanding read.
            listener._poll_timer.cancel()
            listener._poll()
            assert len(transport.sent) == 1
            # A valid but unrelated reply cannot satisfy the outstanding request.
            listener.receiver.datagram_received(
                frames[settings.reads[1].register].raw, ("192.0.2.1", 4001)
            )
            assert not emitted
            for index, read in enumerate(settings.reads):
                assert transport.sent[-1][0] == read_request(read)
                raw = frames[read.register].raw
                if index == 1:
                    # Lost response: advance only after timeout, at normal spacing.
                    listener.receiver.datagram_received(raw[:15], ("192.0.2.1", 4001))
                    listener._response_timer.cancel()
                    listener._timeout()
                    assert listener.last_timeout == read
                    listener.receiver.datagram_received(raw, ("192.0.2.1", 4001))
                else:
                    for chunk in (raw[:10], raw[10:37], raw[37:]):
                        listener.receiver.datagram_received(chunk, ("192.0.2.1", 4001))
                    before = len(emitted)
                    listener.receiver.datagram_received(raw, ("192.0.2.1", 4001))
                    assert len(emitted) == before  # Duplicate cannot refresh.
                listener._poll_timer.cancel()
                listener._poll()
            assert transport.sent[-1][0] == read_request(settings.reads[0])
            assert listener.poll_stats.requests_sent == 5
            assert listener.poll_stats.replies_received == 3
            assert listener.poll_stats.timeouts == 1
            # Even an entirely unmapped compressor reply satisfies its exact read.
            assert emitted[-1].result.frame.register == settings.reads[-1].register
            assert not errors
            poll_timer, response_timer = listener._poll_timer, listener._response_timer
        finally:
            listener.close()
            await listener.wait_closed()
        assert poll_timer.cancelled() and response_timer.cancelled()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"interval": 0},
        {"interval": -1},
        {"interval": float("nan")},
        {"interval": 3601},
        {"request_delay": -0.1},
        {"request_delay": float("inf")},
        {"request_delay": 3601},
    ],
)
def test_cycle_polling_rejects_invalid_timing(kwargs):
    with pytest.raises(ValueError):
        PollingSettings(cycle=True, **kwargs)


def test_cycle_timing_and_legacy_fixed_interval_defaults():
    settings = PollingSettings(cycle=True, interval=0.1, request_delay=0)
    assert settings.interval == 0.1 and settings.request_delay == 0
    assert not PollingSettings().cycle
    with pytest.raises(ValueError):
        PollingSettings(interval=0.1)


def test_cycles_advance_after_reply_or_timeout_and_handle_shared_traffic(monkeypatch):
    from tests.test_queries import captured_frames

    async def scenario():
        loop = asyncio.get_running_loop()
        original_clock = loop.time
        clock_offset = 0.0
        monkeypatch.setattr(loop, "time", lambda: original_clock() + clock_offset)

        async def advance(seconds):
            nonlocal clock_offset
            clock_offset += seconds
            for _ in range(3):
                await asyncio.sleep(0)

        async def endpoint(factory, **kwargs):
            protocol = factory()
            transport = PollTransport(protocol)
            protocol.connection_made(transport)
            return transport, protocol

        monkeypatch.setattr(loop, "create_datagram_endpoint", endpoint)
        emitted, errors, events = [], [], []
        settings = PollingSettings(
            queries=("power", "counters"), cycle=True, interval=2, request_delay=0.25
        )
        listener = TelemetryListener(
            NetworkSettings("192.0.2.1", source_port=4001),
            TelemetryPipeline(
                session_id="cycles",
                origin=Origin.LIVE,
                profile=DecoderProfile.EX35_0B15,
            ),
            emitted.extend,
            errors.append,
            polling=settings,
            on_poll_progress=lambda: events.append(
                (listener.poll_stats.requests_sent, listener.poll_stats.timeouts)
            ),
        )
        frames = captured_frames()
        power = frames[settings.reads[0].register].raw
        counters = frames[settings.reads[1].register].raw
        temperature = b"".join(datagrams("standalone-reply.hex"))
        await listener.start()
        await asyncio.sleep(0)
        transport = listener.receiver._transport

        def receive(data):
            listener.receiver.datagram_received(data, ("192.0.2.1", 4001))

        try:
            assert len(transport.sent) == 1 and listener._poll_timer is None
            # HA's unrelated temperature traffic cannot finish this power read.
            receive(temperature)
            assert listener._poll_timer is None and not emitted
            # A compatible reply (from either poller) advances the local cycle.
            # The captured addresses/register do not identify which client asked.
            receive(power[:20])
            assert listener._poll_timer is None
            receive(power[20:])
            timer = listener._poll_timer
            assert 0.20 < timer.when() - loop.time() <= 0.25
            receive(power)  # Duplicate cannot move the scheduled next request.
            assert listener._poll_timer is timer and len(emitted) == 1
            await advance(0.1)
            assert len(transport.sent) == 1
            await advance(0.2)
            assert len(transport.sent) == 2 and listener.last_read.name == "counters"
            receive(temperature)
            receive(counters)
            # The second cycle starts around t=2, not 2 seconds after completion.
            assert 1.5 < listener._poll_timer.when() - loop.time() < 1.8
            await advance(1.3)
            assert len(transport.sent) == 2
            await advance(0.5)
            assert len(transport.sent) == 3 and listener.last_read.name == "power"
            # Lost reply: no overlapping read despite the short cycle interval.
            await advance(5)
            receive(temperature)
            assert len(transport.sent) == 3
            await advance(5.1)
            assert listener.poll_stats.timeouts == 1
            assert len(transport.sent) == 3
            await advance(0.3)
            assert len(transport.sent) == 4 and listener.last_read.name == "counters"
            receive(counters)
            # The cycle overran. Resume after the pause without catch-up bursts.
            assert 0.20 < listener._poll_timer.when() - loop.time() <= 0.25
            await advance(0.3)
            assert len(transport.sent) == 5 and listener.last_read.name == "power"
            receive(power)
            timer = listener._poll_timer
            assert events == [(1, 0), (2, 0), (3, 0), (3, 1), (4, 1), (5, 1)]
            assert listener.poll_stats.replies_received == 4 and not errors
        finally:
            listener.close()
            await listener.wait_closed()
        assert timer.cancelled()
        await advance(30)
        assert len(transport.sent) == 5

    asyncio.run(scenario())
