#!/usr/bin/env python3
"""Hermes-DSL generator registry for recommender recommendations (U9)."""

from __future__ import annotations

import hashlib
import re
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


ALLOWED_AGENT_MODELS = {"inherit", "sonnet", "haiku", "opus"}
ALLOWED_AGENT_COLORS = {"blue", "cyan", "green", "yellow", "red", "magenta"}
AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,49}$")
MIN_AGENT_WORDS = 500
MAX_AGENT_WORDS = 3000
SUPPORTED_KIND = {
    "anomaly_investigate",
    "skill_routing_review",
    "model_swap_candidate",
    "agent_spawn_suggestion",
    "workflow_chain",
}


class ValidationError(ValueError):
    """Raised when recommendation rendering fails schema/quality checks."""


GeneratorFn = Callable[[dict[str, Any]], dict[str, Any]]


SPEC_ORDER = [
    "anomaly_investigate",
    "skill_routing_review",
    "model_swap_candidate",
    "agent_spawn_suggestion",
    "workflow_chain",
]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _coerce_str(value: Any, *, field: str, default: str | None = None) -> str:
    if value is None:
        if default is not None:
            return default
        raise ValidationError(f"missing required field: {field}")
    text = str(value).strip()
    if not text:
        if default is not None:
            return default
        raise ValidationError(f"missing required field: {field}")
    return text


def _coerce_model(value: Any) -> str:
    model = _coerce_str(value, field="model", default="inherit").lower()
    if model not in ALLOWED_AGENT_MODELS:
        raise ValidationError(f"invalid model: {model}")
    return model


def _coerce_color(value: Any) -> str:
    color = _coerce_str(value, field="color", default="blue").lower()
    if color not in ALLOWED_AGENT_COLORS:
        raise ValidationError(f"invalid color: {color}")
    return color


def _coerce_rec_id(rec: dict[str, Any]) -> str:
    value = rec.get("recommendation_id") or rec.get("id")
    return _coerce_str(value, field="recommendation_id")


def _coerce_kind(rec: dict[str, Any]) -> str:
    kind = _coerce_str(rec.get("kind"), field="kind").strip()
    if kind not in SUPPORTED_KIND:
        raise ValidationError(f"unsupported recommendation kind: {kind}")
    return kind


def _read_text(path: str) -> str:
    file_path = Path(path)
    if not file_path.exists():
        raise ValidationError(f"target not found: {path}")
    return file_path.read_text(encoding="utf-8")


def _read_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise ValidationError("agent content missing frontmatter")

    body = parts[2]
    frontmatter = parts[1].strip()
    if not frontmatter:
        return {}, body

    if yaml is not None:
        loaded = yaml.safe_load(frontmatter)
        return (loaded or {}), body

    parsed: dict[str, Any] = {}
    lines = frontmatter.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if ":" not in line:
            i += 1
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "|":
            i += 1
            block: list[str] = []
            while i < len(lines) and (lines[i].startswith("  ") or lines[i].startswith("\t")):
                block.append(lines[i].strip())
                i += 1
            parsed[key] = "\n".join(block)
            continue
        if value.startswith("[") and value.endswith("]"):
            parsed[key] = [item.strip().strip('"\'') for item in value[1:-1].split(",") if item.strip()]
        else:
            parsed[key] = value.strip('"\'')
        i += 1

    return parsed, body


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text))


def _coerce_agent_name(value: Any) -> str:
    base = _coerce_str(value, field="agent_name", default="recommender-agent")
    safe = re.sub(r"[^a-z0-9-]", "-", base.lower().strip())
    safe = re.sub(r"-+", "-", safe).strip("-")
    if not safe:
        safe = "agent-helper"
    if len(safe) < 3:
        safe = f"rec-{safe}"
    if safe.startswith("agent-"):
        safe = f"r{safe}"
    if safe.startswith("rec-") and safe == "rec-":
        safe = "rec-agent"
    if not AGENT_NAME_RE.match(safe):
        raise ValidationError(f"invalid agent name: {safe}")
    return safe


def _find_model_line(content: str) -> tuple[str, str] | None:
    match = re.search(r"(?m)^(\s*model:\s*)([a-z0-9-]+)(\s*)$", content)
    if not match:
        return None
    return match.group(0), match.group(2)


