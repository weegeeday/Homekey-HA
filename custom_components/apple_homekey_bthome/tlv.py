"""TLV8 encoding and decoding helpers for HAP NFCAccessControlPoint payloads."""

from __future__ import annotations

from typing import Any, Iterable


def encode_tlv8(items: Iterable[tuple[int, bytes | int | bytearray]] | dict[int, Any]) -> bytes:
    """Encode a dictionary or list of (tag, value) tuples into TLV8 bytes."""
    res = bytearray()
    
    if isinstance(items, dict):
        pairs = items.items()
    else:
        pairs = items

    for tag, val in pairs:
        if isinstance(val, int):
            raw = bytes([val])
        elif isinstance(val, (bytes, bytearray)):
            raw = bytes(val)
        elif val is None:
            raw = b""
        else:
            raw = bytes(val)

        if len(raw) == 0:
            res.extend([tag, 0])
        else:
            idx = 0
            while idx < len(raw):
                chunk_len = min(255, len(raw) - idx)
                res.extend([tag, chunk_len])
                res.extend(raw[idx : idx + chunk_len])
                idx += chunk_len
    return bytes(res)


def decode_tlv8(data: bytes) -> list[tuple[int, bytes]]:
    """Decode TLV8 byte stream into a list of (tag, value) tuples.
    
    Combines contiguous TLV elements with identical tags per HAP specification.
    """
    result: list[tuple[int, bytes]] = []
    idx = 0
    data_len = len(data)

    while idx < data_len:
        if idx + 2 > data_len:
            break
        tag = data[idx]
        length = data[idx + 1]
        idx += 2

        if idx + length > data_len:
            val = data[idx:]
            idx = data_len
        else:
            val = data[idx : idx + length]
            idx += length

        if result and result[-1][0] == tag:
            prev_tag, prev_val = result[-1]
            result[-1] = (prev_tag, prev_val + val)
        else:
            result.append((tag, val))

    return result


def decode_tlv8_dict(data: bytes) -> dict[int, bytes]:
    """Decode TLV8 bytes into a dictionary mapping tag integer to value bytes."""
    items = decode_tlv8(data)
    res: dict[int, bytes] = {}
    for tag, val in items:
        res[tag] = val
    return res
