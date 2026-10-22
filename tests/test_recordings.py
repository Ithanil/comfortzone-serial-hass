"""Capture format, finite storage and offline replay using synthetic records."""

import io
import json
import socket
from dataclasses import asdict

import pytest

from custom_components.comfortzone_serial.telemetry.decoder import DecoderProfile
from custom_components.comfortzone_serial.telemetry.stream import (
    Origin,
    TelemetryPipeline,
)
from custom_components.comfortzone_serial.telemetry.udp import NetworkSettings
from tools.records import (
    FOOTER_RESERVE,
    MAX_LINE_BYTES,
    CaptureWriter,
    RecordError,
    datagram_record,
    encode,
    read_records,
)
from tools.replay import main as replay_main
from tools.replay import replay

from .fixtures import make_frame, temperature_frame
from .test_stream import SOURCE, STAMP, datagram


def session(session_id="synthetic"):
    return {
        "type": "session", "format": "comfortzone-udp", "version": 1,
        "session_id": session_id, "started_at": STAMP.isoformat(),
        "network": asdict(NetworkSettings(SOURCE[0])),
        "metadata": {"serial": "unknown", "connection": "synthetic fixture"},
    }


def end(session_id="synthetic", count=0, time=2):
    return {
        "type": "end", "session_id": session_id, "records_written": count,
        "stream_time": time, "reason": "duration",
    }


def read(*records):
    return list(read_records(io.BytesIO(b"".join(encode(item) for item in records))))


def test_capture_roundtrip_preserves_binary_boundaries_times_and_order(tmp_path):
    path = tmp_path / "data.jsonl"
    packets = [datagram(bytes(range(256))), datagram(b"", 1, 0.1)]
    writer = CaptureWriter(path, session(), max_bytes=8000)
    try:
        assert all(writer.write(packet) for packet in packets)
        writer.finish(reason="duration", stream_time=1, counters={"accepted": 2})
        writer.finish(reason="ignored", stream_time=9, counters={})
    finally:
        writer.close()
    with path.open("rb") as stream:
        records = list(read_records(stream))
    assert records[1:3] == [datagram_record("synthetic", item) for item in packets]
    assert records[-1]["records_written"] == 2
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_size == writer.bytes_written <= 8000
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        CaptureWriter(path, session(), max_bytes=8000)
    assert path.read_bytes() == before


def test_size_limit_reserves_footer_and_stops_before_datagram(tmp_path):
    header = session()
    packet = datagram(temperature_frame())
    limit = len(encode(header)) + FOOTER_RESERVE + len(encode(datagram_record(
        "synthetic", packet
    )))
    path = tmp_path / "bounded.jsonl"
    writer = CaptureWriter(path, header, max_bytes=limit)
    try:
        assert writer.write(packet)
        assert not writer.write(datagram(b"too much", 1, 0.1))
        writer.finish(reason="byte_limit", stream_time=1, counters={"not_recorded": 1})
    finally:
        writer.close()
    assert path.stat().st_size <= limit
    with path.open("rb") as stream:
        records = list(read_records(stream))
    assert len(records) == 3
    assert records[-1]["records_written"] == 1


def test_too_small_byte_limit_does_not_create_file(tmp_path):
    path = tmp_path / "none.jsonl"
    with pytest.raises(ValueError):
        CaptureWriter(path, session(), max_bytes=10)
    assert not path.exists()


@pytest.mark.parametrize("change", [
    {"index": True}, {"index": -1}, {"stream_time": -0.1},
    {"stream_time": "1.0"}, {"data_hex": "abc"}, {"data_hex": "aa bb"},
    {"stream_time": 10**1000},
    {"data_hex": "xx"}, {"source": ["host.local", 4001]},
    {"source": ["192.0.2.1", 0]}, {"received_at": "2026-01-01T00:00:00"},
    {"session_id": ""}, {"type": "something_else"},
])
def test_malformed_datagram_records_fail_with_line_number(change):
    record = datagram_record("synthetic", datagram(b"valid")) | change
    with pytest.raises(RecordError, match="Line 2"):
        read(session(), record)


@pytest.mark.parametrize("raw", [
    b'{"type":"session","type":"end"}\n', b'{"stream_time":NaN}\n',
    b'not JSON\n', b'{}', b'\xff\n', b'[]\n', b'\n',
    b'[' * 2000 + b']' * 2000 + b'\n',
])
def test_invalid_truncated_duplicate_or_deep_json_is_rejected(raw):
    with pytest.raises(RecordError, match="Line 1"):
        list(read_records(io.BytesIO(raw)))


