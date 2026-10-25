# Captured EX35 fixtures

Owner-supplied October 2026 serial-over-UDP captures. Hex bytes are exact;
console endpoint labels were removed. Each line remains one UDP datagram, except
`loggamera-request-cycle.hex`, which contains one frame per line (also one datagram
in the original). There are no receive timestamps; tests assign synthetic times.

- `loggamera-request-cycle.hex`: first 46-request cycle from the full request capture.
  The full original has eight identical cycles and an initial stray `00`.
- `pump-reply-datagrams.hex`: all 72 original datagrams, 6460 bytes, 46 responses
  while Loggamera was connected. Temperature payload: 10.3 °C outdoor, 22.2 °C
  indoor, 46.9 °C hot water, explicitly confirmed against the pump display.
- `standalone-reply.hex`: 139-byte response to one captured temperature read,
  RS-422/19200/8N1, Loggamera physically unplugged. CRC 05.
- `standalone-split-reply.hex`: subsequent 104 + 35 byte delivery; total 139,
  CRC ab. Both standalone samples have 12.4/22.0/49.6 °C for those channels.
  These samples are transcribed from the owner's conversation, not synthetic.

Opaque serial addresses are retained to preserve CRC validity. No credentials are
known in these samples. The full unchanged console logs, hashes and experimental
history are retained by the parent research repository; these fixtures are
self-contained for standalone integration testing. Secondary temperature names
come from reference mappings; only the three noted channels were display-confirmed.
