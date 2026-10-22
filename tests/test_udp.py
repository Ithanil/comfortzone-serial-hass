"""Receive-only lifecycle tests, plus synthetic loopback UDP transport tests."""

import asyncio
import socket

import pytest

from custom_components.comfortzone_serial.telemetry.stream import (
    Origin,
    TelemetryPipeline,
)
from custom_components.comfortzone_serial.telemetry.udp import (
    NetworkSettings,
    TelemetryListener,
    UDPReceiver,
)

from .fixtures import temperature_frame


class FakeTransport:
    def __init__(self, protocol):
        self.protocol = protocol
        self.closed = False

    def close(self):
        if not self.closed:
            self.closed = True
            asyncio.get_running_loop().call_soon(self.protocol.connection_lost, None)

    def sendto(self, *args):
        raise AssertionError("Receiver attempted to transmit")


def fake_endpoint(monkeypatch, *, after_connect=None):
    transports = []

    async def endpoint(factory, **kwargs):
        assert kwargs == {"local_addr": ("0.0.0.0", 4001), "family": socket.AF_INET}
        protocol = factory()
        transport = FakeTransport(protocol)
        transports.append(transport)
        protocol.connection_made(transport)
        if after_connect is not None:
            await after_connect()
        return transport, protocol

    monkeypatch.setattr(
        asyncio.get_running_loop(), "create_datagram_endpoint", endpoint
    )
    return transports


@pytest.mark.parametrize("options", [
    {"source_ip": "moxa.local"}, {"source_ip": "::1"}, {"source_ip": "0.0.0.0"},
    {"source_ip": "239.1.2.3"}, {"bind_host": "239.1.2.3"},
    {"bind_port": 0}, {"bind_port": 65536}, {"source_port": False},
])
def test_invalid_network_settings_fail_without_network_access(options):
    with pytest.raises(ValueError):
        NetworkSettings(**({"source_ip": "192.0.2.1"} | options))


def test_filtering_zero_length_datagrams_and_idempotent_close(monkeypatch):
    async def scenario():
        transports = fake_endpoint(monkeypatch)
        records, errors = [], []
        receiver = UDPReceiver(
            NetworkSettings("192.0.2.1", source_port=4001),
            records.append,
            errors.append,
        )
        await receiver.start()
        receiver.datagram_received(b"wrong IP", ("192.0.2.2", 4001))
        receiver.datagram_received(b"wrong port", ("192.0.2.1", 4002))
        receiver.datagram_received(b"", ("192.0.2.1", 4001))
        receiver.datagram_received(b"data", ("192.0.2.1", 4001))
        assert [record.data for record in records] == [b"", b"data"]
        assert [record.index for record in records] == [0, 1]
        assert receiver.stats.rejected == 2
        receiver.close()
        receiver.close()
        await receiver.wait_closed()
        receiver.datagram_received(b"late", ("192.0.2.1", 4001))
        assert len(records) == 2
        assert not receiver.running and transports[0].closed
        assert errors == []
        with pytest.raises(RuntimeError):
            await receiver.start()
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["callback", "transport", "connection_lost"])
def test_errors_close_transport_and_notify_owner_once(monkeypatch, failure):
    async def scenario():
        transports = fake_endpoint(monkeypatch)
        errors = []

        def callback(_record):
            raise RuntimeError("callback failed")

        receiver = UDPReceiver(NetworkSettings("192.0.2.1"), callback, errors.append)
        await receiver.start()
        if failure == "callback":
            receiver.datagram_received(b"data", ("192.0.2.1", 4001))
        elif failure == "transport":
            receiver.error_received(OSError("receive error"))
        else:
            # Simulate a transport that has already closed independently.
            transports[0].closed = True
            receiver.connection_lost(None)
        await receiver.wait_closed()
        receiver.error_received(OSError("late error"))
        assert len(errors) == 1
        assert receiver.stats.errors == 1
        assert not receiver.running
        assert transports[0].closed
    asyncio.run(scenario())


