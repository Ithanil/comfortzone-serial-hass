# Home Assistant setup and behavior

The initial Home Assistant runtime is tested against **Home
Assistant 2026.10.2 on Python 3.14**; older versions are not supported by this
initial version. HACS metadata and standalone workflows are included; see
[distribution](distribution.md) for the current installation boundary.
No real EX35 captures, installation or hardware compatibility have been validated.

## Install manually for evaluation

1. Copy this directory's `custom_components/comfortzone_serial/` into your Home
   Assistant configuration directory as `custom_components/comfortzone_serial/`.
   Include all files, the `LICENSE`, and the `telemetry/`, `translations/` and
   `brand/` subdirectories.
2. Restart Home Assistant. Under **Settings → Devices & services → Add integration**,
   choose **ComfortZone Serial**.
3. Enter the receiver settings below. Setup opens a local UDP socket; it does not
   contact the Moxa, detect a controller, or wait for a pump response. A successful
   setup only establishes that the local listener could start.
4. Keep the default **Observation only** profile for initial traffic inspection.
   Use the entry's **Download diagnostics** action to inspect bounded evidence.
5. After reviewing captures, the entry's **Configure** action offers the explicit
   **RX50 temperatures — provisional reference layout** option. This creates eight
   sensor entities for comparison with pump readings. Selecting it does not validate
   the layout; do not rely on these provisional readings for control automations.

