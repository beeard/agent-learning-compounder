"""Action state for the agent-learning dashboard.

Writes durable JSON files under `<personal>/actions/`:

  promoted-gates.json  – list of {key, domain, gate_category, promoted_at, by}
  muted-domains.json   – list of {domain, muted_at, by, reason}

`distill_learning` reads `muted-domains.json` to skip those domains during
classification. Promotion is recorded for visibility; future passes can use
it to elevate a gate's level or pin it to the brief.

All writes are append-with-dedupe and atomic (write to temp + replace).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import tempfile
from typing import Any, Iterable


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=False)
            fh.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _safe_load(path: pathlib.Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def actions_dir(personal: pathlib.Path) -> pathlib.Path:
    return personal / "actions"


def promoted_path(personal: pathlib.Path) -> pathlib.Path:
    return actions_dir(personal) / "promoted-gates.json"


def muted_path(personal: pathlib.Path) -> pathlib.Path:
    return actions_dir(personal) / "muted-domains.json"


def load_promoted(personal: pathlib.Path) -> list[dict]:
    return _safe_load(promoted_path(personal))


def load_muted(personal: pathlib.Path) -> list[dict]:
    return _safe_load(muted_path(personal))


def muted_domain_set(personal: pathlib.Path) -> set[str]:
    return {
        (item.get("domain") or "").strip()
        for item in load_muted(personal)
        if (item.get("domain") or "").strip()
    }


def promote_gate(personal: pathlib.Path, *, key: str, domain: str, gate_category: str, by: str = "dashboard") -> dict:
    """Idempotent — re-promoting an existing key bumps its `last_promoted_at`."""
    path = promoted_path(personal)
    rows = load_promoted(path.parent.parent if False else personal)
    timestamp = _now()
    updated = False
    for row in rows:
        if row.get("key") == key:
            row["last_promoted_at"] = timestamp
            row["domain"] = domain
            row["gate_category"] = gate_category
            updated = True
            break
    if not updated:
        rows.append({
            "key": key,
            "domain": domain,
            "gate_category": gate_category,
            "promoted_at": timestamp,
            "last_promoted_at": timestamp,
            "by": by,
        })
    _atomic_write(path, rows)
    return {"key": key, "domain": domain, "gate_category": gate_category, "updated": updated, "ts": timestamp}


def unpromote_gate(personal: pathlib.Path, *, key: str) -> dict:
    path = promoted_path(personal)
    rows = load_promoted(personal)
    new_rows = [row for row in rows if row.get("key") != key]
    removed = len(rows) - len(new_rows)
    _atomic_write(path, new_rows)
    return {"key": key, "removed": removed}


def mute_domain(personal: pathlib.Path, *, domain: str, reason: str | None = None, by: str = "dashboard") -> dict:
    path = muted_path(personal)
    rows = load_muted(personal)
    timestamp = _now()
    updated = False
    for row in rows:
        if row.get("domain") == domain:
            row["last_muted_at"] = timestamp
            row["reason"] = reason
            updated = True
            break
    if not updated:
        rows.append({
            "domain": domain,
            "muted_at": timestamp,
            "last_muted_at": timestamp,
            "reason": reason,
            "by": by,
        })
    _atomic_write(path, rows)
    return {"domain": domain, "updated": updated, "ts": timestamp}


def unmute_domain(personal: pathlib.Path, *, domain: str) -> dict:
    path = muted_path(personal)
    rows = load_muted(personal)
    new_rows = [row for row in rows if row.get("domain") != domain]
    removed = len(rows) - len(new_rows)
    _atomic_write(path, new_rows)
    return {"domain": domain, "removed": removed}


def actions_summary(personal: pathlib.Path) -> dict:
    promoted = load_promoted(personal)
    muted = load_muted(personal)
    return {
        "promoted_count": len(promoted),
        "muted_count": len(muted),
        "promoted": promoted,
        "muted": muted,
    }
