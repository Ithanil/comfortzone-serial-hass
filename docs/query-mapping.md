# EX35 monitor query mapping

Research checkpoint: 2026-10-26. These read groups are for the Moxa monitor;
Home Assistant still uses the existing temperature profile and request only.
All request registers and lengths below occur in the preserved Loggamera cycle.
Only the temperature read has been exercised standalone on the installation.

The monitor polls selected reads sequentially within each cycle, defaulting to
30 seconds between cycle starts and a 250 ms pause after each compatible reply
or timeout. Other pollers, including HA, can operate independently. Identical
captured requests share the `ADDR` address without a transaction ID, so a matching
reply cannot be attributed uniquely to the script. See [protocol](protocol.md).

Register prefix is `010203040b15`. The final three bytes identify a memory bank
and a little-endian address. Overlapping captured replies corroborate that
interpretation. Offsets below are zero-based payload offsets, excluding the
21-byte frame header. Original fixtures remain unchanged.

| Read | Register suffix | Payload bytes | Query groups |
| --- | --- | ---: | --- |
| temperature/status | `010400` | 117 | temperature, operation, misc |
| power | `015203` | 53 | power, operation |
| compressor | `01e302` | 59 | operation |
| counters | `052000` | 32 | counters |
| heating settings | `007202` | 178 | settings |
| hot-water settings | `002403` | 176 | settings |
| fan settings | `00e003` | 99 | settings |
| calibration | `007f00` | 10 | misc |
| UI identity | `019905` | 38 | misc |

## Mapped fields

- **Power:** offsets 0/u16, 2/u32, 6/u32 and 10/u32 are compressor heat
  output, auxiliary-heater output and two reported total heat-output fields;
  offset 14/u16 is compressor electrical input. All are little endian, watts.
  Capture: 1340, 0, 1340, 1340, 400 W. Keep both total fields named separately;
  equality in this capture does not establish their interchangeability.
- **Counters:** offsets 12, 16, 20 are u32 little-endian compressor, auxiliary
  and hot-water energy counters, divided by 100 for kWh. Offsets 24 and 28
  are u32 compressor/total runtime in minutes. Values: 2644.08, 393.52,
  2177.64 kWh; 98503 and 317186 minutes. The same 32 bytes occur at offset
  32 in the 64-byte `050000` reply. Counter accounting (input/output and
  overlap), reset behavior and rollover are not established; do not sum them
  or treat them as electrical-import measurements without further evidence.
- **Clock:** temperature/status offsets 0..6: hour, minute, second, day,
  month, year since 2000, weekday (Monday=1). These are binary, not BCD.
  The pump clock has no established timezone; it is not a receive timestamp.
- **Heating:** offset 27/u8 is the curve setting divided by 10; 28/i16 LE
  is the reference's calculated heating setting divided by 10, in degrees C.
  Capture: 3.0 and 21.0 C. The matching reference settings block starts at
  payload offset 19; the two values also occur in the overlapping `001402`
  reply at the same memory addresses. Do not relabel the latter as measured
  flow temperature or a user-selected room setpoint.
- **Hot water:** offset 37/i16 LE is the setpoint, 39/i16 the hysteresis,
  158/i16 the extra-hot-water setpoint, all divided by 10; 160/u16 is extra
  duration in minutes. Capture: 50.0 C, 5.0 C, 55.0 C, 180 minutes. The
  consecutive table/field structure matches the reference from the setpoint
  onwards. The setpoint/hysteresis pair is repeated in `00c602`.
- **Fan settings:** offsets 1, 3, 5 are signed 16-bit LE settings divided
  by 10: normal, reduced and high-speed settings (80.0, -30.0, 30.0 percent).
  They follow the hot-water settings structure at bank 0 addresses 0x03e1,
  0x03e3, 0x03e5 and recur in `007703`. Reduced/high settings are not claims
  about actual instantaneous fan duty, RPM or airflow. Their absolute-versus-
  adjustment semantics remain unresolved. Byte 0 is not assigned a mode name.
- **Calibration:** ten signed one-byte adjustments, TE0..TE9, divided by 10
  in degrees C. Capture: 0, 1.3, 0.9, 0, 0, 0.7, 0, 0, 0, 0. All ten bytes
  also occur at bank 0 address 0x007f in the broad `000000` read.
- **UI information:** bytes 0..2 form major.minor.patch (2.30.0); byte 3 is
  the hardware revision code (10). This does not identify the controller
  firmware version from the `0b15` register prefix.

The nine existing temperature fields retain their established mapping and
sentinel handling. All mapped fields are presented uniformly. Evidence and
unresolved semantics belong in documentation, not confidence badges/defaults.

## Operation and other unknown bytes

Status bytes 11..54 and the 59-byte compressor reply contain operation data,
but exact EX35 locations/masks for mode, alarms, compressor state and frequency
are not established by these captures. Preserve these regions and explicitly
report the requested interpretations as unknown. In particular, do not assert
"no alarm" from zero bytes at offsets borrowed from another layout.

The 2.50 reference uses register prefix `0b10`, status length 114 and sensor
offset 52; ours uses `0b15`, length 117 and offset 55. Its fan/compressor read
uses a different address. An unchanged decoder would call compressor payload
byte 3 a fan mode, although here it is also consistent with the high byte of
a percentage word. Plausible numbers alone do not resolve such ambiguity.
Power provides separately decoded output/input readings when operation is
selected; it is not silently converted into compressor-state/alarm flags.

Unmapped payload regions retain offsets and hex bytes. Known mappings may also
be decoded from the exact overlapping capture layouts; arbitrary new lengths
or prefixes do not select a decoder. Alarm/event history, refrigeration data
and advanced controller tuning are outside this work's scope.

## Sources and implementation provenance

- [Original reference frame definitions](https://github.com/qix67/comfortzone_heatpump/blob/c0a896db8163d721e373c983bc651e7863e8c28b/comfortzone_frame.h): power layout, energy/runtime scaling, clock and older controller structures.
- [Original field meanings](https://github.com/qix67/comfortzone_heatpump/blob/c0a896db8163d721e373c983bc651e7863e8c28b/comfortzone_status.h): distinguishes heat output from compressor electrical input.
- [Proposed 2.50 frame definitions](https://github.com/timdj/comfortzone_heatpump/blob/d401d5fd141cc05f576462aa2cd9b33359f030ea/comfortzone_frame.h) and [decoder](https://github.com/timdj/comfortzone_heatpump/blob/d401d5fd141cc05f576462aa2cd9b33359f030ea/comfortzone_decoder_status.cpp): contiguous settings/calibration/UI layouts and evidence of version-dependent flags. This is an unmerged reference for a different controller, not an EX35 firmware identification.
- [Owner fixtures](../tests/data/README.md): request cycle, fragmented replies,
  and standalone temperature replies. No capture timestamps/cadence are inferred.

Implementation is independently written from protocol facts and owner captures;
no GPL/unlicensed upstream implementation or tables are copied into runtime code.
