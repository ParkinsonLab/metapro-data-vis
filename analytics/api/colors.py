from __future__ import annotations

BASE_LUM = 50


def _to_i32(n: int) -> int:
    """Emulate JS ``hash |= 0`` (signed 32-bit wrap) for map_lum parity with utils.ts."""
    n = n & 0xFFFFFFFF
    return n - 0x100000000 if n >= 0x80000000 else n


def map_lum(string: str) -> int:
    hash_val = 0
    for char in string:
        hash_val = (hash_val << 5) - hash_val + ord(char)
        hash_val = _to_i32(hash_val)
    return abs(int(hash_val % 80)) + 20


def get_color(i: int, n: int) -> str:
    hue = int((360 / (n + 1)) * i)
    return f"hsl({hue} 75 {BASE_LUM})"


def get_sub_color(c: str, label: str) -> str:
    return c.replace(f" {BASE_LUM})", f" {map_lum(label)})")
