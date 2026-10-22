"""Recorder lifecycle and failure tests with synthetic receive callbacks."""

import asyncio

import pytest

from custom_components.comfortzone_serial.telemetry.udp import NetworkSettings
from tools.capture import capture
from tools.records import CaptureWriter, read_records

from .fixtures import temperature_frame
from .test_udp import FakeTransport


def receiver_endpoint(monkeypatch, packets, connected=None):
    transports = []

    async def endpoint(factory, **kwargs):
        protocol = factory()
        transport = FakeTransport(protocol)
        transports.append(transport)
        protocol.connection_made(transport)
        for data, source in packets:
            asyncio.get_running_loop().call_soon(
                protocol.datagram_received, data, source
            )
        if connected is not None:
            connected.set()
        return transport, protocol

    monkeypatch.setattr(
        asyncio.get_running_loop(), "create_datagram_endpoint", endpoint
    )
    return transports


def test_capture_records_before_decoding_and_closes_at_duration(tmp_path, monkeypatch):
    async def scenario():
        packets = [(b"raw unknown", ("192.0.2.1", 4001)),
                   (temperature_frame(), ("192.0.2.1", 4002)),
                   (b"rejected", ("192.0.2.2", 4001))]
        transports = receiver_endpoint(monkeypatch, packets)
        path = tmp_path / "test.jsonl"
        result = await capture(path, NetworkSettings("192.0.2.1"), duration=0.02,
                               install_signals=False, metadata={"serial": "unknown"})
        assert result["reason"] == "duration"
        assert result["records_written"] == 2
        assert result["counters"]["rejected"] == 1
        assert result["counters"]["not_recorded"] == 0
        assert transports[0].closed
        with path.open("rb") as stream:
            records = list(read_records(stream))
        assert records[0]["metadata"]["serial"] == "unknown"
        assert [bytes.fromhex(item["data_hex"]) for item in records[1:-1]] == [
            item[0] for item in packets[:2]
        ]
    asyncio.run(scenario())


def test_queue_overflow_stops_and_reports_loss_without_unbounded_growth(tmp_path,
                                                                      monkeypatch):
    async def scenario():
        packets = [(b"data", ("192.0.2.1", 4001))] * 100
        transports = receiver_endpoint(monkeypatch, packets)
        result = await asyncio.wait_for(capture(
            tmp_path / "full.jsonl", NetworkSettings("192.0.2.1"), duration=10,
            install_signals=False,
        ), 2)
        assert result["reason"] == "queue_overflow"
        assert result["records_written"] == 64
        assert result["counters"]["not_recorded"] == 1
        assert transports[0].closed
    asyncio.run(scenario())


def test_capture_byte_limit_stops_drains_queue_and_keeps_footer(tmp_path, monkeypatch):
    async def scenario():
        receiver_endpoint(monkeypatch, [(b"x" * 1000, ("192.0.2.1", 4001))] * 5)
        path = tmp_path / "bounded.jsonl"
        result = await asyncio.wait_for(capture(
            path, NetworkSettings("192.0.2.1"), max_bytes=5000, duration=10,
            install_signals=False,
        ), 2)
        assert result["reason"] == "byte_limit"
        assert result["records_written"] == 0
        assert result["counters"]["not_recorded"] == 5
        assert path.stat().st_size <= 5000
        with path.open("rb") as stream:
            records = list(read_records(stream))
        assert records[-1]["reason"] == "byte_limit"
    asyncio.run(scenario())


def test_existing_file_is_preserved_and_socket_closed(tmp_path, monkeypatch):
    async def scenario():
        transports = receiver_endpoint(monkeypatch, [])
        path = tmp_path / "existing.jsonl"
        path.write_bytes(b"original")
        with pytest.raises(FileExistsError):
            await capture(path, NetworkSettings("192.0.2.1"), install_signals=False)
        assert path.read_bytes() == b"original"
        assert transports[0].closed
    asyncio.run(scenario())


@pytest.mark.parametrize("error_type", [OSError, RuntimeError])
def test_writer_failure_is_reported_without_hanging_queue(tmp_path, monkeypatch,
                                                        error_type):
    async def scenario():
        transports = receiver_endpoint(
            monkeypatch, [(b"data", ("192.0.2.1", 4001))] * 3
        )

        def fail(*args):
            raise error_type("simulated write failure")

        monkeypatch.setattr(CaptureWriter, "write", fail)
        result = await asyncio.wait_for(capture(
            tmp_path / "failed.jsonl", NetworkSettings("192.0.2.1"), duration=10,
            install_signals=False,
        ), 2)
        assert result["reason"] == "write_error"
        assert result["error"] == "simulated write failure"
        assert result["counters"]["not_recorded"] == 3
        assert transports[0].closed
    asyncio.run(scenario())


def test_cancellation_drains_accepted_records_and_closes_resources(
    tmp_path, monkeypatch
):
    async def scenario():
        connected = asyncio.Event()
        transports = receiver_endpoint(
            monkeypatch, [(b"data", ("192.0.2.1", 4001))], connected
        )
        path = tmp_path / "cancelled.jsonl"
        task = asyncio.create_task(capture(
            path, NetworkSettings("192.0.2.1"), duration=10, install_signals=False
        ))
        await connected.wait()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert transports[0].closed
        with path.open("rb") as stream:
            records = list(read_records(stream))
        assert records[-1]["reason"] == "cancelled"
        assert records[-1]["records_written"] == 1
    asyncio.run(scenario())
