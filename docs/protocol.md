# Provisional protocol contract

These are reference facts, not observations from this EX35. Source revisions and
licensing decisions are in [references.md](references.md). The runtime implements
only the envelope and one explicitly selected temperature layout.

## Envelope

| Bytes, zero based | Reference interpretation |
| --- | --- |
| 0–9 | Address/header fields, retained as opaque bytes |
| 10 | Total frame length including checksum, 22–255 |
| 11 | Command; documented commands are `R`, `r`, `W`, `w` |
| 12–20 | Nine-byte register identifier |
| 21 through penultimate byte | Payload |
| Last byte | CRC-8/MAXIM-DOW over all preceding bytes |

CRC parameters are width 8, polynomial 0x31 (reflected 0x8C), initial value 0,
reflected input/output and final XOR 0. The ASCII check vector `123456789` produces
0xA1. No address CRC or fixed synchronization marker is enforced. The sources
contain differing descriptions of some header fields; their exact raw bytes are
safer diagnostic evidence than assigning unverified meaning to them.

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
datagram. The default one second is an engineering starting point, not a verified
EX35 timing. A caller must periodically call `expire()` during silence. Expiry
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
and offline replay. All timeouts remain engineering defaults awaiting captures.

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
