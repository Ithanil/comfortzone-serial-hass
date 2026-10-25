"""Captured request/reply compatibility, fragmentation and exact layout guards."""

from pathlib import Path

import pytest

from custom_components.comfortzone_serial.telemetry.decoder import (
    DecodeReason,
    DecoderProfile,
    decode_frame,
)
from custom_components.comfortzone_serial.telemetry.framing import (
    Frame,
    FrameBuffer,
    crc8_maxim,
)
from custom_components.comfortzone_serial.telemetry.polling import temperature_request

DATA = Path(__file__).parent / "data"
PROFILE = DecoderProfile.EX35_0B15


def datagrams(name):
    return [bytes.fromhex(line) for line in (DATA / name).read_text().splitlines()]


def corrected(raw):
    return Frame(bytes(raw[:-1]) + bytes([crc8_maxim(raw[:-1])]))


def test_captured_request_cycle_and_all_reply_lengths_match():
    requests = [Frame(raw) for raw in datagrams("loggamera-request-cycle.hex")]
    buffer = FrameBuffer()
    replies = [
        packet.frame
        for raw in datagrams("pump-reply-datagrams.hex")
        for packet in buffer.feed(raw, now=0)
    ]
    assert len(requests) == len(replies) == 46
    assert not buffer.pending
    assert temperature_request() == requests[19].raw
    for request, reply in zip(requests, replies, strict=True):
        assert request.command == ord("R") and reply.command == ord("r")
        assert request.register == reply.register
        assert request.payload[0] == len(reply.payload)
        assert reply.raw[:4] == request.raw[6:10]
        assert reply.raw[6:10] == request.raw[:4]
        assert reply.raw[4] == crc8_maxim(reply.raw[:4])
        assert reply.raw[5] == crc8_maxim(bytes(b ^ 255 for b in reply.raw[:4]))
    result = decode_frame(replies[19], profile=PROFILE)
    values = {t.key: t.celsius for t in result.temperatures}
    assert values["outdoor_temperature"] == 10.3
    assert values["indoor_temperature"] == 22.2
    assert values["hot_water_temperature"] == 46.9


@pytest.mark.parametrize("file", ["standalone-reply.hex", "standalone-split-reply.hex"])
def test_real_standalone_replies(file):
    buffer = FrameBuffer()
    frames = [p.frame for raw in datagrams(file) for p in buffer.feed(raw, now=0)]
    assert len(frames) == 1 and len(frames[0].raw) == 139
    result = decode_frame(frames[0], profile=PROFILE)
    assert result.reason is DecodeReason.DECODED_EX35
    values = {t.key: t.celsius for t in result.temperatures}
    assert len(values) == 9
    assert values["outdoor_temperature"] == 12.4
    assert values["indoor_temperature"] == 22.0
    assert values["hot_water_temperature"] == 49.6


@pytest.mark.parametrize("split", range(1, 139))
def test_real_reply_at_every_split(split):
    raw = datagrams("standalone-reply.hex")[0]
    buffer = FrameBuffer()
    assert not buffer.feed(raw[:split], now=0)
    packets = buffer.feed(raw[split:], now=0.1)
    assert [p.frame.raw for p in packets] == [raw]


@pytest.mark.parametrize(
    ("offset", "reason"),
    [
        (11, DecodeReason.UNKNOWN_COMMAND),
        (17, DecodeReason.UNKNOWN_REGISTER),
        (4, DecodeReason.INVALID_ADDRESS),
        (5, DecodeReason.INVALID_ADDRESS),
    ],
)
def test_wrong_layout_or_address_crc_is_not_decoded(offset, reason):
    raw = bytearray(datagrams("standalone-reply.hex")[0])
    raw[offset] ^= 1
    assert decode_frame(corrected(raw), profile=PROFILE).reason is reason


def test_length_guard_signed_values_and_unused_channel_marker():
    raw = bytearray(datagrams("standalone-reply.hex")[0])
    raw[76:78] = (-125).to_bytes(2, "little", signed=True)
    raw[124:126] = (-990).to_bytes(2, "little", signed=True)
    values = {
        t.key: t.celsius
        for t in decode_frame(corrected(raw), profile=PROFILE).temperatures
    }
    assert values["outdoor_temperature"] == -12.5
    assert values["hot_water_temperature"] is None
    raw.pop(-2)
    raw[10] -= 1
    assert decode_frame(corrected(raw), profile=PROFILE).reason is (
        DecodeReason.UNKNOWN_PAYLOAD_LENGTH
    )
    assert not decode_frame(Frame(datagrams("standalone-reply.hex")[0])).temperatures
