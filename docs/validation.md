# Validation checkpoint — 2026-10-26

Local verification on Python 3.14.7 with the pinned Home Assistant 2026.10.2
harness: **540 integration tests pass**, plus **34 parent-repository tests**,
**574 total**. No automated test contacts the live Moxa or pump.

Subsequent adjustment: HA's default cycle interval changed from 30 to 60 seconds.
Test expectations and documentation were updated; suites were not rerun for this
default-only change at the owner's request. The results below precede that tweak.

- **486 protocol/tools tests:** framing, recording/replay, all captured request
  bytes and reply layouts, split responses, address/length/CRC guards, field
  values and unknown regions, individual-read validation, group expansion,
  fixed/cycle scheduling, timeout continuation, overrun without catch-up bursts,
  shared-client matching and cleanup. Persisted-settings tests cover new defaults,
  individual read names, invalid types/timings, deduplication and long-cycle
  freshness. The final settings-only rerun includes the new long-cycle case.
- **54 HA runtime tests:** configuration/options, new EX35/polling/source-port
  defaults, opt-out, migration preserving existing choices and entity identities,
  the five default reads and 27 registered entities (26 enabled), all optional
  reads and 43 entities (41 enabled), disabled clock/undecoded-response defaults
  with manual enabling preserved across reload,
  read selection/reload, user disables, recorded sensor values and metadata,
  diagnostics, invalid clock/sentinel handling, per-field expiry, timeout
  progression, independent shared traffic and fragment preservation across sends
  and timeouts. Explicit Fahrenheit entity options verify calibration/hysteresis
  conversion without an absolute-temperature offset. Existing passive/RX50,
  lifecycle, failure recovery and live/replay isolation cases also pass.
- **34 parent tests:** preserved-evidence integrity and the CLI monitor's unchanged
  query groups/defaults, decoding/unknown bytes, cycle timing, simultaneous
  temperature traffic and immediate progress reporting.

UDP integration cases use localhost; other device paths use fake transports and
recorded/synthetic fixtures. The HA suite requires execution outside the sandbox
for its event-loop worker wakeups; localhost tests also need local socket access.
The interrupted sandbox attempt is not counted as a successful check. The final
HA run passed all 54 cases. The protocol run passed 485 cases before the final
freshness-bound refinement; all 21 settings cases then passed, giving 486 distinct
passing protocol/tools cases with that addition.

Ruff, diff whitespace, local documentation links, JSON parsing and matching
English translations pass. Fixture provenance is in
[tests/data/README.md](../tests/data/README.md); originals were not changed.

Commands from the integration repository:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q --ignore=tests/ha
python -m pytest -c tests/ha/pytest.ini tests/ha -q
ruff check .
```

Run the parent's `pytest` separately from the parent directory. Its collection
is restricted to `tests/`, excluding temporary bench scripts.

Physical validation was performed separately by the owner: repeatable temperature
reads in RS-422 with Loggamera disconnected, valid frame CRCs and three
display-confirmed temperatures. The owner also reports HA temperature polling
already running alongside the monitor. The new reads/sensors are verified against
captures and fake transports; standalone live trials of the additional reads,
extended operation, deployed frontend behavior and official HACS/hassfest checks
remain separate validation steps. Version 0.1.0 remains unreleased.
