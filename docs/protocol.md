# Protocol contract

The envelope is verified against the owner's EX35 captures. The explicit EX35
`0b15` profile and captured read are described below; the legacy RX50 profile
retains its provisional status. References/licensing: [references.md](references.md).
Fixture provenance: [tests/data](../tests/data/README.md).

## Envelope

| Bytes, zero based | Reference interpretation |
| --- | --- |
| 0–3 | Destination address |
| 4 | CRC-8 of destination |
| 5 | CRC-8 of bitwise-complemented destination |
| 6–9 | Source address |
| 10 | Total frame length including checksum, 22–255 |
| 11 | Command; documented commands are `R`, `r`, `W`, `w` |
| 12–20 | Nine-byte register identifier |
| 21 through penultimate byte | Payload |
| Last byte | CRC-8/MAXIM-DOW over all preceding bytes |

CRC parameters are width 8, polynomial 0x31 (reflected 0x8C), initial value 0,
reflected input/output and final XOR 0. The ASCII check vector `123456789` produces
0xA1. The generic framer retains unknown address forms for diagnostics. The EX35
decoder checks destination `ADDR` and its two address checksums; active polling
also requires the configured pump source address. Observed pump address is
`656fde02`; this is a protocol address, not a confirmed device identity.

`Frame` copies and validates its input, so a decoder cannot be given a corrupt
or later-mutated frame through this API. The parser accepts unknown commands and
registers for diagnostics; framing success does not authorize decoding them.

## Bounded reassembly and recovery

`FrameBuffer` belongs to exactly one sender endpoint and capture/live session.
The acquisition layer must enforce that isolation. It accepts partial and
coalesced frames and retains at most 255 bytes plus one arrival timestamp per byte,
even for a large input datagram. The list of emitted frames scales with input
length; the acquisition/replay layers must bound their inputs and retained output.

A valid complete frame at the current boundary takes precedence. Bad length/CRC
candidates advance the boundary one byte. An incomplete candidate waits for up
to `partial_timeout` seconds from its first byte, **not** from the most recent
datagram. The default one second is an engineering timeout, not a measured maximum
EX35 inter-byte gap. A caller must periodically call `expire()` during silence. Expiry
resumes scanning and can emit valid complete frames hidden behind a corrupt length.

During recovery from discarded bytes, a CRC-valid unknown-command candidate may
overlap a complete frame with one of the documented commands. In that case the
latter takes precedence. Otherwise the unknown candidate is retained as a frame.
An intact frame at an uninterrupted boundary is not searched for nested frames.

**CRC-8 is weak boundary evidence.** Noise and overlapping candidates can pass it.
The preference above cannot guarantee reconstruction and can choose incorrectly;
results during recovery can also depend on datagram fragmentation. The parser does
not invent a delimiter, authenticate a sender, correct bytes or promise to repair
lost/reordered/duplicated UDP data. Preserve original datagrams before framing for
analysis, and validate the actual envelope against captures. Further header checks
need installation evidence before they are imposed on all traffic.

Returned `ReceivedFrame` objects carry the first and last byte's original arrival
times, in the caller's monotonic stream clock, and an optional last-byte record
index. Live/replay acquisition supplies the index to retain exact UTC provenance
even when several datagrams have equal monotonic timestamps. Recovering a frame
later must not
make it look newly measured. These are collector receive times, never pump-generated
measurement times. `reset()` clears partial state at session/source discontinuities;
a backwards clock also resets rather than joining observations across that boundary.
Counters account for consumed/discarded/pending bytes, rejected candidates, expiry
and resets. Rejected candidates are not necessarily real corrupt frames.

The acquisition pipeline now implements source/session isolation and periodic
expiry. See [diagnostics.md](diagnostics.md) for its additional bounds, raw capture
and offline replay. Timeouts remain configurable engineering defaults. Captures confirm that serial
frames cross UDP boundaries.

## Profiles

`observe_only` is the default. It returns the validated frame with an explicit
reason and no measurements, including for matching temperature responses.

`czbridge_rx50_temperatures_v1` is an opt-in, **provisional RX50 reference**, not
an EX35 controller/version profile. It requires all of:

- Command `r`.
- Register `010203040b0d010400`.
- Exactly 114 payload bytes (136 total frame bytes).

| Payload offset | Stable key | Reference meaning |
| --- | --- | --- |
| 52 | `outdoor_temperature` | Outdoor |
| 54 | `flow_water_temperature` | Flow water |
| 56 | `return_water_temperature` | Return water |
| 58 | `indoor_temperature` | Indoor |
| 60 | `hot_gas_temperature` | Hot gas |
| 62 | `exchanger_outlet_temperature` | Exchanger outlet |
| 64 | `evaporator_inlet_temperature` | Evaporator inlet |
| 66 | `exhaust_air_temperature` | Exhaust air |

