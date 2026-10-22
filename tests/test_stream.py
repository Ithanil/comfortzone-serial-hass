"""Source isolation, provenance and bounds using invented datagrams."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.comfortzone_serial.telemetry.decoder import DecoderProfile
from custom_components.comfortzone_serial.telemetry.stream import (
    Datagram,
    Origin,
    TelemetryPipeline,
)

from .fixtures import make_frame, temperature_frame

STAMP = datetime(2026, 1, 1, tzinfo=UTC)
SOURCE = ("192.0.2.1", 4001)


def datagram(data, index=0, time=0, source=SOURCE, stamp=None):
    return Datagram(data, source, stamp or STAMP + timedelta(seconds=time), time, index)


def pipeline(**options):
    return TelemetryPipeline(session_id="synthetic", origin=Origin.LIVE, **options)


def test_sender_endpoints_never_share_partial_bytes():
    raw = temperature_frame()
    pipe = pipeline(profile=DecoderProfile.CZBRIDGE_RX50)
    other = (SOURCE[0], 4002)
    assert pipe.feed(datagram(raw[:50])) == []
    assert pipe.feed(datagram(raw[50:], 1, 0.1, other)) == []
    result = pipe.feed(datagram(raw[50:], 2, 0.2))
    assert len(result) == 1
    assert result[0].source == SOURCE
    assert result[0].first_stream_time == 0
    assert result[0].stream_time == 0.2
    assert result[0].record_index == 2
    assert result[0].result.temperatures[0].celsius == -12.5


def test_source_count_diagnostic_history_and_retired_stats_are_bounded():
    pipe = pipeline(max_sources=2, history_size=3)
    for index in range(20):
        source = ("192.0.2.1", 4001 + index)
        pipe.feed(datagram(
            make_frame(command=255) + b"tail", index, index / 10, source
        ))
    diagnostics = pipe.diagnostics()
    assert len(diagnostics["sources"]) == 2
    assert len(diagnostics["recent_frames"]) == len(diagnostics["events"]) == 3
    assert len(pipe.recent_datagrams) == 4
    assert pipe.stats.source_evictions == 18
    assert diagnostics["framing"]["frames_received"] == 20
    assert diagnostics["framing"]["bytes_received"] == 20 * 26
    assert diagnostics["framing"]["bytes_discarded"] == 18 * 4
    assert any(event["pending_before_hex"] == b"tail".hex() for event in pipe.events)


def test_recovered_frame_keeps_original_timestamp_even_after_wall_clock_jump():
    pipe = pipeline()
    raw = b"\x00" * 10 + b"\xff" + temperature_frame()
    assert pipe.feed(datagram(raw)) == []
    # Empty datagram with the same monotonic time and a different wall clock.
    pipe.feed(datagram(b"", 1, 0, stamp=STAMP + timedelta(days=1)))
    result = pipe.expire(now=1)
    assert len(result) == 1
    assert result[0].received_at == STAMP
    assert result[0].stream_time == 0
    assert result[0].record_index == 0


def test_duplicate_clock_values_retain_exact_record_provenance():
    pipe = pipeline()
    raw = b"\x00" * 10 + b"\xff" + temperature_frame()
    pipe.feed(datagram(raw))
    # This nonempty packet shares a clock value but is not the frame's last byte.
    pipe.feed(datagram(b"\xff", 1, 0, stamp=STAMP + timedelta(days=1)))
    result = pipe.expire(now=1)
    assert result[0].received_at == STAMP
    assert result[0].record_index == 0


def test_maximum_fragmentation_preserves_metadata():
    pipe = pipeline()
    raw = make_frame(payload=b"\x00" * 233)
    result = []
    for index, byte in enumerate(raw):
        result += pipe.feed(datagram(bytes([byte]), index, index / 1000))
    assert len(result) == 1
    assert result[0].record_index == 254
    assert result[0].received_at == STAMP + timedelta(seconds=0.254)


@pytest.mark.parametrize("new_index", [0, 2, 99])
def test_missing_or_reordered_record_index_resets_partial_streams(new_index):
    pipe = pipeline()
    raw = temperature_frame()
    pipe.feed(datagram(raw[:50]))
    result = pipe.feed(datagram(raw, new_index, 0.1))
    assert [item.result.frame.raw for item in result] == [raw]
    assert pipe.stats.discontinuities == 1
    assert pipe.events[0]["reason"] == "record_index_discontinuity"
    assert pipe.events[0]["pending_before_hex"] == raw[:50].hex()


def test_backwards_clock_resets_without_relabeling_received_time():
    pipe = pipeline()
    raw = temperature_frame()
    pipe.feed(datagram(raw[:50], time=10))
    result = pipe.feed(datagram(raw, 1, 1))
    assert len(result) == 1
    assert result[0].stream_time == 1
    assert pipe.stats.discontinuities == 1
    assert pipe.events[0]["reason"] == "clock_reversal"


def test_gap_and_explicit_session_close_preserve_incomplete_tail_evidence():
    pipe = pipeline()
    pipe.feed(datagram(b"partial"))
    pipe.feed(datagram(b"new", 1, 10))
    assert pipe.stats.gap_resets == 1
    assert pipe.events[0]["pending_before_hex"] == b"partial".hex()
    pipe.reset(reason="session_closed")
    assert pipe.events[-1]["pending_before_hex"] == b"new".hex()
    assert pipe.diagnostics()["sources"] == []


def test_unknown_frames_keep_raw_bytes_metadata_and_no_measurements():
    pipe = pipeline(profile=DecoderProfile.CZBRIDGE_RX50)
    raw = make_frame(register=b"\xff" * 9)
    result = pipe.feed(datagram(raw))[0].as_dict()
    assert result["raw_hex"] == raw.hex()
    assert result["reason"] == "unknown_register"
    assert result["temperatures_celsius"] == {}
    assert result["origin"] == "live"
    assert result["session_id"] == "synthetic"


def test_empty_datagrams_do_not_discard_pending_receipt_metadata():
    pipe = pipeline()
    raw = temperature_frame()
    pipe.feed(datagram(raw[:50]))
    for index in range(1, 1000):
        pipe.feed(datagram(b"", index, 0.1))
    result = pipe.feed(datagram(raw[50:], 1000, 0.2))
    assert result[0].first_stream_time == 0
    assert result[0].record_index == 1000


@pytest.mark.parametrize("options", [
    {"max_sources": 0}, {"max_sources": 33}, {"max_sources": True},
    {"history_size": 0}, {"history_size": 257}, {"partial_timeout": float("nan")},
    {"partial_timeout": 0.00001},
    {"partial_timeout": 0}, {"gap_timeout": 0.1}, {"gap_timeout": float("inf")},
])
def test_invalid_bounds_are_rejected(options):
    with pytest.raises(ValueError):
        pipeline(**options)