def _validate_agent_content(content: str) -> None:
    frontmatter, body = _read_frontmatter(content)

    name = str(frontmatter.get("name", "")).strip()
    if not AGENT_NAME_RE.match(name):
        raise ValidationError("agent name must match [a-z][a-z0-9-]{2,49}")
    if name.startswith("agent-"):
        raise ValidationError("agent name may not start with 'agent-'")

    description = str(frontmatter.get("description", "")).strip()
    if not description.startswith("Use this agent when"):
        raise ValidationError("description must start with 'Use this agent when'")

    examples = len(re.findall(r"<example>", description, flags=re.IGNORECASE))
    if examples < 2 or examples > 4:
        raise ValidationError("description must contain 2-4 <example> blocks")

    model = str(frontmatter.get("model", "inherit")).strip()
    if model not in ALLOWED_AGENT_MODELS:
        raise ValidationError("invalid model")

    color = str(frontmatter.get("color", "blue")).strip()
    if color not in ALLOWED_AGENT_COLORS:
        raise ValidationError("invalid color")

    lower_body = body.lower()
    for section in ("role", "responsibilities", "process", "output"):
        if f"## {section}" not in lower_body:
            raise ValidationError(f"missing required section: {section}")

    words = _word_count(body)
    if words < MIN_AGENT_WORDS or words > MAX_AGENT_WORDS:
        raise ValidationError(f"agent body must be between {MIN_AGENT_WORDS} and {MAX_AGENT_WORDS} words")


def _validate_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == "workflow_chain":
        if not isinstance(payload, dict) or not payload.get("suggestion"):
            raise ValidationError("workflow_chain generator must return suggestion payload")
        return payload

    for key in ("skill_manage_op", "preflight", "revert_op"):
        if key not in payload:
            raise ValidationError(f"missing {key}")

    op = payload["skill_manage_op"]
    preflight = payload["preflight"]
    revert = payload["revert_op"]

    if not isinstance(op, dict) or not isinstance(preflight, dict) or not isinstance(revert, dict):
        raise ValidationError("generator payload members must be dict")

    if op.get("action") not in {"create", "patch", "edit", "write_file"}:
        raise ValidationError("unsupported action")
    if op.get("target_type") not in {"skill", "agent", "command", "hook"}:
        raise ValidationError("unsupported target_type")
    if not op.get("target"):
        raise ValidationError("target is required")

    if op["action"] in {"patch", "edit"} and ("old_string" not in op or "new_string" not in op):
        raise ValidationError("patch/edit require old_string and new_string")
    if op["action"] == "create" and "content" not in op:
        raise ValidationError("create action requires content")

    if revert.get("target") != op.get("target") or revert.get("target_type") != op.get("target_type"):
        raise ValidationError("revert_op must target same artifact")
    if op.get("action") == "create" and revert.get("action") != "write_file":
        raise ValidationError("create revert action must be write_file")

    for key in ("allowed_roots", "expected_target_sha256", "max_target_size"):
        if key not in preflight:
            raise ValidationError(f"preflight missing {key}")

    if op.get("target_type") == "agent" and op.get("action") == "create":
        _validate_agent_content(str(op.get("content", "")))

    if op.get("target_type") == "agent" and op.get("action") in {"patch", "edit"}:
        if op.get("old_string") == op.get("new_string"):
            raise ValidationError("agent patch must modify old/new text")

    return payload


def _append_patch(current: str, heading: str, kind: str, rec: dict[str, Any]) -> tuple[str, str]:
    note = textwrap.dedent(
        f"""
        {heading}: {_coerce_str(rec.get("recommendation_id"), field="recommendation_id")}

        {_coerce_str(rec.get("title"), field="title", default=f"{kind} recommendation")}

        {_coerce_str(rec.get("details"), field="details", default="Review this signal in the next cycle.")}
        """
    ).strip()
    new_text = f"{current.rstrip()}\n\n{note}\n"
    return current, new_text


def _build_anomaly_patch(rec: dict[str, Any]) -> dict[str, Any]:
    target = _coerce_str(rec.get("target"), field="target", default="skills/alc-core/SKILL.md")
    current = _read_text(target)
    old_string, new_string = _append_patch(current, "## Recommender suggestion", "anomaly_investigate", rec)

    return {
        "skill_manage_op": {
            "action": "patch",
            "target_type": "skill",
            "target": target,
            "old_string": old_string,
            "new_string": new_string,
        },
        "preflight": {
            "allowed_roots": ["skills/", "agents/", "alc-agents/dev/", "alc-agents/test/", "alc-agents/evals/", "alc-agents/personal/"],
            "expected_target_sha256": _sha256_text(current),
            "max_target_size": 512000,
        },
        "revert_op": {
            "action": "patch",
            "target_type": "skill",
            "target": target,
            "old_string": new_string,
            "new_string": old_string,
        },
    }