Each value occupies two bytes, signed little endian, in tenths of a degree Celsius.
Names and scaling are reference hypotheses for this installation. A matching
envelope still does not prove they are correct on its controller. There is no
plausibility-based mapping, clamping, guessed sentinel handling or conversion of
unknown frames into measurements. Sensor fault encodings remain unverified, so
extreme decoded values must not be taken as confirmed temperatures.

Unknown command, register and payload length each have an explicit result reason.
Every result retains the exact source frame and selected profile. Unsupported
profile names raise an error. Software layouts 1.60, 1.80, 2.21 and proposed 2.50
are not claimed as implemented profiles and never silently select this one.

## Captured EX35 0b15 profile

`ex35_0b15_temperatures_v1` requires command `r`, register
`010203040b15010400`, exactly **117 payload bytes / 139 total**, destination
`ADDR` with address checksums `07 8a`, and valid frame CRC. It does not infer a
firmware version or auto-select a profile from plausible values.

| Payload offset | Channel | Key | Evidence for name |
| --- | --- | --- | --- |
| 55 | TE0 | `outdoor_temperature` | Display-confirmed |
| 57 | TE1 | `flow_water_temperature` | Reference mapping |
| 59 | TE2 | `return_water_temperature` | Reference mapping |
| 61 | TE3 | `indoor_temperature` | Display-confirmed |
| 63 | TE4 | `hot_gas_temperature` | Reference mapping |
| 65 | TE5 | `exchanger_outlet_temperature` | Reference mapping |
| 67 | TE6 | `evaporator_inlet_temperature` | Reference mapping |
| 69 | TE7 | `exhaust_air_temperature` | Reference mapping |
| 103 | TE24 | `hot_water_temperature` | Display-confirmed |

All values are signed int16 little endian divided by 10. Raw **−990** (`22 fc`),
observed in unused channels, is treated conservatively as unavailable in this
profile. No comprehensive fault-code table or other field decoding is claimed.
All nine HA entities are enabled by default and share the same presentation and
availability rules. The evidence column above is documentation only and does not
appear in runtime output. Other channels and registers remain unknown; no
plausibility-based substitutions or clamping occur.

## Read polling

The captured operation, reproduced exactly for the observed pump address, is:

```text
65 6f de 02 d3 5e 41 44 44 52 17 52 01 02 03 04 0b 15 01 04 00 75 73
```

`R` reads 117 bytes (`75`) from the temperature register. A configurable pump
address changes only the destination and checksums. The client address stays
`ADDR`. No arbitrary payload or write-command API exists. Home Assistant uses
only this read. The shared protocol package additionally supports the nine
captured reads in the [monitor query mapping](query-mapping.md); only explicit
monitor query selection enables those operations. The full 46-read cycle remains
research evidence and is not replayed as a polling schedule.

Polling is explicitly enabled, requires the EX35 profile and sends through the
same UDP socket that receives replies. HA retains its default 30-second request
interval (minimum 15) and 10-second response timeout. The default
`PollingSettings()` still selects temperature only, with fixed request spacing.
The monitor uses `cycle=True`: its interval is between cycle starts (default 30,
any positive value up to 3600 seconds), with a configurable `request_delay`
(default 0.25, range 0–3600 seconds) after each compatible reply or timeout.
Shared reads are deduplicated in selection order. Slow cycles finish before the
next starts; the actual next start becomes its new timing origin, without
catch-up bursts. Each listener allows one outstanding request of its own;
other clients can poll independently. The separate `readings`
inspector accepts exact captured reply windows and decodes covered fields without
changing HA decoder profiles or their results. Unknown payload regions retain hex
and offsets. A reply can match a poll even when its payload remains undecoded.
The first matching response satisfies it. Unrelated addresses/registers, late
responses outside a request, and subsequent duplicates cannot refresh entities.
Partial buffers reset before every read and after timeout. UDP has no transaction
ID here: a delayed reply during a later request cannot be perfectly distinguished.
Likewise, clients using the captured `ADDR` address cannot distinguish which
poller triggered an otherwise matching reply. Matching is compatible-response
tracking, not exclusive request attribution. The monitor's independent receive
stream displays traffic from all pollers forwarded by its selected Moxa endpoint.
Capture timestamps are absent, so the interval is not inferred from Loggamera.

The response fixtures include CRC `05` as one 139-byte datagram and CRC `ab`
as 104+35 bytes. CRC and exact length apply to the reconstructed frame, never to
individual UDP packet sizes. Loss/reordering can cause a failed read; freshness
expiry and the next periodic read recover without fabricating measurements.