For HACS, use the standalone
[comfortzone-serial-hass repository](https://github.com/Ithanil/comfortzone-serial-hass)
as a custom repository of type **Integration** once it is public and its
distribution checks pass. The investigation repository is not the HACS source.
HACS installation and a deployed HA instance remain unverified.

To update a manual installation, disable the entry, replace its component directory
with the new complete version and restart HA. Preserve the HA config entry to keep
its entity identities. To remove it, delete its entry under **Devices & services**,
then remove `custom_components/comfortzone_serial/` and restart HA. Deleting an entry
does not ask this integration to erase Home Assistant's recorded history.

## Network settings

| Setting | Default | Meaning |
| --- | --- | --- |
| Moxa source IPv4 address | Required | Numeric address of the expected UDP sender. Hostnames, IPv6, multicast and `0.0.0.0` are rejected. |
| Local listening IPv4 address | `0.0.0.0` | Listen on all local IPv4 interfaces, or specify an address assigned to the HA host. This is not the Moxa address. |
| Local UDP port | `4001` | Port on the HA host, from 1 to 65535. Match the Moxa's UDP destination port. |
| Moxa source UDP port | `0` | `0` accepts any source port from the configured IP; otherwise accept only the specified port (1–65535). The sender port need not equal the destination port. |

Configure the Moxa's UDP destination to the **actual reachable HA host address**,
never the wildcard `0.0.0.0`. Permit inbound UDP through relevant firewalls; a
container installation must expose the UDP port or use appropriate host networking.
This integration does not configure the Moxa or send application data to it.
IP/port filtering is not authentication; traffic must come from a trusted network.

Use the entry menu's **Reconfigure** action to change network settings. A reload
closes the old socket before starting a new session. Overlapping source filters
and local bind addresses are rejected between ComfortZone entries, including
disabled entries. A port occupied by another program fails at bind time; Home
Assistant reports a setup retry. Disable the conflicting program or change the
local port and Moxa destination together.

To use the [raw capture command](diagnostics.md) on the same host and port, disable
the HA entry first. It releases its socket. Re-enable the entry after recording.
The optional capture command is development tooling and is not started by HA.

Wiring, two-wire RS-485, baud rate and traffic without Loggamera remain unverified.
Confirm electrical compatibility before attaching the pump cable. Software reception
does not electrically disable the Moxa's transmitter; see the diagnostic guide's
hardware assumptions and the reference audit.

## Decoder and timing options

**Configure** changes the following options and automatically reloads the entry:

| Option | Default | Range and behavior |
| --- | --- | --- |
| Decoder profile | Observation only | No measurement entities are created initially; valid unknown/undecoded frames remain in diagnostics. The sole measurement profile is the provisional RX50 reference layout. |
| Measurement freshness limit | 120 seconds | 5–3600 seconds. Age since receipt of the final byte of that measurement's source frame. Tune only after observing the actual traffic cadence. |
| Incomplete frame timeout | 1 second | 0.01–60 seconds. Expire an incomplete candidate from its first byte, even during silence. |
| Reset partial data after a source gap | 5 seconds | At least the incomplete-frame timeout, at most 3600 seconds. Discard pending fragments when traffic resumes after a gap. |

The reference profile requires an exact command, register and payload length.
It creates outdoor, flow water, return water, indoor, hot gas, exchanger outlet,
evaporator inlet and exhaust air temperature sensors. Native units are °C, with
temperature device class and measurement state class; HA may display converted
units according to its settings. No other measurements, fault-value interpretation,
setpoints or writable entities are inferred. See [protocol.md](protocol.md).

Each sensor starts **unavailable**. Only matching live observations from the current
session update it. CRC failures and unrelated/unknown traffic cannot refresh its
age. A monotonic timer marks each reading unavailable at its freshness limit even
when traffic stops completely. Framing recovery keeps the original receive time;
a recovered old frame does not become a new measurement. Wall-clock changes do
not extend freshness. Replay never enters this HA publishing path.

Receive time is the collector's timestamp, not a pump-generated measurement time.
Diagnostics expose that timestamp, age and provisional profile provenance. HA
records the current state update; the integration does not backfill history or
put raw frame bytes/timestamps in sensor attributes on every packet. HA owns
measurement storage, history and visualization.

Entity and device identifiers use the persistent HA entry ID, independent of IP
addresses and source ports. The integration has no verified pump serial/MAC
identity and does not claim to detect an EX35 controller revision. Reconfiguration,
reload and profile changes retain entity registry identities. Deleting and creating
a new entry creates new identities. Switching back to observation only stops all
measurement publishing; existing registry entities remain unavailable. Switching
back restores the same IDs, initially unavailable. No prior value is restored as fresh.

## Lifecycle and diagnostics

Disabling, unloading, removing or reloading the entry, failed setup, cancellation,
and HA shutdown close the UDP socket and cancel owned timers. If platform unloading
fails, the running receiver is retained so a later unload can be retried. An actual
receiver error makes measurements unavailable immediately and schedules one reload
after five seconds. If binding the replacement fails, HA's normal setup retry
mechanism applies. Mere traffic silence expires measurements and keeps listening;
it does not trigger repeated reloads or any requests to the pump.

Download diagnostics includes receiver/framing counters, current measurement ages,
the most recent 64 frames, 64 framing events and four raw datagrams, plus bounded
partial buffers for up to eight source ports. These are in-memory rings, not a
durable recording; they reset on reload/restart. Unknown frames retain exact bytes
and decoding reasons. Use raw capture for evidence that must survive a reload.

Configured IP addresses, sender endpoints and session IDs are redacted from HA's
diagnostic download. Opaque serial bytes remain exact and may contain identifiers
that this decoder cannot recognize. Review a download before sharing it. No data
is uploaded by the integration.

If no sensors appear, check the selected profile. If sensors are unavailable,
inspect received/accepted datagram counters, framing CRC counters, decoding reasons
and measurement ages. Successful UDP reception alone does not prove valid wiring,
serial settings or a compatible layout. Capture and compare against the pump display;
do not change offsets merely to obtain plausible values.

## Development verification

The protocol/tools suite needs Python 3.13+ and `requirements-test.txt`:

```sh
python3 -m pytest -q --ignore=tests/ha
```

The HA suite needs Python 3.14 and the pinned HA harness. From this directory:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-test-ha.txt
.venv/bin/python -m pytest -c tests/ha/pytest.ini tests/ha -q
```

To run the protocol/tools suite in that same environment, disable the HA plugin's
global fixtures so plain asyncio and real loopback tests remain independent:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q --ignore=tests/ha
```

The HA tests load the actual integration/platform, flow manager, state machine and
entity/device registries from HA 2026.10.2. They inject synthetic datagrams into a
fake receive-only transport and reject sends. They cover UI validation, options
reload, initial/stale/unavailable states, original receipt times, replay/session
guards, stable IDs, diagnostics and cleanup/failure cases. These are software tests,
not a deployed-frontend test or hardware validation. The separate protocol/tools
suite includes actual UDP over localhost only.
