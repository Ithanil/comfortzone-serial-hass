# Implementation packages and review checkpoints

Updated 2026-10-19. At the owner's request, each package is reviewed and reported
before proceeding to the next, leaving an opportunity for feedback.

## 1. Protocol foundation and licensing — reviewed; owner authorized package 2

- Read project guidance, both active hardware reports and all three upstream
  references; record revisions, licensing decisions and official HA/HACS docs.
- Establish independent MIT code under `custom_components/comfortzone_serial/`.
- Implement bounded framing, CRC validation, incomplete-candidate expiry and an
  explicitly chosen provisional temperature decoder.
- Exercise failure modes with synthetic fixtures and review boundary ambiguity.

The initial test run caught a CRC-valid misalignment hiding a real frame. Recovery
now prefers a complete overlapping frame with a documented command over an
unknown-command candidate after corruption. A valid outer frame retains priority
in an uninterrupted stream, even if its payload contains another valid frame.
This is a framing heuristic, not proof of a synchronization boundary. Raw
datagrams must remain available for diagnosis; CRC-8 cannot eliminate ambiguity.

The reviewed foundation has 194 passing parametrized tests on Python 3.14.7.
This count includes 135 split-point cases and is not a hardware-validation result.
The same suite passed from a temporary standalone copy of this directory. Python
compilation and `git diff --check` also passed. Ruff was unavailable in the local
environment; no Ruff result or Home Assistant compatibility result is claimed.

## 2. Receive-only UDP acquisition and development diagnostics — reviewed; owner authorized package 3

- Async UDP bind with configurable local IPv4 address/port and expected Moxa
  source IPv4 address, plus optional source-port filtering. No network sends.
- Separate framing per source endpoint, bounded source count and diagnostic ring,
  session/gap resets, periodic expiry during silence, counters and clean closure.
- Preserve unknown CRC-valid frames, their metadata and incomplete tails in
  bounded diagnostics. Frame receipt times remain those of their original bytes.
- Versioned raw JSONL capture: session settings, exact datagram bytes, source,
  receive wall time, monotonic offset and record index; finite duration/storage
  limits and graceful shutdown. Recording remains a development command.
- Offline replay through the same frame/decoder pipeline, preserving source and
  session boundaries and gaps. Report decoded and unknown frames without any
  route into live HA state or sending datagrams to the Moxa.
- Test filtering, source/session isolation, malformed recordings, bounded memory,
  shutdown and replay equivalence. No test needs access to the real pump.

The implementation is in `telemetry/stream.py`, `telemetry/udp.py` and `tools/`.
The [diagnostic guide](diagnostics.md) documents commands, format, limits and
remaining hardware validation. Recording stops at a byte/duration limit rather
than rotating; original files cannot be overwritten. Profile decoding is not
required for capture. Replay has no socket or entity publishing path.

Review added exact record provenance to the framer so repeated monotonic clock
values cannot attach the wrong receive timestamp to a recovered frame. Empty
datagrams cannot evict metadata for buffered bytes. Review also added minimum
timer intervals, malformed-number handling, explicit incomplete-session summaries
and cleanup checks for cancellation and writer failures.

Final verification: **275 tests passed** on Python 3.14.7 from an independent copy
of `integration/` under `/tmp`, including the real localhost UDP test and threaded
recorder tests. These required execution outside the restricted sandbox: it denied
UDP socket creation and prevented writer-thread event-loop wakeups. The same tests
passed outside that restriction; no pump/LAN endpoint was contacted. Python parse,
compilation, whitespace and network send/connect-path audits passed. Ruff remains
unavailable, so no Ruff result is claimed. All fixtures and datagrams are synthetic;
there is no hardware, Home Assistant or HACS installation validation yet.

## 3. Home Assistant setup, entities and lifecycle — reviewed; owner authorized package 4

- Domain `comfortzone_serial`, UI config flow, settings changes/reload, bind error
  handling and cleanup on unload, setup failure and Home Assistant shutdown.
- Default to observation only. Offer the clearly labelled provisional RX50
  reference profile explicitly; never infer controller layout from model name.
- Create eight temperature sensors only for the selected temperature profile,
  with Celsius, temperature device class, measurement state class and stable IDs
  independent of changing network addresses. No cloud IDs are reused.
- A push coordinator owns the receiver. Track freshness per decoded measurement
  using monotonic receipt time; unrelated/unknown traffic cannot keep values fresh.
  A timer marks old data unavailable even when the network is completely silent.
- Initial/absent values remain unavailable. Never restore old values as fresh.
  Provisional provenance and last receive time are visible in diagnostics.
- Validate config, lifecycle, sensor metadata, freshness and failure behavior
  against Home Assistant itself with focused integration tests.

Implemented UI setup, network reconfiguration, decoder/timing options with reload,
a push coordinator, eight provisional temperature entities and bounded diagnostic
downloads. New entries default to observation only. The persistent config-entry
ID identifies entities/devices; network addresses are not hardware identity. There
is no handshake, poll, automatic controller detection or restored fresh value.

The runtime manifest and English form/entity strings moved into this package so
the actual HA integration can load and be tested. HACS metadata, brand assets,
extraction-ready CI and the final distribution audit remain package 4. Manual
evaluation and timing/availability behavior are in [home-assistant.md](home-assistant.md).

Review checked silent expiry against original monotonic byte receipt times,
per-key freshness, origin/session/profile guards, source filtering, no send paths,
and resource cleanup on normal/failed/cancelled setup, unload and HA stop. It found
and fixed a cleanup gap after partial platform forwarding: already-added entities
are now unloaded if forwarding raises. A malformed stored entry also no longer
blocks configuration of another valid receiver. Reconfiguration and options use
HA's reload helpers without redundant update listeners.

