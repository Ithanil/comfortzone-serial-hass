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
