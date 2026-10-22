"""Version 1 JSONL diagnostic records and a finite, non-overwriting file writer."""

import json
import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from custom_components.comfortzone_serial.telemetry.stream import (
    MAX_DATAGRAM_BYTES,
    Datagram,
    finite_seconds,
)
from custom_components.comfortzone_serial.telemetry.udp import NetworkSettings

FORMAT = "comfortzone-udp"
VERSION = 1
MAX_LINE_BYTES = 140_000
MAX_HEADER_BYTES = 16_384
FOOTER_RESERVE = 4096


class RecordError(ValueError):
    """An invalid, unsupported or truncated capture record."""


def encode(record: dict) -> bytes:
    return (json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _session_id(record: dict) -> str:
    value = record.get("session_id")
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise RecordError("session_id must contain 1 to 128 characters")
    return value


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise RecordError("Timestamp must be an ISO 8601 string")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise RecordError("Timestamp must include a timezone")
    return result


def validate(record: dict) -> None:
    if not isinstance(record, dict):
        raise RecordError("Each record must be an object")
    _session_id(record)
    match record.get("type"):
        case "session":
            if (
                record.get("format") != FORMAT
                or type(record.get("version")) is not int
                or record["version"] != VERSION
            ):
                raise RecordError("Unsupported capture format/version")
            _timestamp(record["started_at"])
            NetworkSettings(**record["network"])
            if not isinstance(record["metadata"], dict):
                raise RecordError("Session metadata must be an object")
            if len(encode(record)) > MAX_HEADER_BYTES:
                raise RecordError("Session header exceeds 16384 bytes")
        case "datagram":
            to_datagram(record)
        case "end":
            finite_seconds(record["stream_time"])
            if (
                type(record["records_written"]) is not int
                or not 0 <= record["records_written"] < 2**63
                or not isinstance(record["reason"], str)
            ):
                raise RecordError("Invalid capture end record")
        case _:
            raise RecordError("Unknown record type")


def to_datagram(record: dict) -> Datagram:
    raw_hex = record["data_hex"]
    if (
        not isinstance(raw_hex, str)
        or len(raw_hex) > 2 * MAX_DATAGRAM_BYTES
        or len(raw_hex) % 2
        or any(c not in "0123456789abcdefABCDEF" for c in raw_hex)
    ):
        raise RecordError("data_hex must be hexadecimal, at most 65507 bytes")
    source = record["source"]
    if not isinstance(source, list) or len(source) != 2:
        raise RecordError("source must be [IPv4 address, port]")
    return Datagram(
        bytes.fromhex(raw_hex), tuple(source), _timestamp(record["received_at"]),
        record["stream_time"], record["index"],
    )


def datagram_record(session_id: str, datagram: Datagram) -> dict:
    return {
        "type": "datagram", "session_id": session_id,
        "index": datagram.index, "source": list(datagram.source),
        "received_at": datagram.received_at.isoformat(),
        "stream_time": datagram.stream_time, "data_hex": datagram.data.hex(),
    }


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecordError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise RecordError(f"Invalid JSON constant: {value}")


def read_records(stream: BinaryIO) -> Iterator[dict]:
    """Read bounded lines strictly; never skip corrupt lines and splice streams."""
    line_number = 0
    while line := stream.readline(MAX_LINE_BYTES + 1):
        line_number += 1
        try:
            if len(line) > MAX_LINE_BYTES:
                raise RecordError("Record exceeds 140000 bytes")
            if not line.endswith(b"\n"):
                raise RecordError("Truncated record (missing newline)")
            record = json.loads(
                line, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
            )
            validate(record)
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            raise RecordError(f"Line {line_number}: {error}") from error
        yield record


class CaptureWriter:
    """Stop at a byte limit, reserve a footer, and never replace a recording."""

    def __init__(self, path: Path, session: dict, *, max_bytes: int) -> None:
        validate(session)
        if session["type"] != "session":
            raise RecordError("A capture must start with a session record")
        header = encode(session)
        if type(max_bytes) is not int or max_bytes < len(header) + FOOTER_RESERVE:
            raise ValueError(
                "Byte limit must fit the session header and 4096-byte footer"
            )
        self.session_id = session["session_id"]
        self.max_bytes = max_bytes
        self.records_written = 0
        self.bytes_written = 0
        self.finished = False
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self._file = os.fdopen(descriptor, "wb")
        try:
            self._write(header)
        except BaseException:
            self._file.close()
            raise

    def write(self, datagram: Datagram) -> bool:
        if self.finished:
            raise RuntimeError("Capture already finished")
        data = encode(datagram_record(self.session_id, datagram))
        if self.bytes_written + len(data) > self.max_bytes - FOOTER_RESERVE:
            return False
        self._write(data)
        self.records_written += 1
        return True

    def finish(self, *, reason: str, stream_time: float, counters: dict) -> None:
        if self.finished:
            return
        record = {
            "type": "end", "session_id": self.session_id,
            "reason": reason, "stream_time": stream_time,
            "records_written": self.records_written, "counters": counters,
        }
        validate(record)
        data = encode(record)
        if len(data) > FOOTER_RESERVE:
            raise ValueError("Capture footer exceeds reserved space")
        self._write(data)
        self.finished = True

    def close(self) -> None:
        self._file.close()

    def _write(self, data: bytes) -> None:
        self._file.write(data)
        self._file.flush()
        self.bytes_written += len(data)