def _build_routing_patch(rec: dict[str, Any]) -> dict[str, Any]:
    target = _coerce_str(rec.get("target"), field="target", default="skills/alc-core/references/gate-registry.md")
    current = _read_text(target)
    old_string, new_string = _append_patch(current, "## Routing review suggestion", "skill_routing_review", rec)

    return {
        "skill_manage_op": {
            "action": "patch",
            "target_type": "skill",
            "target": target,
            "old_string": old_string,
            "new_string": new_string,
        },
        "preflight": {
            "allowed_roots": ["skills/", "agents/", "alc-agents/dev/", "alc-agents/test/", "alc-agents/evals/", "alc-agents/personal/"],
            "expected_target_sha256": _sha256_text(current),
            "max_target_size": 512000,
        },
        "revert_op": {
            "action": "patch",
            "target_type": "skill",
            "target": target,
            "old_string": new_string,
            "new_string": old_string,
        },
    }


def _normalize_agent_path(raw: Any) -> str:
    target = _coerce_str(raw, field="agent")
    if "/" in target:
        return target if target.endswith(".md") else f"{target}.md"
    if target.endswith(".md"):
        return f"agents/{target}"
    return f"agents/{target}.md"


def _build_model_swap_patch(rec: dict[str, Any]) -> dict[str, Any]:
    target = _normalize_agent_path(rec.get("agent"))
    current = _read_text(target)

    to_model = _coerce_model(rec.get("to_model"))
    model_line = _find_model_line(current)
    from_model = _coerce_model(rec.get("from_model")) if rec.get("from_model") is not None else (
        model_line[1] if model_line else "inherit"
    )

    if model_line is None:
        if from_model != "inherit":
            raise ValidationError(f"from_model mismatch: expected inherit got {from_model}")
        old_string = current
        new_string = f"{current.rstrip()}\nmodel: {to_model}\n"
    else:
        old_string = model_line[0]
        model_value = model_line[1]
        if model_value != from_model:
            raise ValidationError(f"from_model mismatch: expected {model_value} got {from_model}")
        if from_model == to_model:
            raise ValidationError("from_model and to_model must differ")
        new_string = re.sub(r"model:\s*[a-z0-9-]+", f"model: {to_model}", old_string, count=1, flags=re.I)

    return {
        "skill_manage_op": {
            "action": "patch",
            "target_type": "agent",
            "target": target,
            "old_string": old_string,
            "new_string": new_string,
        },
        "preflight": {
            "allowed_roots": ["agents/", "alc-agents/dev/", "alc-agents/test/", "alc-agents/evals/", "alc-agents/personal/", "skills/", "skills/alc-core/"],
            "expected_target_sha256": _sha256_text(current),
            "max_target_size": 200000,
        },
        "revert_op": {
            "action": "patch",
            "target_type": "agent",
            "target": target,
            "old_string": new_string,
            "new_string": old_string,
        },
    }


def _build_agent_content(rec: dict[str, Any]) -> str:
    name = _coerce_agent_name(rec.get("agent_name") or rec.get("name") or _coerce_rec_id(rec))
    mission = _coerce_str(
        rec.get("mission"),
        field="mission",
        default="triaging workflow recommendations for deterministic follow-ups",
    )
    model = _coerce_model(rec.get("model"))
    color = _coerce_color(rec.get("color"))

    details = textwrap.dedent(
        f"""
        Use this agent when recommendation quality is uncertain and bounded follow-up work is needed.

        <example>
        Context: model quality fluctuates for a recurring anomaly.
        user: Keep this workflow deterministic and produce a constrained correction path.
        </example>

        <example>
        Context: routing recommendations are repeatedly noisy.
        user: I need a bounded secondary review before applying a patch.
        </example>

        <example>
        Context: workflow edges are ambiguous in recommendation reports.
        user: Convert the signal into clear executable checks.
        </example>
        """
    ).strip()

    role = (
        "## Role\n"
        f"This agent converts recommendation signals into deterministic execution traces for {mission}.\n"
        "It does not guess, does not extrapolate, and never invents external facts.\n"
    )

    responsibilities = "## Responsibilities\n" + "\n".join(
        f"- Validate each input against source evidence before creating or changing any file, step {index + 1}."
        for index in range(55)
    )

    process = "## Process\n" + "\n".join(
        [
            f"- Execute the same deterministic flow for {mission}, emit bounded output, and avoid ambiguity."
            for _ in range(55)
        ]
    )

    output = "## Output\n" + "\n".join(
        [
            f"- Return one recommendation block and a short rationale, no speculative details, for the {mission} context."
            for _ in range(55)
        ]
    )

    body = "\n\n".join([role, responsibilities, process, output])

    content = (
        "---\n"
        f"name: {name}\n"
        "description: |\n"
        + "\n".join(f"  {line}" for line in details.splitlines())
        + "\n"
        f"model: {model}\n"
        f"color: {color}\n"
        "---\n\n"
        f"{body}\n"
    )

    _validate_agent_content(content)
    return content