def test_reader_bounds_line_size_without_reading_rest():
    stream = io.BytesIO(b"x" * (MAX_LINE_BYTES + 100))
    with pytest.raises(RecordError, match="exceeds"):
        list(read_records(stream))
    assert stream.tell() == MAX_LINE_BYTES + 1


@pytest.mark.parametrize("version", [2, "1", True])
def test_unsupported_capture_versions_are_not_guessed(version):
    with pytest.raises(RecordError, match="version"):
        read(session() | {"version": version})


def test_replay_matches_live_pipeline_and_never_opens_socket(monkeypatch):
    raw = temperature_frame()
    packets = [
        datagram(raw[:50]), datagram(raw[50:] + make_frame(command=255), 1, 0.1),
        datagram(b"\x00" * 10 + b"\xff" + raw, 2, 0.2),
    ]
    live = TelemetryPipeline(session_id="synthetic", origin=Origin.LIVE,
                             profile=DecoderProfile.CZBRIDGE_RX50)
    expected = []
    for packet in packets:
        expected += live.feed(packet)
    expected += live.expire(now=2)

    def no_socket(*args, **kwargs):
        raise AssertionError("Offline replay attempted to create a socket")

    monkeypatch.setattr(socket, "socket", no_socket)
    records = read(session(), *(datagram_record("synthetic", item) for item in packets),
                   end(count=3))
    results = list(replay(records, profile=DecoderProfile.CZBRIDGE_RX50))
    frames = [item for item in results if item["type"] == "frame"]
    assert frames == [item.as_dict() | {"origin": "replay"} for item in expected]
    assert results[-1]["capture_complete"]
    assert frames[-1]["received_at"] == packets[-1].received_at.isoformat()
    assert frames[-1]["stream_time"] == 0.2


def test_sessions_are_never_spliced_even_if_session_ids_repeat():
    raw = temperature_frame()
    records = read(
        session(), datagram_record("synthetic", datagram(raw[:50])),
        session(), datagram_record("synthetic", datagram(raw[50:])), end(count=1),
    )
    results = list(replay(records))
    assert not any(item["type"] == "frame" for item in results)
    summaries = [item for item in results if item["type"] == "summary"]
    assert summaries[0]["reason"] == "session_without_end"
    assert not summaries[0]["capture_complete"]
    assert summaries[1]["capture_complete"]


def test_replay_gaps_duplicates_and_reordering_are_visible():
    raw = temperature_frame()
    records = read(
        session(), datagram_record("synthetic", datagram(raw[:50])),
        datagram_record("synthetic", datagram(raw, 2, 0.2)),
        datagram_record("synthetic", datagram(raw, 2, 0.1)), end(count=3),
    )
    results = list(replay(records))
    assert len([item for item in results if item["type"] == "frame"]) == 2
    assert results[-1]["diagnostics"]["stats"]["discontinuities"] == 2


def test_missing_end_flushes_frames_in_recorded_time_and_reports_incomplete():
    records = read(session(), datagram_record("synthetic", datagram(
        b"\x00" * 10 + b"\xff" + temperature_frame()
    )))
    results = list(replay(records))
    assert results[1]["type"] == "frame"
    assert results[1]["stream_time"] == 0
    assert results[1]["origin"] == "replay"
    assert not results[-1]["capture_complete"]


def test_mismatched_session_and_footer_count_are_reported():
    with pytest.raises(RecordError, match="active session"):
        list(replay(read(session(), datagram_record("other", datagram(b"data")))))
    results = list(replay(read(session(), end(count=1))))
    assert results[-1]["reason"] == "record_count_mismatch"
    assert not results[-1]["capture_complete"]


def test_empty_capture_or_backwards_end_time_is_rejected():
    with pytest.raises(RecordError, match="no session"):
        list(replay([]))
    records = read(session(), datagram_record("synthetic", datagram(b"", time=10)),
                   end(count=1, time=1))
    with pytest.raises(RecordError, match="end time"):
        list(replay(records))


def test_replay_cli_defaults_to_observation_and_rejects_corrupt_input(tmp_path, capsys):
    path = tmp_path / "capture.jsonl"
    path.write_bytes(b"".join(encode(item) for item in (
        session(),
        datagram_record("synthetic", datagram(temperature_frame())),
        end(count=1),
    )))
    assert replay_main([str(path)]) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[1]["reason"] == "observe_only"
    assert output[1]["temperatures_celsius"] == {}
    path.write_bytes(b"broken\n")
    assert replay_main([str(path)]) == 1
    assert "Line 1" in capsys.readouterr().err
