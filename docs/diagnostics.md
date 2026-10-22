# Receive-only acquisition and diagnostic capture/replay

Package 2 provides a reusable asyncio receiver and standalone development tools.
All runtime and tooling dependencies are in Python's standard library. Run the
commands below from this directory's parent, the integration repository root.
Python 3.13 or newer is the development baseline; testing currently uses 3.14.7.
Home Assistant setup and entities are documented in the
[Home Assistant guide](home-assistant.md). The tools remain independently usable.

## Before a real capture

The tools only receive UDP; they never send requests, acknowledgements, discovery
probes or serial commands. They do not configure the Moxa. The Moxa can still
transmit network data onto its serial connection, so software receive-only
operation does not establish a hardware receive-only guarantee.

Confirm the installed cable's electrical interface and pin assignment before
connecting it. **RS-232 is now the leading hypothesis at the Loggamera socket;
its pinout remains unconfirmed.** The owner reported these DC multimeter readings
on 2026-10-19 at the powered LMCZEXG-07's female nine-pin D-sub socket, with the
black probe on pin 5: pin 2 measured −5.575 V and pin 3 measured steady 0 V.
On 2026-10-22 the owner repeated these values using a numbered male/female
breakout adapter, and measured the pump cable end at approximately 0 V on pin 2
and −6.68 V on pin 3, again relative to pin 5. The devices were explicitly
confirmed disconnected from each other during measurement. Exact measurement
times were not supplied; adapter continuity and signal ground remain unverified.

