# Validation checkpoint — 2026-10-25

Local verification on Python 3.14.7, with the pinned Home Assistant 2026.10.2
harness. All **463 integration tests pass**:

- **431 protocol/tools tests**: existing framing/recording cases plus the exact
  captured request cycle and replies, all 138 split points of a 139-byte response,
  EX35 layout guards, signed values, unavailable marker, read-only request
  generation, reply matching, timeouts/recovery and cancellation.
- **32 HA runtime tests**: existing passive behavior plus EX35 options, opt-in
  polling, three enabled/six disabled entities, hot water, sentinel/stale states,
  diagnostics and cleanup.

An actual localhost UDP test sends the captured read through the production
listener and receives the recorded 104+35-byte response through that same bound
socket. All other hardware paths use fake transports. No test contacts the real
Moxa/pump. The sandbox blocked event-loop worker wakeups; the complete suites ran
successfully outside it with their existing fixtures and localhost restrictions.

Ruff, Python compilation, diff whitespace, local documentation links, JSON and
translation consistency also pass. Captured fixture provenance is in
[tests/data/README.md](../tests/data/README.md). The parent research repository has
two additional passing integrity tests for the preserved logs and fixture extraction.

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