The **24 HA tests passed** against **Home Assistant 2026.10.2**, pytest harness
0.13.373 and Python 3.14.7, including actual config/options flows, sensor state and
metadata, stable registry IDs, unavailable states, diagnostics redaction, timer and
socket cleanup, setup retry and automatic recovery from simulated receiver errors.
Telemetry is synthetic and the HA UDP transport is fake, with sends rejected.
The HA suite covers 100% of setup/flow/sensor/diagnostics statements and 94% of the
coordinator; coverage is software evidence, not proof of hardware compatibility.

Ruff is now available and its checks pass across all integration runtime, tools
and tests. Compilation and whitespace checks pass. HA tests required execution
outside the restricted sandbox because its thread/event-loop restrictions stalled
the HA harness. There was no pump/LAN access and no frontend/deployed-HA validation.

Final standalone verification copied `integration/` to an independent directory
under `/tmp`: **275 protocol/capture/replay tests** passed without HA installed in
their Python environment, and **24 HA tests** passed using the pinned HA environment
against that same copy. Total: **299 passing tests across the two suites**. The
runtime/tools send-path AST audit, JSON parsing and whitespace checks also passed.

## 4. Packaging, setup documentation and final review — implemented and reviewed locally

- Review the manifest and English translations added in package 3; add HACS metadata,
  a brand asset and extraction-ready CI under this directory. Confirm current
  official HA/HACS requirements again.
- Document manual installation now and HACS installation after extraction; HACS
  expects `custom_components/` at repository root and cannot install this nested
  directory directly from the investigation repository as currently arranged.
- Document receiver settings, capture/replay/testing commands, diagnostic limits,
  the receive-only software boundary and troubleshooting.
- Audit all send paths, resource bounds, profile guards, provenance, timestamps,
  entity availability, cleanup and standalone operation. Run relevant checks and
  report their actual scope, including any checks that could not run.
- Update the parent README to reflect implemented work and the remaining hardware
  checks. Do not create a separate repository/submodule or publish a release yet.

Added `hacs.json` with minimum HA 2026.10.2, an issue-tracker link, original MIT
brand artwork (editable SVG and bundled PNG), a runtime copy of the license, an
unreleased changelog, pinned Ruff requirements and standalone test/validation
workflows. The distribution guide describes extraction, public repository settings,
future HACS installation, release validation and the exact current limitations.
The directory remains ordinary and unpublished. Its nested workflows do not run
in the parent repository; they are prepared for extraction.

Review covered all runtime and capture/replay modules: no send/connect path,
source filtering, bounded buffers/rings/recording, exact decoder guards, original
receipt timestamps, live/replay separation, per-measurement silent expiry and
shutdown/reload cleanup. It also checked the MIT reference boundary and that
runtime imports require no files outside the component directory. Review found
a missing reconfiguration-success translation and added it, along with a clearer
reconfiguration description that preserves the selected profile.

Final tests from an independent `/tmp` copy: **275 protocol/tools tests** and
**24 Home Assistant tests** passed, **299 total**, on Python 3.14.7 with HA 2026.10.2
in its separate environment. All telemetry remained synthetic. Ruff, compilation,
JSON/YAML parsing, translation consistency, PNG dimensions/checksums, matching MIT
notices, local documentation links and the receive-only import/call audit passed.
The test suites again needed sandbox exceptions for localhost sockets and event-loop
thread wakeups; no test contacted a Moxa, pump or LAN host.

**Validation not performed:** the official container-based hassfest check (Docker
access was declined), remote HACS validation, GitHub Actions execution, installation
or updating through HACS, and a deployed HA frontend. Included workflows retain the
official validators without ignored checks for later execution. Python 3.13 is in
the future protocol-test matrix but this local run used 3.14.7. Passing local
metadata checks is not reported as official validator approval. The first release
must complete the distribution checks in [distribution.md](distribution.md).

## Standalone repository preparation — 2026-10-22

Prepared the current implementation as the initial snapshot for
`Ithanil/comfortzone-serial-hass`. Renamed the display name to **ComfortZone Serial**,
the integration domain and component directory to `comfortzone_serial`, and updated
imports, tests, translations, artwork metadata and documentation consistently.
Manifest documentation and issue links now point to the standalone repository.
The package records above describe work before extraction.

Ruff, compilation, manifest/domain consistency, translations, JSON/YAML parsing,
local documentation links, the bundled icon and matching license notices passed.
The earlier **299-test** result above belongs to the previous implementation review.
Test reruns for this rename were stopped at the owner's request; no new suite result
is claimed. Hardware and official distribution validation remain outstanding.

## Validation that still needs real captures

1. Confirm installed cable signals, electrical interface, connector mapping and
   reference ground before any pump connection. D-sub shell compatibility is not
   proof of electrical compatibility.
2. Record actual Moxa mode, serial format, packing timeout, network addresses,
   controller revision/software, wiring and whether Loggamera is present.
3. Capture datagrams independently of measurement decoding. Inventory headers,
   lengths, CRCs, commands/registers, addressing and traffic cadence. Check whether
   the reference framing assumptions actually hold.
4. Compare each proposed measurement against a contemporaneous pump display
   reading over changing conditions. Identify fault/sentinel values. Keep other
   layouts unknown until supported by evidence.
5. Demonstrate continuing fresh telemetry with Loggamera absent and normal pump
   operation. If it stops, investigate the polling dependency; active requests
   remain outside the authorized implementation.