These readings fit an idle RS-232 output on pin 2 and a possible input on pin 3,
the conventional DCE arrangement. The pump readings support the complementary
DTE arrangement: output on pin 3 and input on pin 2. They supersede the earlier
provisional two-wire RS-485 plan for this connection. They do not establish a waveform,
the pump cable's mapping or the application protocol. The
[Moxa P5150A quick guide](https://moxa.com/getmedia/4ccea339-54d9-4f3e-8fe4-d768ab08f1b1/moxa-nport-p5150a-series-qig-v2.3.pdf),
page 5, defines its RS-232 receive input as pin 2, so replacement may require a
crossover and gender adaptation after the actual cable signals are identified. See
[TI's electrical specification](https://www.ti.com/lit/an/slla037a/slla037a.pdf)
and [Analog Devices' DCE pinout explanation](https://www.analog.com/media/en/technical-documentation/application-notes/67805834ee_27.pdf)
for the general interpretation, not a Loggamera-specific pinout.

**19200/8N1 remains an unverified hypothesis** from the related panel-bus
reference. The known community layout is not yet verified on this EX35/X2
connection, and traffic without Loggamera has not been demonstrated. Do not
infer the pump cable's wiring from the Moxa DB9 pinout or the community RJ11
panel-bus pinout. UDP capture works independently of the serial electrical
standard; no decoder profile is validated by the voltage readings.

Later on 2026-10-22, the owner reported Moxa pins 4, 3, 2 and 1 at approximately
+6.5 V, −6.1 V, +0.25 V and 0 V respectively, relative to pin 5. These fit the
documented DTR output, TxD output, RxD input and DCD input roles. Pump contacts
6–9 measured 0 V relative to pin 5, which does not establish their functions.
The owner cancelled a null-modem adapter with extra control connections and
ordered a female DB9-to-three-wire lead (pins 2, 3, 5) plus a solder-free female
connector. Delivery, assembly and continuity verification remain pending.

The proposed three-wire mapping is **pump 3 → Moxa 2**, **Moxa 3 → pump 2** and
**5 ↔ 5**, with all other signal contacts unconnected. It matches the inferred
data/ground arrangement at the Loggamera connector, not a proven full pinout.
That arrangement still relies on software receive-only behavior. The selected
parts also permit omitting the Moxa 3 → pump 2 wire, physically removing the
reverse data path; the actually assembled variant must be recorded. Check
continuity with the assembly disconnected from both devices, using numbered
contacts rather than assumed wire colors or connector viewing orientation.
No pump connection or serial byte-transfer result has been reported.

TCP is planned for a later software package after the documentation checkpoint.
These commands and the JSONL version 1 format currently support UDP only;
changing the Moxa to TCP mode will not make the existing receiver consume it.

Once the connection and serial settings are established, configure Moxa UDP unicast
to the **collector computer's actual IP address and destination port** (default
4001). Use binary packing with delimiters disabled. The proposed 20 ms packing
timeout remains unverified. The receive tool does not set baud rate or other
serial options. Record actual settings as metadata rather than labelling the
proposed settings as verified.

Permit the intended incoming UDP traffic to the listening host, including any
container port mapping. A bind address belongs to the collector, not the Moxa.
Numeric IPv4 addresses are supported; there is no DNS, IPv6 or multicast setup.
The expected source IP is required; its source port can optionally be pinned.
Filtering is not authentication and does not detect network packet loss.

## Save a raw diagnostic recording

The address `192.0.2.10` below is a documentation placeholder. Replace it with the
actual Moxa IPv4 address. A wildcard bind listens on all local IPv4 interfaces;
use a specific local IPv4 address when appropriate.

```sh
mkdir -p captures
python3 -m tools.capture captures/first-session.jsonl \
  --source-ip 192.0.2.10 \
  --bind-host 0.0.0.0 --bind-port 4001 \
  --duration 300 --max-bytes 67108864 \
  --serial unknown --connection unknown \
  --controller unknown --loggamera unknown
```

Supply `--serial`, `--connection`, `--controller`, `--loggamera` and `--notes` with
observed facts when available. `--source-port 4001` filters the **sender's** port;
it is independent of the listener port and should only be set when known.
`--help` lists all options.

The recorder saves each accepted datagram's exact bytes, boundary, source endpoint,
receive UTC timestamp, monotonic seconds since receiver start and session-local
record index. It never invokes the frame decoder, so incomplete, corrupt, empty or
unknown datagrams are still recorded. Rejected sources are counted, not recorded.
The index describes local reception order, not a serial or Moxa sequence number.

Default limits are 300 seconds and 64 MiB including metadata/footer. Duration must
be positive and at most 86400 seconds. The output file is created exclusively with
owner-only permissions; an existing file is never overwritten. Parent directories
must already exist. The file limit reserves 4096 bytes for its summary and stops
before writing a datagram that would exceed the limit. A new capture uses a new
filename/session; this version stops at limits rather than rotating files.

Writes run sequentially in a worker thread. A 64-datagram queue bounds memory
(at most about 4 MiB of payload plus the active record). If it fills, reception
stops and already queued records are drained. The footer and printed JSON summary
report `not_recorded`, the accepted count minus the written count. This can also
be nonzero when the byte limit is reached. Kernel/network drops and traffic after
the socket closes cannot be counted by the receiver.

Ctrl-C/SIGINT, SIGTERM, expiry, limits and task cancellation close the socket and
drain queued writes. Ordinary completion writes an `end` record and prints a JSON
summary. Queue overflow, socket error and writer failure return a nonzero CLI
status; configured limits are normal stop reasons. Disk errors or abrupt process
termination can leave a file without a footer or with a truncated last line.
Each complete record is flushed to the OS, but the tool does not promise power-loss
durability. Preserve the original file when investigating a damaged capture.

Only one listener can own a local address/port. An existing capture process or
future HA receiver will cause a bind error; the tool intentionally does not use
port sharing. Stop the other listener or use a separately configured destination.

## Replay entirely offline

First inventory frames without interpreting measurements:

```sh
python3 -m tools.replay captures/first-session.jsonl
```

Explicitly select the provisional reference to examine candidate temperatures:

```sh
python3 -m tools.replay captures/first-session.jsonl \
  --profile czbridge_rx50_temperatures_v1 \
  > captures/first-session-decoded.jsonl
```

Replay has no network output or Home Assistant publishing path. It marks every
observation `origin: replay`, keeps original receive timestamps and uses recorded
monotonic time to expire partial frames. It runs without waiting for real time.
The shared live listener rejects a replay pipeline. Package 3 must also reject
replay observations at the entity-update boundary.

Output is JSONL: session metadata, each validated frame with raw hex, command,
register, source, profile, decoder reason and any provisional temperatures, then
a per-session summary. Unsupported layouts remain unknown. The default profile
is `observe_only`; matching bytes alone do not enable measurements.

At the end of each session or file, replay advances its virtual clock by the
partial timeout to recover complete frames hidden behind incomplete candidates.
Recovered frames retain their original last-byte time and record index. Summary
events retain bounded incomplete-tail snapshots before expiry/discontinuities.
`capture_complete` means an end record exists and its written count matches the
records read; it does **not** prove loss-free UDP reception. Inspect its stop
reason, counters and stream-discontinuity events as well.

Missing/duplicate/reordered local record indices or backwards stream times reset
partial streams, preventing bytes from being joined across known discontinuities.
Each session header starts a fresh pipeline, even if its ID repeats. Different
sender ports/IPs never share a buffer. Duplicate or reordered **network datagrams**
with ordinary local indices cannot generally be detected and are not deduplicated.
The frame CRC and recovery rules also cannot guarantee correct reconstruction;
see [protocol.md](protocol.md).

Malformed JSON, duplicate keys, unknown format versions, invalid types, oversized
lines and a truncated final line produce a line-numbered error and nonzero exit.
Do not consume partial replay stdout as a successful result after such an error.
Missing footers, mismatched record counts and session boundaries without an end
record are reported as incomplete summaries. Replay never silently skips damaged
lines or replaces missing bytes. On a working copy, removing a truncated final
line permits analysis of preceding complete records with an incomplete summary.

`--partial-timeout` defaults to 1 second and accepts 0.01–60 seconds.
`--gap-timeout` defaults to 5 seconds and must be at least the partial timeout and
at most 3600 seconds. These are engineering defaults, not measured EX35 timing.

## Runtime API and memory bounds

`telemetry.udp.UDPReceiver` binds an IPv4 UDP socket, applies source filtering and
delivers immutable `Datagram` objects. Its owner supplies fast synchronous callbacks.
Callback/transport errors close the receiver and notify the owner once. Setup
failure and cancellation release any acquired socket; `close()` and
`await wait_closed()` complete shutdown. Reopening requires a new receiver/session.

`TelemetryListener` owns a live `TelemetryPipeline`, receiver and expiry timer.
It checks partials every `min(partial_timeout / 2, 0.25)` seconds during silence,
cancels the timer on shutdown/error and clears partial streams. It does not
reconnect itself; its future HA owner will manage retry/reload behavior. There is
no periodic network transmission.

| Resource | Default / enforced bound |
| --- | --- |
| UDP payload / replay hex payload | 65507 bytes |
| Sources tracked in one pipeline | 8, configurable 1–32; least recently received source is evicted |
| Frame buffer per source | 255 bytes plus per-byte time and record-index references |
| Receipt metadata per source | 256 nonempty datagrams; no raw payload copies |
| Recent validated frames and reset/expiry events | Separate rings of 64 each, configurable 1–256 |
| Recent accepted raw datagrams | 4 |
| Capture writer queue | 64 datagrams plus the currently written record |
| Capture header | 16384 encoded bytes |
| Replay input line | 140000 bytes; rejected without reading an unbounded line |

Runtime diagnostics include exact recent frames/datagrams and source metadata.
They are bounded in-memory evidence, not a history database. Unknown observations
can age out as new frames arrive; use raw capture when complete diagnostic evidence
is needed. Retired-source counters are aggregated without retaining unbounded
per-source state. Raw files can contain installation identifiers: keep them under
ignored `captures/` or `private/` and sanitize copies before sharing.

## JSONL version 1

Each UTF-8 JSON object ends with a newline. Every record has a `type` and
`session_id` (1–128 characters). One file may contain concatenated sessions.

- `session`: `format: "comfortzone-udp"`, integer `version: 1`, timezone-aware
  `started_at`, `network` matching `NetworkSettings`, and a `metadata` object.
- `datagram`: nonnegative integer `index`, `source: [IPv4, port]`, timezone-aware
  `received_at`, finite nonnegative `stream_time` in seconds, and `data_hex`.
  The first accepted record is index 0; empty payloads use an empty hex string.
- `end`: `reason`, `stream_time`, `records_written` and the recorder's `counters`.
  The end time must not precede the last datagram. Counters distinguish accepted,
  rejected and not-recorded traffic; they cannot measure upstream packet loss.

## Verification scope

Tests use invented frames, in-process fake transports, temporary recordings and
synthetic localhost UDP. They exercise filtering, buffer/source limits, timestamp
provenance, malformed recordings, replay isolation, capture limits/errors and
lifecycle cleanup. The loopback test verifies actual UDP binding/reception,
absence of replies, bind-conflict errors and immediate rebinding after closure.
No Moxa, serial connection, pump display comparison or real measurement was tested.
