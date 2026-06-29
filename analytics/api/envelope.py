from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")

def wrap_handler(fn: Callable[..., T], *args, **kwargs) -> dict:
    try:
        return {"ok": True, "value": fn(*args, **kwargs)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
