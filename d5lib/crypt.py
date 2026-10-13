"""Disgaea 5 PC data obfuscation: each byte is XOR 0xF0 then nibble-swapped.
The transform is its own inverse only in combination; we keep explicit tables."""
_DEC = bytes((((b ^ 0xF0) >> 4) | (((b ^ 0xF0) & 0xF) << 4)) for b in range(256))
_ENC = bytes(0 for _ in range(256))
_enc = bytearray(256)
for _i in range(256):
    _enc[_DEC[_i]] = _i
_ENC = bytes(_enc)


def decode(data: bytes) -> bytes:
    return data.translate(_DEC)


def encode(data: bytes) -> bytes:
    return data.translate(_ENC)


def is_obfuscated_nispack(head: bytes) -> bool:
    return decode(head[:7]) == b"NISPACK"
