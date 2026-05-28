#!/usr/bin/env python3
"""Shared envelope fields for artifact producer payloads."""

from __future__ import annotations

import datetime as dt
from typing import Any

ANALYST_RESERVED_FIELDS = {"generated_at", "fallback_mode", "fallback_samples_count"}


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def analyst_payload(
    *,
    fallback_mode: bool,
    fallback_samples_count: int,
    **fields: Any,
) -> dict[str, Any]:
    """Return the existing analyst artifact shape with shared envelope fields."""
    reserved = ANALYST_RESERVED_FIELDS.intersection(fields)
    if reserved:
        raise ValueError(f"reserved envelope field(s): {sorted(reserved)}")
    return {
        "generated_at": utc_now_iso(),
        "fallback_mode": bool(fallback_mode),
        "fallback_samples_count": int(fallback_samples_count),
        **fields,
    }
