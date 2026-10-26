# Validation checkpoint — 2026-10-26

Local verification on Python 3.14.7, with the pinned Home Assistant 2026.10.2
harness. All **501 integration tests pass**:

- **465 protocol/tools tests**: existing framing/recording cases plus the exact
  captured request cycle and replies, all 138 split points of a 139-byte response,
  EX35 layout guards, signed values, unavailable marker, read-only request
  generation, reply matching, timeouts/recovery and cancellation. New query tests
  compare every allowed request byte-for-byte with the captured cycle, verify
  mapped values and overlapping windows, reject incorrect layouts, preserve
  unknown fields/bytes, and check ordered polling, deduplication, timeouts and
  non-overlap. Cycle tests cover fractional intervals, reply/timeout-driven
  advancement, overrun without catch-up bursts, duplicate and other-client
  traffic, and cancellation. HA's default request and decoder still cover
  temperatures only, with unchanged fixed request spacing.
- **36 HA runtime tests**: existing passive behavior plus EX35 options, opt-in
  polling, nine enabled entities, upgrade migration preserving explicit user
  disables and entry-wide preferences, hot water, sentinel/stale states,
  diagnostics and cleanup.

An actual localhost UDP test sends the captured read through the production
listener and receives the recorded 104+35-byte response through that same bound
socket. All other hardware paths use fake transports. No test contacts the real
Moxa/pump. The sandbox blocked local socket creation and event-loop worker wakeups;
the integration suites and parent localhost cases passed outside it with their
existing fixtures and localhost restrictions. The interrupted sandbox attempts
are not counted as successful checks.

Ruff, diff whitespace, local documentation links, JSON and translation
consistency also pass. Captured fixture provenance is in
[tests/data/README.md](../tests/data/README.md). The parent research repository has
**34 additional passing tests** for preserved-log integrity, fixture extraction
and the CLI monitor, including all six query groups, power polling with unrelated
incoming frames, uniform labels, partial decoding and JSON unknown regions.
Fast-cycle tests verify every read is logged even with zero configured pause,
and simultaneous temperature traffic remains visible throughout the cycle.
Together, **535 tests pass**. The new non-temperature reads have not been sent
to the installation by automated testing; owner live trials remain outstanding.

Commands from the standalone repository:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q --ignore=tests/ha
python -m pytest -c tests/ha/pytest.ini tests/ha -q
ruff check .
python -m compileall -q custom_components tools tests
```

Physical validation was performed separately by the owner: repeatable reads in
RS-422 with Loggamera physically disconnected, correct frame CRCs and three
display-confirmed temperatures. The final connector assembly, extended polling,
the owner's HA installation and official HACS/hassfest validation are not claimed
as completed by these tests. Version 0.1.0 remains unreleased.
