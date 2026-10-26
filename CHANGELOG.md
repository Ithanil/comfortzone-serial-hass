# Changelog

## 0.1.0 — unreleased

- HA selects nine individual captured reads. Temperature, power, counters, heating
  settings and hot-water settings are selected by default; calibration, UI identity,
  fan settings and the undecoded compressor response are optional.
- 27 registered read-only sensor entities (26 enabled by default), 43 with all
  reads selected (41 enabled). Pump local clock and the undecoded compressor
  response entity default to disabled; manual entity choices are preserved. Units and
  availability are per field; raw/unknown payloads remain in bounded diagnostics.
  Energy/runtime counters keep ordinary history without assuming reset statistics.
- Shared cycle scheduling with a 60-second default interval for HA, 30 seconds for
  the monitor, and a 250 ms inter-read pause: one local request pending, timeout continuation and no
  overlapping/catch-up cycles. HA also consumes selected replies from other pollers
  and preserves receive fragments across its own sends/timeouts.
- New installations default to EX35 polling and source port 4001. Migration keeps
  existing acquisition choices, identities and user disables, and adds the five
  default reads. Freshness defaults to 120 seconds, configurable up to one day.
- Monitor query groups remain separate from HA's individual reads, using the same
  whitelisted request definitions and decoders.
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
- Standalone UDP polling uses only captured reads, with strict reply validation,
  bounded response timeouts, lifecycle cleanup and polling diagnostics.
- Unused-channel marker suppression and per-measurement freshness/unavailability.
- Verified 5150A RS-422 connector/settings, concise research history and real
  request/reply fixtures, including split UDP delivery.
- Existing passive observation and provisional RX50 modes retained without
  automatically enabling transmission on upgrade.
- UDP reassembly/CRC, offline recording/replay, HA configuration/reconfiguration,
  stable entity IDs, HACS metadata, MIT licensing and standalone CI workflows.

Minimum HA 2026.10.2; automated runtime tests target that version. Bench polling
works with Loggamera disconnected. The owner reports HA temperature polling in use; additional reads, extended
operation and official distribution validation remain separate owner checks.
No release has been published; TCP remains deferred.
