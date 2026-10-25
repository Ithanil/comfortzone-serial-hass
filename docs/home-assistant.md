# Home Assistant setup and behavior

Supports **HA 2026.10.2 or newer**, tested with the pinned 2026.10.2 runtime on
Python 3.14. The protocol and hardware path have been verified on the owner's
EX35. The owner's deployed HA instance and extended polling remain to be tested.

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

Enter the Moxa source IPv4 address, local listening address/port, and optionally
its source port. Initial setup opens a passive listener without probing the pump.
Under **Configure** choose **EX35 temperatures — captured 0b15 layout** and enable
**Send temperature read requests** for standalone operation. Selecting the profile
alone remains passive, useful while observing existing traffic.

| Network field | Default | Meaning |
| --- | --- | --- |
| Moxa source IPv4 | Required | Numeric unicast Moxa address; no DNS or IPv6 |
| Local listening IPv4 | `0.0.0.0` | All local IPv4 interfaces, or an address assigned to HA |
| Local UDP port | `4001` | Match the Moxa destination port |
| Moxa source UDP port | `0` | Accept any port from that IP; set 4001 for the tested configuration |

The Moxa's listen port for requests is a separate option from this source filter.
Requests use the same bound socket as replies. **Reconfigure** changes the network
settings and reloads, preserving entity IDs and options. Overlapping listeners
and source filters between entries are rejected. Disable other listeners using
the same host/port, including diagnostic capture or bench scripts.

## Decoder, polling and freshness

| Option | Default | Behavior |
| --- | --- | --- |
| Decoder profile | Observation only | Select EX35 0b15 for this installation; legacy RX50 remains provisional |
| Send temperature read requests | Off | Explicitly enables the captured `R` operation; requires EX35 profile |
| Read interval | 30 s | 15–3600 s; no overlapping requests or immediate retry bursts |
| Moxa UDP listen port for requests | 4001 | Destination port at configured Moxa IP, independent of HA's listening port |
| Pump protocol address | `656fde02` | Four bytes as eight hex characters, observed in this installation's captures; not an IP address |
| Measurement freshness limit | 120 s | 5–3600 s, must exceed polling interval when polling is enabled |
| Incomplete frame timeout | 1 s | 0.01–60 s, below 10 s when polling; measured from first byte |
| Source-gap reset | 5 s | At least incomplete timeout, at most 3600 s |

Changing options reloads the entry. Existing entries stay passive on upgrade.
The integration sends the first read after opening the socket, then every interval.
It waits up to **10 seconds** for a CRC-valid reply from the selected pump address,
with the expected `r` command/register/length. Incomplete responses are discarded
on timeout and at the next read. Matching replies outside an outstanding request
are ignored for entity updates; duplicates cannot refresh a completed request.
There is no sequence ID, so a sufficiently delayed UDP response arriving during a
later request cannot be distinguished perfectly. The network must be trusted.

The fixed operation reads `010203040b15010400` for 117 payload bytes; there is no
arbitrary command, write, setpoint or control service. Pump address may be changed
only to an address established from captures for an installation with the same
layout. See [protocol](protocol.md). HA `update_entity` reevaluates freshness;
it does not add another poll or socket.

## Entities and evidence

The EX35 profile creates nine temperature entities, all with °C, temperature device
class, measurement state class and one decimal display precision. Only **outdoor,
indoor and hot water** are enabled by default: these match the pump display.
Six reference-mapped entities are disabled by default and may be enabled in the
entity registry: flow water, return water, hot gas, exchanger outlet, evaporator
inlet and exhaust air. Their channel positions are supported by captures and
reference implementations, but their individual labels lack display confirmation.

All sensors start unavailable. A matching live frame updates measurements; old
sessions, replay, unknown layouts and corrupt bytes cannot refresh them. A monotonic
timer expires measurements at their freshness limit even during total silence.
The observed −990 raw unused-channel marker immediately makes that sensor
unavailable. Other sensor fault encodings are not established. Unknown channels
and fields are not exposed. This integration provides no writable entities.

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
A missing response increments a timeout counter; polling continues on its regular
schedule, and readings age out. Passive silence simply continues listening.

Download diagnostics includes settings, poll/receiver/framing counters, measurement
ages, the latest 64 frames, 64 events and four raw datagrams. Network addresses,
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

Recorded fixtures exercise the exact request cycle, all replies, address/length
checks, the observed 104+35 split and every split point. HA tests cover opt-in
polling, options, three enabled/six disabled sensors, hot water, sentinels, stale
states and cleanup. Fake transports and localhost replace all live devices.
