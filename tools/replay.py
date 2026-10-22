"""Replay saved datagrams locally. This tool never opens a network socket."""

import argparse
import json
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

from custom_components.comfortzone_serial.telemetry.decoder import DecoderProfile
from custom_components.comfortzone_serial.telemetry.stream import (
    Origin,
    TelemetryPipeline,
)

from .records import RecordError, read_records, to_datagram


def replay(
    records: Iterable[dict],
    *,
    profile: DecoderProfile = DecoderProfile.OBSERVE_ONLY,
    partial_timeout: float = 1.0,
    gap_timeout: float = 5.0,
) -> Iterator[dict]:
    pipeline = None
    last_time = 0.0
    seen_session = False

    def finish(reason: str, complete: bool, end: dict | None = None) -> Iterator[dict]:
        # Flush only in the recorded time domain. Preserve original byte times.
        for observation in pipeline.expire(now=last_time + partial_timeout):
            yield observation.as_dict()
        diagnostics = pipeline.diagnostics()
        diagnostics.pop("recent_frames")  # Frames were already streamed to stdout.
        diagnostics.pop("recent_datagrams")  # Exact datagrams remain in the input file.
        yield {
            "type": "summary", "capture_complete": complete, "reason": reason,
            "capture_end": end, "diagnostics": diagnostics,
        }

    for record in records:
        kind = record["type"]
        if kind == "session":
            seen_session = True
            if pipeline is not None:
                yield from finish("session_without_end", False)
            pipeline = TelemetryPipeline(
                session_id=record["session_id"], origin=Origin.REPLAY, profile=profile,
                partial_timeout=partial_timeout, gap_timeout=gap_timeout,
            )
            last_time = 0.0
            yield {"type": "session", "origin": "replay", "capture": record}
            continue
        if pipeline is None or record["session_id"] != pipeline.session_id:
            raise RecordError("Record has no matching active session header")
        if kind == "datagram":
            datagram = to_datagram(record)
            last_time = datagram.stream_time
            for observation in pipeline.feed(datagram):
                yield observation.as_dict()
        elif kind == "end":
            if record["stream_time"] < last_time:
                raise RecordError("Capture end time precedes the last datagram")
            last_time = record["stream_time"]
            matches = record["records_written"] == pipeline.stats.datagrams
            yield from finish(
                record["reason"] if matches else "record_count_mismatch",
                matches,
                record,
            )
            pipeline = None
        else:
            raise RecordError("Unknown record type")
    if pipeline is not None:
        yield from finish("missing_end_record", False)
    if not seen_session:
        raise RecordError("Capture contains no session header")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument(
        "--profile", choices=list(DecoderProfile), default="observe_only"
    )
    parser.add_argument("--partial-timeout", type=float, default=1.0)
    parser.add_argument("--gap-timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    try:
        with args.capture.open("rb") as stream:
            for result in replay(
                read_records(stream), profile=DecoderProfile(args.profile),
                partial_timeout=args.partial_timeout, gap_timeout=args.gap_timeout,
            ):
                print(json.dumps(result, separators=(",", ":"), allow_nan=False))
    except (OSError, ValueError) as error:
        print(f"Replay failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
