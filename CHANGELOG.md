# Changelog

## 0.1.0 — unreleased

- Shared captured-read groups for monitor research: power, operation, counters,
  settings and misc; ordered/deduplicated polling with one pending read and
  exact reply matching. HA still polls only temperatures and creates no new entities.
- Optional cycle scheduling for the monitor: 30-second cycle interval and 250 ms
  inter-read pause by default, fractional intervals, timeout continuation and no
  overlapping/catch-up cycles. Concurrent clients' compatible replies are accepted
  without claiming exclusive request attribution; HA keeps fixed request spacing.
- Field inspection for power, counters, clock, calibration, UI information and
  selected heating/hot-water/fan settings, including overlapping captured windows.
  Unknown mode/alarm/compressor fields retain raw bytes without guessed values.
- Captured EX35 `0b15` temperature profile: 117-byte payload, offset 55 and hot water.
- All nine EX35 temperature sensors enabled by default with uniform presentation;
  mapping provenance retained in documentation only. A one-time upgrade enables
  former integration-disabled temperatures while preserving user disables and the
  entry-wide preference to disable new entities.
- Removed confidence annotations from diagnostics and UI labels; the legacy
  RX50 decoder's success reason is now `decoded` instead of `decoded_provisional`.
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
