"""New synthetic protocol fixtures, with an independent bit-order CRC oracle.

No real captures or upstream test fixtures are included. The addresses and opaque
header bytes are arbitrary; passing a test does not validate those on the pump.
"""


def reference_crc(data: bytes) -> int:
    """Non-reflected polynomial arithmetic with explicitly reversed input/output."""
    value = 0
    for byte in data:
        value ^= int(f"{byte:08b}"[::-1], 2)
        for _ in range(8):
            value = ((value << 1) ^ (0x31 if value & 0x80 else 0)) & 0xFF
    return int(f"{value:08b}"[::-1], 2)


def make_frame(
    *,
    payload: bytes = b"",
    register: bytes = bytes.fromhex("010203040b0d010400"),
    command: int = ord("r"),
) -> bytes:
    """Construct a frame without invoking the implementation under test."""
    size = 22 + len(payload)
    assert len(register) == 9 and size <= 255
    header = bytes.fromhex("10203040000050607080") + bytes((size, command))
    body = header + register + payload
    return body + bytes((reference_crc(body),))


def temperature_frame(values: tuple[int, ...] | None = None) -> bytes:
    """Build eight signed tenths-of-degree fields in the provisional layout."""
    if values is None:
        values = (-125, 335, 281, 210, 654, 152, -37, 53)
    assert len(values) == 8
    payload = bytearray(114)
    for i, value in enumerate(values):
        payload[52 + 2 * i : 54 + 2 * i] = value.to_bytes(2, "little", signed=True)
    return make_frame(payload=bytes(payload))
