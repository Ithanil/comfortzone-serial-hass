"""Exercise stream failure modes using synthetic frames, never a live socket."""

import random

import pytest

from custom_components.comfortzone_serial.telemetry.framing import (
    MAX_FRAME_SIZE,
    Frame,
    FrameBuffer,
    crc8_maxim,
)

from .fixtures import make_frame, reference_crc, temperature_frame


def test_crc_standard_check_and_independent_oracle():
    assert crc8_maxim(b"") == 0
    assert reference_crc(b"123456789") == 0xA1
    assert crc8_maxim(b"123456789") == 0xA1
    for size in range(256):
        data = bytes(range(size))
        assert crc8_maxim(data) == reference_crc(data)


@pytest.mark.parametrize("split", range(1, 136))
def test_every_temperature_frame_split(split):
    raw = temperature_frame()
    buffer = FrameBuffer()
    assert buffer.feed(raw[:split], now=10.0) == []
    packets = buffer.feed(raw[split:], now=10.25)
    assert len(packets) == 1
    assert packets[0].frame.raw == raw
    assert packets[0].first_received_at == 10.0
    assert packets[0].received_at == 10.25
    assert buffer.pending == b""


def test_multiple_frames_and_partial_tail_in_one_datagram():
    raw = temperature_frame()
    buffer = FrameBuffer()
    packets = buffer.feed(raw * 3 + raw[:50], now=1.0)
    assert [packet.frame.raw for packet in packets] == [raw] * 3
    assert buffer.pending == raw[:50]
    assert buffer.feed(raw[50:], now=1.1)[0].frame.raw == raw
    assert buffer.stats.peak_buffer_bytes <= MAX_FRAME_SIZE


@pytest.mark.parametrize("size", [22, 23, 254, 255])
def test_minimum_and_maximum_length_frames(size):
    raw = make_frame(payload=bytes(size - 22))
    buffer = FrameBuffer()
    assert buffer.feed(raw, now=0)[0].frame.raw == raw


def test_garbage_and_corrupt_crc_recover_at_deadline():
    raw = temperature_frame()
    corrupt = raw[:-1] + bytes((raw[-1] ^ 0x01,))
    buffer = FrameBuffer()
    packets = buffer.feed(b"\x00" * 20 + corrupt + raw, now=0)
    packets += buffer.expire(now=1.0)
    assert [packet.frame.raw for packet in packets] == [raw]
    assert packets[0].received_at == 0  # Recovery must not refresh the observation.
    assert buffer.stats.crc_failures > 0
    assert buffer.stats.invalid_length_candidates > 0
    assert buffer.stats.bytes_discarded == 20 + len(corrupt)
    assert buffer.pending == b""


def test_plausible_incomplete_length_cannot_hide_complete_suffix_forever():
    raw = temperature_frame()
    # A plausible 255-byte candidate containing an entire valid frame behind it.
    prefix = b"\x00" * 10 + b"\xff"
    buffer = FrameBuffer()
    assert buffer.feed(prefix + raw, now=5) == []
    assert buffer.expire(now=5.999) == []
    packets = buffer.expire(now=6)
    assert [packet.frame.raw for packet in packets] == [raw]
    assert packets[0].first_received_at == packets[0].received_at == 5
    assert buffer.stats.expired_partial_bytes > 0


def test_valid_frame_containing_another_valid_frame_keeps_outer_boundary():
    nested = make_frame(command=ord("W"))
    outer = make_frame(payload=nested + b"\xff" * 80)
    buffer = FrameBuffer()
    assert buffer.feed(outer[:70], now=0) == []
    packets = buffer.feed(outer[70:], now=0.5)
    assert [packet.frame.raw for packet in packets] == [outer]


def test_recovery_retains_unknown_commands_without_a_stronger_candidate():
    unknown = make_frame(command=0xFF)
    buffer = FrameBuffer()
    packets = buffer.feed(b"\x00" * 20 + unknown, now=0)
    packets += buffer.expire(now=1)
    assert [packet.frame.raw for packet in packets] == [unknown]


def test_valid_unknown_frame_containing_known_frame_keeps_outer_boundary():
    outer = make_frame(payload=make_frame(), command=0xFF)
    buffer = FrameBuffer()
    packets = buffer.feed(outer, now=0)
    assert [packet.frame.raw for packet in packets] == [outer]


