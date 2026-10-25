# Changelog

## 0.1.0 — unreleased

- Captured EX35 `0b15` temperature profile: 117-byte payload, offset 55 and hot water.
- Outdoor, indoor and hot-water sensors enabled by default for that profile; six
  reference-mapped temperatures offered disabled by default.
- Opt-in standalone UDP read polling, fixed captured operation, matching replies,
  bounded response timeout, lifecycle cleanup and polling diagnostics.
- Unused-channel marker suppression and per-measurement freshness/unavailability.
- Verified 5150A RS-422 connector/settings, concise research history and real
  request/reply fixtures, including split UDP delivery.
- Existing passive observation and provisional RX50 modes retained without
  automatically enabling transmission on upgrade.
- UDP reassembly/CRC, offline recording/replay, HA configuration/reconfiguration,
  stable entity IDs, HACS metadata, MIT licensing and standalone CI workflows.

Minimum HA 2026.10.2; automated runtime tests target that version. Bench polling
works with Loggamera disconnected. Extended operation, the owner's HA deployment
and official distribution validation remain separate from automated tests.
No release has been published; TCP remains deferred.
