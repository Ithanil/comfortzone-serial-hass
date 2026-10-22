"""Record receive-only UDP diagnostics, with finite duration and disk usage."""

import argparse
import asyncio
import json
import signal
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from custom_components.comfortzone_serial.telemetry.stream import (
    Datagram,
    finite_seconds,
)
from custom_components.comfortzone_serial.telemetry.udp import (
    NetworkSettings,
    UDPReceiver,
)

from .records import FORMAT, VERSION, CaptureWriter


async def capture(
    path: Path,
    settings: NetworkSettings,
    *,
    duration: float = 300,
    max_bytes: int = 64 * 1024 * 1024,
    metadata: dict | None = None,
    install_signals: bool = True,
) -> dict:
    """Save accepted datagrams without invoking any protocol decoder.

    File writes run sequentially in a worker thread. If its 64-record queue fills,
    close the socket, drain queued records, and explicitly report missing records.
    """
    if not 0 < finite_seconds(duration) <= 86400:
        raise ValueError("Duration must be in (0, 86400] seconds")
    queue: asyncio.Queue[Datagram | None] = asyncio.Queue(maxsize=64)
    stopped = asyncio.Event()
    reason = "duration"
    error_message = None
    writer = None
    worker = None
    timer = None
    signals = []
    session_id = str(uuid4())
    loop = asyncio.get_running_loop()

    def stop(why: str) -> None:
        nonlocal reason
        if not stopped.is_set():
            reason = why
        receiver.close()
        stopped.set()

    def datagram_received(datagram: Datagram) -> None:
        try:
            queue.put_nowait(datagram)
        except asyncio.QueueFull:
            stop("queue_overflow")

    def failed(error: Exception) -> None:
        nonlocal error_message
        error_message = str(error)
        stop("receiver_error")

    receiver = UDPReceiver(settings, datagram_received, failed)

    async def write_records() -> None:
        nonlocal error_message, reason
        writable = True
        while True:
            datagram = await queue.get()
            if datagram is None:
                return
            if not writable:
                continue
            try:
                writable = await asyncio.to_thread(writer.write, datagram)
                if not writable:
                    stop("byte_limit")
            except Exception as error:
                writable = False
                error_message = str(error)
                reason = "write_error"
                stop("write_error")

    try:
        await receiver.start()
        header = {
            "type": "session", "format": FORMAT, "version": VERSION,
            "session_id": session_id, "started_at": receiver.started_at.isoformat(),
            "network": asdict(settings), "metadata": metadata or {},
        }
        # Construct before the first await after bind; failures always close the
        # receiver. Only this short header write occurs on the diagnostic tool loop.
        writer = CaptureWriter(path, header, max_bytes=max_bytes)
        worker = asyncio.create_task(write_records())
        timer = loop.call_later(duration, stop, "duration")
        if install_signals:
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, stop, sig.name.lower())
                    signals.append(sig)
                except NotImplementedError:
                    pass
        await stopped.wait()
    except asyncio.CancelledError:
        reason = "cancelled"
        raise
    finally:
        receiver.close()
        await receiver.wait_closed()
        if timer is not None:
            timer.cancel()
        for sig in signals:
            loop.remove_signal_handler(sig)
        try:
            if worker is not None:
                await queue.put(None)
                await worker
            if writer is not None:
                counters = asdict(receiver.stats)
                counters["not_recorded"] = (
                    receiver.stats.accepted - writer.records_written
                )
                await asyncio.to_thread(
                    writer.finish, reason=reason, stream_time=receiver.elapsed,
                    counters=counters,
                )
        finally:
            if writer is not None:
                writer.close()
    return {
        "session_id": session_id, "reason": reason, "error": error_message,
        "path": str(path), "records_written": writer.records_written,
        "bytes_written": writer.bytes_written, "counters": counters,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New JSONL file; never overwritten")
    parser.add_argument("--source-ip", required=True, help="Expected Moxa IPv4 address")
    parser.add_argument("--source-port", type=int, help="Optional Moxa UDP source port")
    parser.add_argument("--bind-host", default="0.0.0.0")
    parser.add_argument("--bind-port", type=int, default=4001)
    parser.add_argument(
        "--duration", type=float, default=300, help="Seconds, at most 86400"
    )
    parser.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument(
        "--serial", default="unknown", help="Actual settings, or unknown"
    )
    parser.add_argument(
        "--connection", default="unknown", help="Actual cable/wiring notes"
    )
    parser.add_argument("--controller", default="unknown")
    parser.add_argument("--loggamera", choices=["present", "absent", "unknown"],
                        default="unknown")
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)
    try:
        settings = NetworkSettings(
            args.source_ip, args.bind_host, args.bind_port, args.source_port
        )
        result = asyncio.run(capture(
            args.output, settings, duration=args.duration, max_bytes=args.max_bytes,
            metadata={key: getattr(args, key) for key in (
                "serial", "connection", "controller", "loggamera", "notes"
            )},
        ))
        print(json.dumps(result, separators=(",", ":")))
        failure_reasons = {"queue_overflow", "receiver_error", "write_error"}
        return int(result["reason"] in failure_reasons)
    except (OSError, ValueError) as error:
        print(f"Capture failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