def test_cancel_during_start_closes_created_transport(monkeypatch):
    async def scenario():
        connected = asyncio.Event()

        async def delay():
            connected.set()
            await asyncio.Event().wait()

        transports = fake_endpoint(monkeypatch, after_connect=delay)
        receiver = UDPReceiver(
            NetworkSettings("192.0.2.1"), lambda _: None, lambda _: None
        )
        task = asyncio.create_task(receiver.start())
        await connected.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert transports[0].closed
        assert not receiver.running
    asyncio.run(scenario())


def test_listener_expires_during_silence_and_cancels_timer(monkeypatch):
    async def scenario():
        fake_endpoint(monkeypatch)
        emitted = asyncio.Event()
        observations, errors = [], []
        pipe = TelemetryPipeline(
            session_id="test", origin=Origin.LIVE, partial_timeout=0.02
        )

        def received(items):
            observations.extend(items)
            emitted.set()

        listener = TelemetryListener(NetworkSettings("192.0.2.1"), pipe, received,
                                     errors.append)
        await listener.start()
        listener.receiver.datagram_received(
            b"\x00" * 10 + b"\xff" + temperature_frame(), ("192.0.2.1", 4001)
        )
        await asyncio.wait_for(emitted.wait(), 1)
        assert len(observations) == 1
        assert observations[0].stream_time < 0.02
        timer = listener._timer
        listener.close()
        await listener.wait_closed()
        assert timer.cancelled()
        assert errors == []
    asyncio.run(scenario())


def test_close_while_endpoint_is_opening_waits_for_actual_closure(monkeypatch):
    async def scenario():
        opening = asyncio.Event()
        release = asyncio.Event()
        transports = []

        async def endpoint(factory, **kwargs):
            opening.set()
            await release.wait()
            protocol = factory()
            transport = FakeTransport(protocol)
            transports.append(transport)
            protocol.connection_made(transport)
            return transport, protocol

        monkeypatch.setattr(asyncio.get_running_loop(), "create_datagram_endpoint",
                            endpoint)
        receiver = UDPReceiver(
            NetworkSettings("192.0.2.1"), lambda _: None, lambda _: None
        )
        starting = asyncio.create_task(receiver.start())
        await opening.wait()
        receiver.close()
        closing = asyncio.create_task(receiver.wait_closed())
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        await starting
        await closing
        assert transports[0].closed
        assert not receiver.running
    asyncio.run(scenario())


def test_replay_pipeline_cannot_be_attached_to_a_live_listener():
    pipe = TelemetryPipeline(session_id="test", origin=Origin.REPLAY)
    with pytest.raises(ValueError, match="live"):
        TelemetryListener(
            NetworkSettings("192.0.2.1"), pipe, lambda _: None, lambda _: None
        )


def test_actual_loopback_receive_no_reply_bind_conflict_and_port_release():
    async def scenario():
        # Allocate a loopback port. No pump or LAN address is contacted.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            listen_port = probe.getsockname()[1]
        records, errors = [], []
        received = asyncio.Event()

        def callback(record):
            records.append(record)
            received.set()

        settings = NetworkSettings("127.0.0.1", "127.0.0.1", listen_port)
        receiver = UDPReceiver(settings, callback, errors.append)
        await receiver.start()
        try:
            conflicting = UDPReceiver(settings, callback, errors.append)
            with pytest.raises(OSError):
                await conflicting.start()
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                sender.bind(("127.0.0.1", 0))
                sender.setblocking(False)
                loop = asyncio.get_running_loop()
                await loop.sock_sendto(sender, temperature_frame(),
                                       ("127.0.0.1", listen_port))
                await asyncio.wait_for(received.wait(), 1)
                assert records[0].data == temperature_frame()
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(loop.sock_recvfrom(sender, 1024), 0.03)
        finally:
            receiver.close()
            await receiver.wait_closed()
        replacement = UDPReceiver(settings, callback, errors.append)
        await replacement.start()
        replacement.close()
        await replacement.wait_closed()
        assert not errors
    asyncio.run(scenario())
