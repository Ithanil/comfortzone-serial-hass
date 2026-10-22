# Changelog

## 0.1.0 — unreleased

Initial receive-only implementation for local evaluation:

- Standalone `comfortzone-serial-hass` repository, display name **ComfortZone Serial**
  and integration domain `comfortzone_serial`.
- Configurable IPv4 UDP reception, sender filtering, bounded framing, CRC checks
  and recovery from corrupt or incomplete traffic.
- Observation-only default and an explicit provisional eight-temperature profile.
- Home Assistant UI setup, options/reconfiguration, sensor metadata, freshness,
  unavailable states, bounded diagnostics and lifecycle recovery.
- Optional bounded raw diagnostic capture and offline replay commands.
- Synthetic protocol and Home Assistant tests, MIT licensing, HACS metadata and
  standalone repository workflows.

Requires Home Assistant 2026.10.2 or newer. Tested with 2026.10.2; compatibility
with later releases still needs their tests. No real EX35 or Moxa captures have
been validated. Wiring, serial settings, controller layout and traffic without
Loggamera remain unverified. No release has been published.
