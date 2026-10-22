# ComfortZone Serial

![ComfortZone Serial icon](custom_components/comfortzone_serial/brand/icon.png)

An MIT-licensed, receive-only Home Assistant integration in development for a
ComfortZone EX35 connected through a Moxa NPort P5150A. Home Assistant owns
measurement storage, history and visualization.

**Status, 2026-10-22: initial implementation prepared as ComfortZone Serial.**
Receive-only UDP, framing/CRC, provisional decoding, capture/replay, Home Assistant
configuration, sensors and lifecycle handling are implemented. HACS metadata,
original brand artwork and standalone CI workflows are included. Manual evaluation
targets **Home Assistant 2026.10.2 or newer**, with runtime tests on 2026.10.2.
See the [Home Assistant setup guide](docs/home-assistant.md),
[distribution guide](docs/distribution.md) and [review record](docs/implementation.md).

The standalone repository is
[Ithanil/comfortzone-serial-hass](https://github.com/Ithanil/comfortzone-serial-hass),
with integration domain `comfortzone_serial`. Follow the manual installation guide
for evaluation. HACS installation requires the repository to be public and the
distribution checks to pass. Official HACS/hassfest checks and a deployed
installation remain unverified; version `0.1.0` is unreleased.

**Follow-up, 2026-10-22:** TCP acquisition is planned after the current
documentation checkpoint and conversation compaction. It is not implemented;
runtime and capture/replay remain UDP-only. See the
[next-package handoff](docs/implementation.md#next-package-tcp-acquisition-planned-not-started).

No live serial data has been obtained. Owner-reported DC voltages at the powered
Loggamera socket now make **RS-232 the leading hypothesis; its pinout remains
unconfirmed**, superseding the earlier provisional two-wire RS-485 plan. See the
[hardware assumptions and readings](docs/diagnostics.md#before-a-real-capture).
Cable signals, 19200/8N1, controller layout and continued traffic with Loggamera
absent all still need validation on the installation. Tests use synthetic frames
exclusively. Neither passing them nor selecting a profile establishes hardware
compatibility.
The owner has ordered connector parts to carry only selected data/ground
signals, replacing a cancelled adapter with extra control connections. Assembly
and continuity checks are pending; the [diagnostic guide](docs/diagnostics.md#before-a-real-capture)
distinguishes three-wire software receive-only operation from omitting the
Moxa transmitter wire entirely.

## Current implementation

The runtime foundation lives in `custom_components/comfortzone_serial/telemetry/`.
It has no Home Assistant or third-party dependency:

- A stream buffer bounded to 255 bytes reassembles split/coalesced frames and
  checks their length and CRC-8/MAXIM-DOW checksum.
- Incomplete candidates expire after a configurable interval measured from their
  first byte. Expiry can recover complete frames behind a corrupt length even
  when no more traffic arrives; callers must run the expiry timer.
- Frames retain exact bytes. Decoding defaults to `observe_only`, which yields no
  measurements. Explicit profile `czbridge_rx50_temperatures_v1` decodes only the
  documented response command, register and exact payload length.
- UDP source filtering, per-sender buffers, bounded diagnostics and expiry during
  silence preserve original receive times and isolate sessions. Socket and timer
  resources close cleanly on shutdown and failure.
- Eight signed temperature values have reference names. There are no inferred
  hot-water, power, alarm, setpoint or cloud-to-bus mappings.

Read the [protocol contract](docs/protocol.md), including CRC ambiguity and timing
limitations, and the [reference and licensing audit](docs/references.md).

## Diagnostic capture and replay

The [diagnostic guide](docs/diagnostics.md) documents network settings, bounded
recording, metadata, replay format and failure handling. Run from this directory:

```sh
python3 -m tools.capture --help
python3 -m tools.replay --help
```

Capture requires the actual Moxa source IPv4 address and saves raw datagrams before
any decoding. Replay is offline, defaults to observation only, and cannot publish
live measurements. Neither tool configures or sends data to the Moxa.

## Run the offline tests

From this directory, with Python 3.13 or newer and pytest installed:

```sh
python3 -m pytest -q --ignore=tests/ha
```

For a separate development environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest -q --ignore=tests/ha
```

The tests cover every split point of the temperature frame, coalesced frames,
frame-length limits, malformed lengths, corrupted checksums, incomplete traffic,
expiry during silence/trickle traffic, clock resets, bounded noise processing,
unknown commands/registers/layouts and signed temperature decoding. The fixture
builder uses a separate bit-order CRC implementation and the published CRC check
vector. No fixtures were copied from upstream.

Acquisition tests cover source/session isolation, recording limits, cancellation,
write failures, malformed files and replay equivalence. One test sends synthetic
UDP only through localhost to check actual reception, no replies and socket reuse
after closure. Tests need permission to create loopback sockets and to wake the
asyncio event loop from writer threads. No test contacts a heat pump or LAN host.
The protocol/tools suite contains **275 tests**. The separate Home Assistant suite
currently contains **24 tests** against HA 2026.10.2, covering config/options flows,
sensor metadata and freshness, reloads, diagnostics and lifecycle failures. See the
[HA testing commands](docs/home-assistant.md#development-verification) for its pinned
dependencies and separate pytest configuration. All measurement fixtures are synthetic;
these tests do not validate a Moxa connection or EX35 layout.
Both suites passed from an independent standalone copy of this directory: **299
tests total**, rechecked for package 4 on Python 3.14.7. Ruff, compilation,
metadata/translation/workflow parsing, asset integrity, license notices and the
receive-only code audit also passed. GitHub workflows have not run here; local
checks do not constitute official HACS/hassfest validation or hardware validation.

## Repository boundary

This directory is the standalone repository root. Runtime, tests, documentation
and HACS metadata must remain self-contained here. The protocol package uses no
parent-repository imports, scripts or data. The separate
[investigation repository](https://github.com/Ithanil/re_loggamera) holds hardware
reports and vendor manuals and uses `integration/` as this repository's checkout
location.

Raw diagnostic recording/replay is opt-in development tooling, independent
of measurement history. No database, MQTT service or separate telemetry backend
is required by the integration.

## License

New code is licensed under [MIT](LICENSE). The upstream projects are references,
not bundled dependencies. Their licenses and the exact inspected commits are
recorded in [docs/references.md](docs/references.md).
