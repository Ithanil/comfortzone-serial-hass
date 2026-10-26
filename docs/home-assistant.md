# Home Assistant setup and behavior

Supports **HA 2026.10.2 or newer**, tested with the pinned 2026.10.2 runtime on
Python 3.14. The protocol and hardware path have been verified on the owner's
EX35. The owner reports HA temperature polling already running. Additional reads
are fixture-validated; their standalone live trials and extended operation remain
owner validation steps.

## Installation

Copy the entire `custom_components/comfortzone_serial/` directory into the HA
configuration's `custom_components/`, including `telemetry/`, translations, brand
and license. Restart HA and add **ComfortZone Serial** under Devices & services.
For HACS use `Ithanil/comfortzone-serial-hass` as a custom **Integration** repository
once public and distribution checks pass; see [distribution](distribution.md).

Configure the [documented RS-422 wiring](../README.md#proven-wiring) and unplug
Loggamera. Moxa must target the actual reachable HA host IPv4 address and UDP port,
not `0.0.0.0`. Allow that inbound UDP source/port through the host firewall and
container networking. Moxa settings are not changed by this integration.

Enter the Moxa source IPv4 address and local listening address/port. Setup defaults
to EX35 telemetry with **Send captured read requests** enabled. Turn that checkbox
off for passive reception. The setup form itself sends no probe; acquisition
starts after the entry is created. Under **Configure**, choose individual reads,
profile and timing. All settings are validated again when loading persisted entries.

| Network field | New-entry default | Rationale / behavior |
| --- | --- | --- |
| Moxa source IPv4 | Required | Numeric unicast address; no DNS or IPv6 |
| Local listening IPv4 | `0.0.0.0` | Works without requiring a particular HA interface address |
| Local UDP port | `4001` | Match the Moxa destination port |
| Moxa source UDP port | `4001` | Matches the tested Moxa; `0` explicitly accepts any source port |

Requests use the same bound socket as reception. The destination port for requests
is separate from the source filter. **Reconfigure** changes network settings and
reloads while preserving IDs and options. Overlapping local listeners/source
filters between entries are rejected. HA and the monitor may poll concurrently:
each needs its own listening endpoint, and Moxa UDP forwarding must deliver
replies to both. Processes cannot share the same local address/port.

## Read selection, polling and reviewed defaults

| Option | New-entry default | Rationale / behavior |
| --- | --- | --- |
| Decoder profile | EX35 telemetry — 0b15 | The observed installation; observation-only and passive RX50 remain available |
| Send captured read requests | On | The standalone pump requires polling; turn off for passive listening |
| Individual reads | `temperature`, `power`, `counters`, `heating_settings`, `hot_water_settings` | Select one or more of nine captured operations, not monitor groups |
| Polling cycle interval | 60 s | Between cycle starts; any positive finite value up to 3600 s, including fractions |
| Pause between reads | 0.25 s | After each compatible reply or timeout; 0–3600 s, yielding between sends even at zero |
| Moxa UDP request port | 4001 | Matches the tested listen port; independent of HA's local port |
| Pump protocol address | `656fde02` | Captured four-byte address, eight hex characters; not an IP address |
| Measurement freshness limit | 120 s | Two nominal cycles; 5–86400 s, greater than cycle interval and the sum of configured pauses |
| Incomplete frame timeout | 1 s | Allows fragmented UDP replies; 0.01–60 s, below the reply timeout when polling |
| Source-gap reset | 5 s | Discards abandoned partials after silence; at least partial timeout, at most 3600 s |
| Reply timeout (fixed) | 10 s | Allows a slow reply before advancing; no immediate retry |
| Transport-error reload delay (fixed) | 5 s | One recovery attempt scheduled through HA; normal HA retry handles failed binds |

A cycle sends each selected read once in selection order, with one outstanding
request of its own. A compatible complete reply or the fixed 10-second timeout
advances the cycle after the pause. The first read starts immediately on setup.
If a cycle overruns, the next starts after the last pause and uses that actual
start as its new origin: no overlap or catch-up burst. At the default timings,
five unanswered reads take about 51.25 seconds and all nine about 92.25 seconds.
The freshness range extends to one day so long cycle settings can still have a
longer expiry limit. A 120-second default accommodates unanswered default cycles; explicitly tighter limits
can make sensors unavailable when other reads time out. No automatic retries or
rate adjustments obscure which operations are sent. All timings are engineering
defaults, not measurements from the timestamp-free Loggamera capture.

All selected reads use the same cycle interval, including slow-changing settings
and counters. This keeps scheduling and freshness predictable for nine short
reads; optional reads add no traffic unless selected. Disabling a sensor entity
does not disable its read, since one read may serve many sensors. Change the read
selection to remove that operation. Switching off polling keeps the selected
sensors available for passive acquisition; unselected reads are not published.

Options reload the entry. On upgrade, existing profiles, explicit timings, polling
choices and source filters are preserved, including the old implicit observation,
passive and any-source-port defaults. EX35 entries gain the five default reads.
The interval now applies to the whole cycle. The existing profile identifier
`ex35_0b15_temperatures_v1` stays stable despite its broader UI label.

Reception is independent of the outstanding request: valid selected replies from
other pollers also update entities. Matching advances only the local scheduler.
There is no transaction ID and clients share `ADDR`; a compatible response may
have been triggered by another poller. A duplicate or delayed UDP reply cannot
always be distinguished from fresh traffic. Age reflects local byte receipt,
not proof of when the pump measured a value. Wrong source IP/port, pump address,
command, layout, length or CRC cannot update sensors. Partial buffers survive
our own sends/timeouts and expire according to the framing limits instead.

Only the nine captured `R` operations are permitted. The configurable pump address
must be established for an installation with this layout. There are no arbitrary
commands, writes or heating controls. HA `update_entity` reevaluates freshness;
it does not add a poll or socket. See [query mapping](query-mapping.md) and
[protocol](protocol.md) for exact registers and lengths.

## Entities and evidence

The temperature read creates nine temperature entities, all enabled by default with
°C, temperature device class, measurement state class and one decimal display
precision: outdoor, indoor, hot water, flow water, return water, hot gas,
exchanger outlet, evaporator inlet and exhaust air. Evidence provenance has no
effect on defaults, names, diagnostics or availability rules.

On upgrade, previously integration-disabled temperature entities are enabled once,
preserving their IDs and history. Entities explicitly disabled by the user stay
disabled. The entry-wide preference to disable new entities is also respected.

Outdoor, indoor and hot-water readings were checked against the pump display.
The other six names come from captures and reference implementations and lack
individual display confirmation. This distinction is retained here and in the
[protocol notes](protocol.md) as research history only.

The [read/entity table](../README.md#installation-and-setup) lists all supported
reads: 27 registered entities with the default five reads (26 enabled), 43 with
all nine (41 enabled). Optional
`calibration`, `ui_identity`, `fan_settings` and `compressor` reads can be enabled
independently. Pump local clock and the undecoded compressor response entity are
disabled by default; other selected sensors, including pump weekday, are enabled.
These defaults apply on entity creation and preserve existing user choices. Enable
the clock or compressor response manually in HA if wanted. Disabling an entity
does not change polling or diagnostic decoding. Deselecting a read
stops its polling/publication; old registry entries may remain unavailable and
retain their IDs/history for reselection.

Metadata follows [HA sensor semantics](https://developers.home-assistant.io/docs/core/entity/sensor/):

- Measured temperatures and power use measurement statistics, in °C and W.
- Energy counters use kWh; runtimes/durations use minutes. Energy and runtime
  reset/rollover behavior is not known, so they have no statistics state class
  yet. They retain ordinary recorder history, but energy counters are not offered
  to the Energy dashboard. Their accounting overlap and input/output meaning
  also remain unresolved; they must not be summed as electrical import.
- Read-only settings have units without a measurement statistics class.
  Hysteresis and calibration are temperature **differences**, allowing correct
  °C/°F conversion. Fan settings are signed percentages, not actual RPM or duty.
- The pump clock is local ISO text, not a timestamp sensor with an invented
  timezone. Clock, weekday, calibration and UI identity are diagnostic entities.
- The optional diagnostic **Compressor response** entity, when enabled, reports **Undecoded**
  when a valid fresh compressor reply arrives. The payload and unknown fields
  are in diagnostics. It becomes unavailable on silence; no compressor frequency,
  mode or alarm reading is invented. Unknown status fields from the temperature
  read likewise remain in diagnostics.

All sensors start unavailable; no saved state is restored as a fresh measurement.
A valid live selected frame updates its own fields only. Old sessions, replay,
unknown layouts and corrupt bytes cannot refresh them. A monotonic timer expires
each field at its freshness limit even during total silence. The observed −990
raw temperature marker makes that sensor unavailable immediately. Invalid clock
fields become unknown without discarding valid temperatures. Other sensor fault
encodings remain unknown. This integration provides no writable entities.

Receive timestamps belong to the collector, not the pump's measurement clock.
There is no history backfill. Home Assistant handles all history and visualization.
IDs depend on persistent entry ID and measurement key, not network addresses.
Reload/reconfigure and profile changes retain registry IDs. Switching to observation
stops publishing; returning to a profile starts unavailable. Creating a new entry
creates new IDs; no old value is restored as fresh.

## Lifecycle and diagnostics

Unload, failed setup, reload and HA shutdown close the socket and cancel polling,
response, framing and freshness timers. A transport error makes sensors unavailable
and schedules one reload after five seconds. Bind failures use HA's normal retry.
A missing response increments a timeout counter; the cycle advances to the next read, and readings age out. Passive silence simply continues listening.

Download diagnostics includes settings, poll/receiver/framing counters, measurement
ages, the latest 64 frames, 64 events and four raw datagrams. It also retains the latest
valid response for each selected read (at most nine), with decoded fields, unknown
regions and receive ages; these raw bytes are never sensor attributes. Network addresses,
session IDs and the structured pump address are redacted. Exact serial bytes remain
for diagnosis and can contain opaque identifiers; review before sharing. These
bounded memory rings reset on reload, and nothing is uploaded.

For unavailable sensors, inspect requests sent, replies received, timeouts, accepted
UDP datagrams and decoding reasons. A successful setup or transmit count alone does
not prove a working serial link. For original evidence use the passive
[capture tool](diagnostics.md), or inspect HA diagnostics while polling; two
listeners cannot bind the same address/port. No live polling is performed by tests.

Update a manual installation by disabling the entry, replacing the complete
component directory, and restarting HA. To remove it, delete the entry then the
component directory. HA history is not erased by this integration.

## Development verification

Protocol/tools: Python 3.13+ and `requirements-test.txt`:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q --ignore=tests/ha
```

HA runtime: Python 3.14 and the pinned harness:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-test-ha.txt -r requirements-lint.txt
.venv/bin/python -m pytest -c tests/ha/pytest.ini tests/ha -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q --ignore=tests/ha
.venv/bin/ruff check .
```

Recorded fixtures exercise every captured read and its sensor values, framing,
address/length checks, 104+35 splits, metadata, independent freshness and unknown
fields. HA tests cover defaults, individual selection/reload, migration/identity,
sequential cycles, timeouts, other-poller traffic, fragment preservation and
cleanup. Fake transports and localhost replace all live devices. See
[validation](validation.md) for the latest results.
