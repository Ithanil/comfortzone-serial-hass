# How the working EX35 connection was established

The October 2026 investigation used the installed pump DB9 cable, Loggamera,
a Moxa **5150A**, a breakout and multimeter. No oscilloscope was available.

1. Negative idle voltages suggested RS-232. A three-wire 2/3 crossover, passive
   taps and serial-setting sweeps failed to recover valid pump traffic.
2. An isolated Moxa loopback and firewall correction established UDP forwarding.
   Startup `00` and connector-motion `ff` bytes were artifacts, not useful data.
   The owner corrected the assumed P5150A model to **5150A** with two bias jumpers.
3. At 19200/8N1 in RS-485 four-wire mode, comparing pump pin 3 (RX+) to pin 2
   (RX−) captured Loggamera's requests. Two-wire mode with that tap still captured
   only requests. The complete log contains eight identical 46-request cycles.
4. Comparing ground pin 5 (RX+) to pump pin 3 (RX−) captured pump responses.
   One complete cycle has 46 CRC-valid replies in 72 UDP datagrams. Outdoor,
   indoor and hot-water temperatures matched the display at 10.3/22.2/46.9 °C.
5. Removing Loggamera stopped traffic. It had supplied the necessary polls; local
   replacement must send reads. One captured temperature request suffices.
6. Moxa TX− pin 1 to pump pin 2, with the ground-referenced receiver retained,
   produced no reply in RS-485 four-wire mode despite the correct Tx count.
   Switching to **RS-422** produced repeatable valid 139-byte responses, with
   Loggamera physically unplugged. Driver-enable/idle behavior may explain the
   difference; its exact cause was not measured.
7. Leaving Moxa RX+ pin 3 floating stopped communication. Retain the local 3–5
   jumper. TX+ remains unconnected because it is an active output, unlike RX+.

The final wiring and settings are in the [README](../README.md#proven-wiring).
It uses separate ground-referenced signal directions through the Moxa differential
interface. The native pump circuitry/standard remains unknown; a working Moxa mode
must not be mistaken for a standard pump pinout or a universal adapter design.

The request-only versus reply-only taps are consistent with the measured idle
voltages: pin 2 around −5.4 V, pin 3 around −2.2 V. Loggamera pin-2 transitions
can reverse the sign across 3/2; pump pin-3 transitions may not. Against ground,
pin-3 transitions become readable and pin 2 is excluded. This is an explanation
consistent with the evidence, not an oscilloscope measurement.

The controller uses register prefix `0b15`, with 117 payload bytes and temperature
start offset 55. The legacy RX50 `0b0d` layout has 114 bytes and offset 52, so it
cannot be applied unchanged. No firmware version is inferred from the prefix.
UDP fragmentation into 104+35 bytes is normal: the combined reply has valid CRC.

[Fixtures](../tests/data/README.md) preserve the captured bytes for standalone
regression tests. Full original console logs, hashes and dated experiments live
in the [research repository](https://github.com/Ithanil/re_loggamera).
Read-only now means **read requests without writes**, not passive-only reception.
TCP, unknown registers, writable controls and cloud protocols are unnecessary for
this result. Extended polling and the owner's HA deployment remain validation work.