def test_partial_timeout_is_not_extended_by_trickle_traffic():
    buffer = FrameBuffer()
    assert buffer.feed(b"\xff" * 30, now=0) == []
    for step in range(1, 10):
        assert buffer.feed(b"\xff", now=step / 10) == []
    assert buffer.stats.expired_partial_bytes == 0
    assert buffer.feed(b"\xff", now=1) == []
    assert buffer.stats.expired_partial_bytes == 30
    assert len(buffer.pending) == 10


def test_partial_header_expires_without_more_datagrams():
    buffer = FrameBuffer()
    buffer.feed(b"\x12\x34", now=4)
    assert buffer.expire(now=5) == []
    assert buffer.pending == b""
    assert buffer.stats.expired_partial_bytes == 2


def test_gap_does_not_join_old_partial_to_new_datagram():
    raw = temperature_frame()
    buffer = FrameBuffer()
    buffer.feed(raw[:50], now=0)
    packets = buffer.feed(raw[50:] + raw, now=2)
    packets += buffer.expire(now=3)
    assert [packet.frame.raw for packet in packets] == [raw]
    assert packets[0].first_received_at == packets[0].received_at == 2


@pytest.mark.parametrize("reset_kind", ["explicit", "clock_reversal"])
def test_discontinuities_clear_partial_state(reset_kind):
    raw = temperature_frame()
    buffer = FrameBuffer()
    buffer.feed(raw[:50], now=10)
    if reset_kind == "explicit":
        buffer.reset()
    packets = buffer.feed(raw, now=1)
    assert [packet.frame.raw for packet in packets] == [raw]
    assert buffer.stats.resets == 1
    assert buffer.stats.bytes_discarded == 50


def test_random_noise_has_bounded_memory_and_accounts_for_every_byte():
    rng = random.Random(73)
    buffer = FrameBuffer()
    packets = []
    total = 0
    for step in range(100):
        data = rng.randbytes(rng.randrange(1, 1000))
        total += len(data)
        packets += buffer.feed(data, now=step / 1000)
        assert len(buffer.pending) < MAX_FRAME_SIZE
    packets += buffer.expire(now=2)
    assert buffer.pending == b""
    assert buffer.stats.peak_buffer_bytes <= MAX_FRAME_SIZE
    assert buffer.stats.bytes_received == total
    consumed = sum(len(p.frame.raw) for p in packets)
    assert consumed + buffer.stats.bytes_discarded == total
    assert buffer.stats.frames_received == len(packets)


def test_large_coalesced_datagram_preserves_all_frames():
    raw = make_frame(payload=b"\x00" * 233)
    buffer = FrameBuffer()
    packets = buffer.feed(raw * 256, now=0)
    assert len(packets) == 256
    assert all(p.frame.raw == raw for p in packets)
    assert buffer.stats.peak_buffer_bytes == MAX_FRAME_SIZE


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_bad_timeout_rejected(timeout):
    with pytest.raises(ValueError, match="timeout"):
        FrameBuffer(partial_timeout=timeout)


@pytest.mark.parametrize("now", [float("inf"), float("-inf"), float("nan")])
def test_bad_clock_rejected_without_altering_stream(now):
    buffer = FrameBuffer()
    buffer.feed(b"abc", now=1)
    with pytest.raises(ValueError, match="time"):
        buffer.feed(b"def", now=now)
    assert buffer.pending == b"abc"
    assert buffer.stats.bytes_received == 3


@pytest.mark.parametrize("raw", [b"", b"\x00" * 21, b"\x00" * 256])
def test_frame_rejects_invalid_size(raw):
    with pytest.raises(ValueError, match="length"):
        Frame(raw)


def test_frame_rejects_length_mismatch_and_crc_failure():
    raw = bytearray(temperature_frame())
    raw[10] = 22
    with pytest.raises(ValueError, match="length field"):
        Frame(raw)
    raw[10] = len(raw)
    raw[-1] ^= 1
    with pytest.raises(ValueError, match="CRC"):
        Frame(raw)


def test_frame_copies_mutable_input():
    raw = bytearray(temperature_frame())
    frame = Frame(raw)
    raw[-1] ^= 1
    assert frame.raw == temperature_frame()
