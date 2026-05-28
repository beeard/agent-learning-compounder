#!/usr/bin/env python3
"""Shared parser for approved gate registry markdown."""

from __future__ import annotations

import dataclasses
import re
from typing import Iterable


GATE_ID_RE = re.compile(r"^[a-f0-9]{12}$")
FIELD_RE = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*:\s*(.*?)\s*$", re.I)


@dataclasses.dataclass(frozen=True)
class GateBlock:
    domain: str
    gate_id: str
    gate_category: str
    gate: str
    previous_gate_ids: list[str] = dataclasses.field(default_factory=list)
    level: str | None = None
    derived_from: str | None = None
    probe_status: str | None = None
    probe_rate: str | None = None
    fields: dict[str, str] = dataclasses.field(default_factory=dict)
    raw_block: str = ""

    @property
    def slot(self) -> tuple[str, str]:
        return (self.domain, self.gate_category)


def validate_gate_id(gate_id: str, *, field: str = "gate_id") -> None:
    if not GATE_ID_RE.fullmatch(gate_id):
        raise ValueError(f"{field} must be 12 lowercase hex characters: {gate_id}")


def parse_previous_gate_ids(value: str) -> list[str]:
    ids = [part.strip() for part in value.split(",") if part.strip()]
    if not ids:
        raise ValueError("previous_gate_ids must contain at least one gate id")
    seen: set[str] = set()
    out: list[str] = []
    for gate_id in ids:
        try:
            validate_gate_id(gate_id, field="previous_gate_ids")
        except ValueError as exc:
            raise ValueError(f"invalid previous_gate_ids entry: {gate_id}") from exc
        if gate_id in seen:
            raise ValueError(f"duplicate previous_gate_ids entry: {gate_id}")
        seen.add(gate_id)
        out.append(gate_id)
    return out


def parse_gate_blocks(text: str) -> list[GateBlock]:
    """Parse approved-gates markdown into gate blocks.

    The splitter is LF/CRLF tolerant and accepts files that begin directly
    with ``- domain:``.
    """
    blocks: list[GateBlock] = []
    for part in re.split(r"(?m)^(?=-\s+domain:)", text):
        if not re.match(r"-\s+domain:", part):
            continue
        lines = part.splitlines()
        first = re.match(r"-\s+domain:\s*(.*?)\s*$", lines[0], re.I)
        if not first:
            continue
        fields: dict[str, str] = {"domain": first.group(1).strip()}
        for raw in lines[1:]:
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                break
            match = FIELD_RE.match(raw)
            if not match:
                continue
            fields[match.group(1).lower()] = match.group(2).strip()
        required = ("domain", "gate_id", "gate_category", "gate")
        if not all(fields.get(field) for field in required):
            continue
        validate_gate_id(fields["gate_id"])
        previous_gate_ids = (
            parse_previous_gate_ids(fields["previous_gate_ids"])
            if fields.get("previous_gate_ids")
            else []
        )
        if fields["gate_id"] in previous_gate_ids:
            raise ValueError(f"gate_id {fields['gate_id']} cannot alias itself")
        blocks.append(
            GateBlock(
                domain=fields["domain"],
                gate_id=fields["gate_id"],
                gate_category=fields["gate_category"],
                gate=fields["gate"],
                previous_gate_ids=previous_gate_ids,
                level=fields.get("level"),
                derived_from=fields.get("derived_from"),
                probe_status=fields.get("probe_status"),
                probe_rate=fields.get("probe_rate"),
                fields=fields,
                raw_block=part.rstrip(),
            )
        )
    return blocks


def alias_map(blocks: Iterable[GateBlock]) -> dict[str, str]:
    """Return old_id -> canonical_id and reject ambiguous alias claims."""
    blocks = list(blocks)
    canonical_ids = {block.gate_id for block in blocks}
    aliases: dict[str, str] = {}
    for block in blocks:
        for old_id in block.previous_gate_ids:
            if old_id in canonical_ids:
                raise ValueError(
                    f"alias cycle or duplicate canonical id: {old_id} is both canonical and previous"
                )
            existing = aliases.get(old_id)
            if existing and existing != block.gate_id:
                raise ValueError(
                    f"previous gate id {old_id} claimed by multiple canonical gates: "
                    f"{existing}, {block.gate_id}"
                )
            aliases[old_id] = block.gate_id
    return aliases


def inherited_blocks_by_id(text: str) -> dict[str, GateBlock]:
    return {
        block.gate_id: block
        for block in parse_gate_blocks(text)
        if block.derived_from
    }