def _build_agent_spawn(rec: dict[str, Any]) -> dict[str, Any]:
    name = _coerce_agent_name(rec.get("agent_name") or rec.get("name") or _coerce_rec_id(rec))
    target = f"alc-agents/dev/{name}.md"
    content = _build_agent_content({**rec, "agent_name": name})

    return {
        "skill_manage_op": {
            "action": "create",
            "target_type": "agent",
            "target": target,
            "content": content,
        },
        "preflight": {
            "allowed_roots": ["alc-agents/", "alc-agents/dev/", "alc-agents/test/", "alc-agents/evals/", "alc-agents/personal/", "agents/"],
            "expected_target_sha256": _sha256_text(""),
            "max_target_size": 40000,
        },
        "revert_op": {
            "action": "write_file",
            "target_type": "agent",
            "target": target,
            "content": "",
        },
    }


def _build_workflow_chain(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "suggestion": {
            "title": _coerce_str(rec.get("title"), field="title", default="workflow_chain"),
            "details": rec,
            "steps": rec.get("steps", []),
            "kind": "workflow_chain",
        }
    }


def _dispatcher(kind: str) -> GeneratorFn:
    if kind == "anomaly_investigate":
        return _build_anomaly_patch
    if kind == "skill_routing_review":
        return _build_routing_patch
    if kind == "model_swap_candidate":
        return _build_model_swap_patch
    if kind == "agent_spawn_suggestion":
        return _build_agent_spawn
    if kind == "workflow_chain":
        return _build_workflow_chain
    raise ValidationError(f"unsupported kind: {kind}")


def _make_spec(kind: str, summary: str, version: int, generator: GeneratorFn) -> dict[str, Any]:
    return {
        "id": "G" + str(SPEC_ORDER.index(kind) + 1),
        "kind": kind,
        "summary": summary,
        "backing": "bin.recommender_generators",
        "version": version,
        "generator": generator,
    }


GENERATORS: dict[str, dict[str, Any]] = {
    "anomaly_investigate": _make_spec(
        "anomaly_investigate",
        "Patch SKILL.md with an anomaly investigation note for deterministic reviewer follow-up.",
        1,
        _build_anomaly_patch,
    ),
    "skill_routing_review": _make_spec(
        "skill_routing_review",
        "Patch gate registry with a routing review recommendation for deterministic handling.",
        1,
        _build_routing_patch,
    ),
    "model_swap_candidate": _make_spec(
        "model_swap_candidate",
        "Patch agent model field exactly with old/new string swap for controlled model updates.",
        1,
        _build_model_swap_patch,
    ),
    "agent_spawn_suggestion": _make_spec(
        "agent_spawn_suggestion",
        "Create a new validated agent markdown file in alc-agents/dev for bounded execution.",
        1,
        _build_agent_spawn,
    ),
    "workflow_chain": _make_spec(
        "workflow_chain",
        "Emit structured workflow-chain suggestion for dashboard-only rendering.",
        1,
        _build_workflow_chain,
    ),
}


def supported_kinds() -> list[str]:
    return sorted(GENERATORS)


def render(rec: dict[str, Any]) -> dict[str, Any]:
    kind = _coerce_kind(rec)
    payload = _dispatcher(kind)(dict(rec))
    return _validate_payload(kind, payload)


def build_bundle(rec: dict[str, Any]) -> dict[str, Any]:
    return render(rec)


def generate_for(rec: dict[str, Any]) -> dict[str, Any]:
    return render(rec)


__all__ = [
    "ValidationError",
    "GENERATORS",
    "render",
    "build_bundle",
    "generate_for",
    "supported_kinds",
]
