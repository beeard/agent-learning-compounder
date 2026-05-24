# agent-learning-compounder: Eight-Upgrade Implementation Plan

> **Frozen historical work order.** All phases shipped in `2026.05.24+review7-plus1`; for the active status see `CHANGES.md`. Kept here for archaeological reference only — do not use the checkboxes below to schedule new work.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the vendored `agent-learning-compounder` (review7-production) with eight upgrades that turn it from a one-way distiller into a convergent, federated, queryable learning system.

**Architecture:** Five sequenced phases. Phase 1 is the foundation (schema versioning + replay) every later phase depends on. Phases 2 and 3 add learning convergence (vector dedup, effectiveness scoring, domain mining, causal probe). Phase 4 federates across repos. Phase 5 surfaces everything (MCP + dashboard). Each phase produces a working, tested system on its own and is independently revertable.

**Tech Stack:** Python 3.10+ stdlib for all core scripts (matches upstream policy of zero required deps). Optional deps gated behind import guards with graceful fallbacks: `sentence-transformers` (vector recall), `mcp` (MCP server), `fastapi`/`jinja2` (dashboard). Storage stays JSONL/JSON. Tests use stdlib `unittest` to match upstream.

---

## Architecture Overview

### Dependency graph

```
Phase 1 (schema + replay) ──┬─► Phase 2A (vector recall)
                            ├─► Phase 2B (gate effectiveness)
                            │       │
                            │       ├─► Phase 3B (causal probe)
                            │       └─► Phase 4   (cross-repo inheritance)
                            └─► Phase 3A (domain learner)

Phase 5A (MCP server)  ── reads from Phases 1–4
Phase 5B (dashboard)   ── reads from Phases 1–4
```

### Sequencing rationale

1. **Phase 1 first** because every later phase needs `schema_version`, `correlation_id`, and `gate_loaded_ids` in hook events. Retrofitting these is expensive.
2. **Phase 2 next** because (a) vector recall removes queue noise that obscures (b) effectiveness scoring, and effectiveness data feeds 3B and 4.
3. **Phase 3** runs parallel to Phase 4 once Phase 2 lands; both consume the same evidence base.
4. **Phase 5** is the surface layer — only meaningful after the underlying systems exist.

### Layout conventions (preserved from upstream)

- New executables go in `agent-learning-compounder/bin/<name>` (chmod +x, shebanged) with `bin/<name>.py` symlink and `scripts/<name>.py` symlink.
- New references go in `agent-learning-compounder/reference-lib/<name>` (no extension) with `references/<name>.md` symlink.
- New unit/integration tests in `agent-learning-compounder/fixtures/tests/test_<name>.py`.
- New eval fixtures in `agent-learning-compounder/fixtures/eval-fixtures/<name>.json`.

### Pre-flight: per-phase setup

Before starting any phase, run from `~/work/active/agent-learning-compounder/`:

```bash
cd agent-learning-compounder
python3 -m unittest discover -s fixtures/tests 2>&1 | tail -5
python3 -m unittest discover -s tests 2>&1 | tail -5
python3 scripts/run_pressure_tests.py 2>&1 | tail -5
```

Expected: all tests pass (105 fixture, 1 smoke, 4 pressure). If they don't, fix before adding new phases.

---

## Phase 1: Event Schema Versioning and Replay

**Goal:** Add `schema_version` to every hook event row and ship a replay tool that upgrades v1 rows on read. Adds two new fields (`correlation_id`, `gate_loaded_ids`) that Phases 2B, 3B, and 4 depend on.

**Files:**
- Modify: `agent-learning-compounder/bin/collect_hook_event` — write `schema_version: 2`, accept new fields
- Create: `agent-learning-compounder/bin/replay_hook_events`
- Create: `agent-learning-compounder/bin/replay_hook_events.py` (symlink → `replay_hook_events`)
- Create: `agent-learning-compounder/scripts/replay_hook_events.py` (symlink → `../bin/replay_hook_events`)
- Create: `agent-learning-compounder/reference-lib/event-schema-evolution`
- Create: `agent-learning-compounder/references/event-schema-evolution.md` (symlink → `../reference-lib/event-schema-evolution`)
- Test: `agent-learning-compounder/fixtures/tests/test_replay_hook_events.py`
- Test: `agent-learning-compounder/fixtures/tests/test_collect_hook_event_schema_v2.py`

### Task 1.1: Pin current behavior with a regression test

- [ ] **Step 1: Write a baseline test that locks the current event shape**

Create `agent-learning-compounder/fixtures/tests/test_collect_hook_event_schema_v2.py`:

```python
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECT = REPO_ROOT / "bin" / "collect_hook_event"


class CollectHookEventSchemaV2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name)
        self.log_path = self.state_dir / "hook-events.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _emit(self, payload):
        env = {**os.environ, "AGENT_LEARNING_STATE_DIR": str(self.state_dir)}
        proc = subprocess.run(
            [str(COLLECT), "--event-log", str(self.log_path)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]

    def test_event_has_schema_version_2(self):
        rows = self._emit({"event": "PreToolUse", "tool": "Bash"})
        self.assertEqual(rows[-1]["schema_version"], 2)

    def test_correlation_id_pass_through(self):
        rows = self._emit({"event": "PreToolUse", "tool": "Bash", "correlation_id": "abc-123"})
        self.assertEqual(rows[-1]["correlation_id"], "abc-123")

    def test_gate_loaded_ids_pass_through(self):
        rows = self._emit({
            "event": "InstructionsLoaded",
            "gate_loaded_ids": ["g_aa11", "g_bb22"],
        })
        self.assertEqual(rows[-1]["gate_loaded_ids"], ["g_aa11", "g_bb22"])

    def test_unknown_fields_dropped(self):
        rows = self._emit({"event": "PreToolUse", "random_field": "ignored"})
        self.assertNotIn("random_field", rows[-1])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it; expect failures**

Run: `python3 -m unittest fixtures.tests.test_collect_hook_event_schema_v2 -v` from `agent-learning-compounder/`.
Expected: 4 FAIL (no `schema_version` key; `correlation_id` and `gate_loaded_ids` dropped by current allowlist).

### Task 1.2: Extend the collector allowlist and add schema_version

- [ ] **Step 3: Locate the allowlist in `bin/collect_hook_event`**

Run: `grep -n "ALLOWED_FIELDS\|normalize_event\|allowlist" agent-learning-compounder/bin/collect_hook_event | head -20`

- [ ] **Step 4: Add three fields and stamp schema_version**

Edit `agent-learning-compounder/bin/collect_hook_event`. Locate the `ALLOWED_FIELDS` constant (or equivalent set inside `normalize_event`). Add `correlation_id`, `gate_loaded_ids`, `schema_version` to the allowlist set. In the function that constructs the persisted row, add `row["schema_version"] = 2` immediately before the JSONL write call. If `correlation_id` is absent in input, leave it absent in output (do not synthesize). `gate_loaded_ids` must be normalized to a list of strings or dropped.

Sketch:

```python
ALLOWED_FIELDS = {
    "ts", "event", "runtime", "repo", "skill", "tool", "outcome",
    "path", "command_class", "tags",
    "correlation_id", "gate_loaded_ids",     # new in v2
}

SCHEMA_VERSION = 2


def normalize_event(payload):
    out = {}
    for k, v in payload.items():
        if k not in ALLOWED_FIELDS:
            continue
        if k == "gate_loaded_ids":
            if not isinstance(v, list):
                continue
            v = [str(x) for x in v if isinstance(x, (str, int))][:64]
        if k == "correlation_id":
            if not isinstance(v, str) or len(v) > 128:
                continue
        out[k] = v
    out["schema_version"] = SCHEMA_VERSION
    return out
```

- [ ] **Step 5: Re-run; expect all four tests pass**

Run: `python3 -m unittest fixtures.tests.test_collect_hook_event_schema_v2 -v`
Expected: 4 PASS.

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3`
Expected: all tests pass (was 105, now 109).

- [ ] **Step 7: Commit**

```bash
git add agent-learning-compounder/bin/collect_hook_event \
        agent-learning-compounder/fixtures/tests/test_collect_hook_event_schema_v2.py
git commit -m "feat(hooks): v2 schema with schema_version, correlation_id, gate_loaded_ids"
```

### Task 1.3: Build the replay tool

- [ ] **Step 8: Write the replay test first**

Create `agent-learning-compounder/fixtures/tests/test_replay_hook_events.py`:

```python
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
REPLAY = REPO_ROOT / "bin" / "replay_hook_events"


class ReplayHookEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.input_path = Path(self.tmp.name) / "in.jsonl"
        self.output_path = Path(self.tmp.name) / "out.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rows):
        self.input_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    def _run(self, *args):
        proc = subprocess.run(
            [str(REPLAY), "--input", str(self.input_path), "--output", str(self.output_path), *args],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [json.loads(line) for line in self.output_path.read_text().splitlines() if line]

    def test_v1_row_upgrades_to_v2(self):
        self._write([{"ts": "2026-01-01T00:00:00Z", "event": "PreToolUse", "tool": "Bash"}])
        rows = self._run()
        self.assertEqual(rows[0]["schema_version"], 2)
        self.assertEqual(rows[0]["event"], "PreToolUse")

    def test_v2_row_passes_through(self):
        self._write([{
            "ts": "2026-01-01T00:00:00Z", "event": "PreToolUse",
            "tool": "Bash", "schema_version": 2, "correlation_id": "c1",
        }])
        rows = self._run()
        self.assertEqual(rows[0]["correlation_id"], "c1")
        self.assertEqual(len(rows), 1)

    def test_malformed_row_skipped_not_crashed(self):
        self.input_path.write_text(
            json.dumps({"event": "PreToolUse"}) + "\n"
            + "not-json\n"
            + json.dumps({"event": "PostToolUse"}) + "\n"
        )
        rows = self._run("--skip-malformed")
        self.assertEqual(len(rows), 2)

    def test_dry_run_writes_nothing(self):
        self._write([{"event": "PreToolUse"}])
        proc = subprocess.run(
            [str(REPLAY), "--input", str(self.input_path), "--output", str(self.output_path), "--dry-run"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(self.output_path.exists())
        self.assertIn("would_write_rows=1", proc.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 9: Run; expect failure (REPLAY does not exist yet)**

Run: `python3 -m unittest fixtures.tests.test_replay_hook_events -v`
Expected: 4 ERROR (binary not found).

- [ ] **Step 10: Create the replay executable**

Create `agent-learning-compounder/bin/replay_hook_events`:

```python
#!/usr/bin/env python3
"""Replay hook event JSONL, upgrading v1 rows to v2.

Reads --input JSONL, normalizes each row through the collector's allowlist,
stamps schema_version=2, writes to --output. Idempotent: v2 rows pass through.
"""
import argparse
import json
import os
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from collect_hook_event import normalize_event, SCHEMA_VERSION  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--skip-malformed", action="store_true",
                   help="Skip lines that fail JSON decode instead of erroring")
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would be written; do not write output")
    return p.parse_args()


def iter_rows(path: Path, skip_malformed: bool):
    with path.open() as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                if skip_malformed:
                    print(f"skip lineno={lineno}", file=sys.stderr)
                    continue
                raise


def main():
    args = parse_args()
    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 2

    upgraded = []
    for raw in iter_rows(args.input, args.skip_malformed):
        normalized = normalize_event(raw)
        upgraded.append(normalized)

    if args.dry_run:
        print(f"would_write_rows={len(upgraded)}")
        return 0

    fd = os.open(
        str(args.output),
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    with os.fdopen(fd, "w") as out:
        for row in upgraded:
            out.write(json.dumps(row, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 11: Make it executable and add the symlinks**

```bash
chmod +x agent-learning-compounder/bin/replay_hook_events
ln -s replay_hook_events agent-learning-compounder/bin/replay_hook_events.py
ln -s ../bin/replay_hook_events agent-learning-compounder/scripts/replay_hook_events.py
```

- [ ] **Step 12: Verify the symlinks**

Run: `ls -la agent-learning-compounder/bin/replay_hook_events* agent-learning-compounder/scripts/replay_hook_events.py`
Expected: `replay_hook_events` is executable; `.py` paths are symlinks pointing at the canonical files.

- [ ] **Step 13: Re-run the replay tests**

Run: `python3 -m unittest fixtures.tests.test_replay_hook_events -v`
Expected: 4 PASS.

- [ ] **Step 14: Run full suite**

Run: `python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3`
Expected: 113 tests pass.

- [ ] **Step 15: Commit**

```bash
git add agent-learning-compounder/bin/replay_hook_events* \
        agent-learning-compounder/scripts/replay_hook_events.py \
        agent-learning-compounder/fixtures/tests/test_replay_hook_events.py
git commit -m "feat(hooks): add replay_hook_events for cross-schema log migration"
```

### Task 1.4: Document the schema evolution policy

- [ ] **Step 16: Write the reference doc**

Create `agent-learning-compounder/reference-lib/event-schema-evolution`:

```markdown
# Hook Event Schema Evolution

The hook event JSONL log carries a `schema_version` integer on every row written
by `bin/collect_hook_event`. Older rows that predate this stamp are treated as
`schema_version: 1` on read.

## Versions

| Version | Added | Removed | Notes |
| --- | --- | --- | --- |
| 1 | (initial) | — | implicit; no stamp on disk |
| 2 | `schema_version`, `correlation_id`, `gate_loaded_ids` | — | introduced by Phase 1 of the eight-upgrade plan |

`correlation_id` ties events from a single agent session together for Phase 2B
gate effectiveness analysis. `gate_loaded_ids` records which approved gates the
session actually loaded into context.

## Replay

`bin/replay_hook_events` reads a JSONL log and re-emits it through the current
collector's `normalize_event`. Output is always at the latest schema version.

```bash
python3 scripts/replay_hook_events.py \
  --input  "<state>/repos/<repo-id>/hook-events.jsonl" \
  --output "<state>/repos/<repo-id>/hook-events.v2.jsonl"
```

`--skip-malformed` tolerates corrupted lines (logs notice on stderr).
`--dry-run` reports row count without writing.

## Policy

- Adding a field: bump schema version, list it in the table above, and
  guarantee readers can default-fill the absent field for older rows.
- Removing a field: bump schema version, list it in the Removed column, and
  document the migration in this file.
- Renaming a field: never. Add a new field, mark the old one removed at the
  next bump.
- Bounded fields only: every new field has a maximum size in bytes or items,
  enforced inside `normalize_event`. Hook logs are not blob storage.
```

- [ ] **Step 17: Add the references symlink**

```bash
ln -s ../reference-lib/event-schema-evolution agent-learning-compounder/references/event-schema-evolution.md
```

- [ ] **Step 18: Commit**

```bash
git add agent-learning-compounder/reference-lib/event-schema-evolution \
        agent-learning-compounder/references/event-schema-evolution.md
git commit -m "docs: event schema evolution policy and replay usage"
```

### Phase 1 acceptance

```bash
python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3
python3 -m unittest discover -s tests 2>&1 | tail -3
python3 scripts/run_pressure_tests.py 2>&1 | tail -3
```

Expected: 113 fixture tests, 1 smoke test, 4 pressure scenarios all pass.

---

## Phase 2: Convergent Learning (Vector Recall + Gate Effectiveness)

### Phase 2A: Vector Recall over the Improvement Queue (Upgrade 1)

**Goal:** Replace string-match dedup in `improvement-queue.jsonl` with optional embedding-based semantic dedup so the queue stops accumulating semantically identical proposals.

**Design:** Two-backend strategy. Default backend uses character-trigram Jaccard (no deps). Optional embedding backend uses `sentence-transformers` if installed; falls back to trigrams with a stderr notice if import fails. Threshold defaults: trigram Jaccard ≥ 0.80, cosine ≥ 0.85. Both are configurable.

**Files:**
- Create: `agent-learning-compounder/bin/queue_dedup` (+ symlinks)
- Create: `agent-learning-compounder/reference-lib/queue-dedup` (+ symlink)
- Modify: `agent-learning-compounder/bin/refresh_learning_state` — call queue_dedup after each refresh
- Test: `agent-learning-compounder/fixtures/tests/test_queue_dedup.py`

### Task 2A.1: Trigram similarity baseline

- [ ] **Step 1: Write tests for the trigram backend**

Create `agent-learning-compounder/fixtures/tests/test_queue_dedup.py`:

```python
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEDUP = REPO_ROOT / "bin" / "queue_dedup"


class QueueDedup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = Path(self.tmp.name) / "improvement-queue.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rows):
        self.queue.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    def _run(self, *args):
        proc = subprocess.run(
            [str(DEDUP), "--queue", str(self.queue), "--backend", "trigram",
             "--threshold", "0.80", *args],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return [json.loads(line) for line in self.queue.read_text().splitlines() if line]

    def test_dedups_near_identical_text(self):
        self._write([
            {"id": "a", "text": "Re-read AGENTS.md before changing the repo."},
            {"id": "b", "text": "Re-read AGENTS.md before modifying the repo."},
        ])
        rows = self._run()
        ids = {r["id"] for r in rows}
        self.assertEqual(len(rows), 1)
        self.assertIn(next(iter(ids)), {"a", "b"})

    def test_keeps_semantically_distinct(self):
        self._write([
            {"id": "a", "text": "Re-read AGENTS.md before changing the repo."},
            {"id": "b", "text": "Run pytest with -x before pushing."},
        ])
        rows = self._run()
        self.assertEqual(len(rows), 2)

    def test_preserves_oldest_id_on_dedup(self):
        self._write([
            {"id": "older", "text": "Always quote one line of deploy output.",
             "ts": "2026-01-01T00:00:00Z"},
            {"id": "newer", "text": "Always quote a line of deploy output.",
             "ts": "2026-02-01T00:00:00Z"},
        ])
        rows = self._run("--keep", "oldest")
        self.assertEqual(rows[0]["id"], "older")

    def test_dry_run_does_not_modify_queue(self):
        original = [
            {"id": "a", "text": "Re-read AGENTS.md before changing the repo."},
            {"id": "b", "text": "Re-read AGENTS.md before modifying the repo."},
        ]
        self._write(original)
        proc = subprocess.run(
            [str(DEDUP), "--queue", str(self.queue), "--backend", "trigram",
             "--threshold", "0.80", "--dry-run"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        on_disk = [json.loads(line) for line in self.queue.read_text().splitlines() if line]
        self.assertEqual(on_disk, original)
        self.assertIn("would_remove=1", proc.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run; expect 4 ERROR (binary missing)**

Run: `python3 -m unittest fixtures.tests.test_queue_dedup -v`

- [ ] **Step 3: Create the dedup executable**

Create `agent-learning-compounder/bin/queue_dedup`:

```python
#!/usr/bin/env python3
"""Semantically dedup the improvement-queue.jsonl using trigrams or embeddings.

Default backend: character-trigram Jaccard (stdlib only).
Optional backend: sentence-transformers (gracefully falls back if missing).
"""
import argparse
import fcntl
import json
import sys
from pathlib import Path


def trigrams(text: str) -> set:
    text = text.lower()
    return {text[i:i + 3] for i in range(len(text) - 2)} if len(text) >= 3 else {text}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def embed_backend(texts):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("queue_dedup: sentence-transformers not installed; falling back to trigram",
              file=sys.stderr)
        return None
    model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    return model.encode(texts, normalize_embeddings=True)


def cosine(u, v) -> float:
    return float(sum(a * b for a, b in zip(u, v)))


def find_duplicates(rows, backend, threshold):
    texts = [r.get("text", "") for r in rows]
    if backend == "embed":
        vectors = embed_backend(texts)
        if vectors is None:
            backend = "trigram"

    if backend == "trigram":
        sigs = [trigrams(t) for t in texts]
        sim = lambda i, j: jaccard(sigs[i], sigs[j])
    else:
        sim = lambda i, j: cosine(vectors[i], vectors[j])

    keep_idx = list(range(len(rows)))
    drop = set()
    for i in range(len(rows)):
        if i in drop:
            continue
        for j in range(i + 1, len(rows)):
            if j in drop:
                continue
            if sim(i, j) >= threshold:
                drop.add(j)
    return drop


def order_by_keep(rows, keep):
    if keep == "oldest":
        return sorted(range(len(rows)), key=lambda i: rows[i].get("ts", ""))
    return sorted(range(len(rows)), key=lambda i: rows[i].get("ts", ""), reverse=True)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--queue", required=True, type=Path)
    p.add_argument("--backend", choices=["trigram", "embed"], default="trigram")
    p.add_argument("--threshold", type=float, default=0.80)
    p.add_argument("--keep", choices=["oldest", "newest"], default="oldest")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    if not args.queue.exists():
        print(f"queue not found: {args.queue}", file=sys.stderr)
        return 2

    with args.queue.open("r+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        lines = [ln for ln in fh.read().splitlines() if ln]
        rows = [json.loads(ln) for ln in lines]
        if not rows:
            return 0

        priority = order_by_keep(rows, args.keep)
        reordered = [rows[i] for i in priority]
        drop = find_duplicates(reordered, args.backend, args.threshold)
        kept = [r for i, r in enumerate(reordered) if i not in drop]

        if args.dry_run:
            print(f"would_remove={len(drop)} kept={len(kept)} backend={args.backend}")
            return 0

        fh.seek(0)
        fh.truncate()
        for r in kept:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Add executable bit and symlinks**

```bash
chmod +x agent-learning-compounder/bin/queue_dedup
ln -s queue_dedup agent-learning-compounder/bin/queue_dedup.py
ln -s ../bin/queue_dedup agent-learning-compounder/scripts/queue_dedup.py
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m unittest fixtures.tests.test_queue_dedup -v`
Expected: 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add agent-learning-compounder/bin/queue_dedup* \
        agent-learning-compounder/scripts/queue_dedup.py \
        agent-learning-compounder/fixtures/tests/test_queue_dedup.py
git commit -m "feat(queue): semantic dedup with trigram+embedding backends"
```

### Task 2A.2: Wire dedup into refresh_learning_state

- [ ] **Step 7: Add an integration test**

Append to `agent-learning-compounder/fixtures/tests/test_queue_dedup.py`:

```python
class RefreshWiresDedup(unittest.TestCase):
    """refresh_learning_state should invoke queue_dedup after appending candidates."""

    def test_refresh_emits_dedup_count(self):
        # Stand up a fake repo state, seed two near-duplicate queue rows,
        # run refresh with --no-baseline --no-baseline-map (refresh-only mode),
        # assert stderr or result dict reports dedup_removed >= 1.
        # Full setup deferred to integration scaffold in fixtures/eval-fixtures/
        # mini-repo/. Mark xfail until scaffold lands in Step 9.
        self.skipTest("integration scaffold pending step 9")
```

- [ ] **Step 8: Read current refresh logic**

Run: `grep -n "queue_candidate_adjustments\|improvement-queue" agent-learning-compounder/bin/refresh_learning_state`

- [ ] **Step 9: Edit refresh_learning_state to call queue_dedup**

Inside `agent-learning-compounder/bin/refresh_learning_state`, locate the post-append section of `queue_candidate_adjustments` (where it returns its result dict). After the appends succeed, call the dedup module in-process:

```python
# Insert near the bottom of queue_candidate_adjustments, after the append block:
from queue_dedup import find_duplicates, order_by_keep  # add at module top

def _post_dedup(queue_path, backend="trigram", threshold=0.80):
    lines = [ln for ln in queue_path.read_text().splitlines() if ln]
    rows = [json.loads(ln) for ln in lines]
    if len(rows) < 2:
        return 0
    priority = order_by_keep(rows, "oldest")
    reordered = [rows[i] for i in priority]
    drop = find_duplicates(reordered, backend, threshold)
    if not drop:
        return 0
    kept = [r for i, r in enumerate(reordered) if i not in drop]
    tmp = queue_path.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(json.dumps(r, sort_keys=True) for r in kept) + "\n")
    tmp.replace(queue_path)
    return len(drop)

# Then in queue_candidate_adjustments, after the existing append+result_dict:
result["dedup_removed"] = _post_dedup(queue_path)
```

- [ ] **Step 10: Build the mini-repo scaffold and unskip the test**

Create `agent-learning-compounder/fixtures/eval-fixtures/mini-repo/README.md`:

```markdown
# mini-repo: integration fixture

Used by integration tests that need a small but valid repo with a working
agent-learning state. Tests stage this directory into a TemporaryDirectory
before invoking scripts.

Contents:
- empty repo with a single Python file
- pre-populated `.agent-learning/repos/<repo-id>/improvement-queue.jsonl`
  with two near-duplicate entries (for dedup tests)
- minimal `config.json`, `baseline.json`, `domain-rules.active.json`,
  `skill-map.json`
```

Then replace the skipped test with a real one that copies this scaffold into a tmpdir, runs `refresh_learning_state.py --refresh-only`, and asserts `dedup_removed >= 1` in stderr.

Concrete test body:

```python
import shutil

class RefreshWiresDedup(unittest.TestCase):
    def test_refresh_emits_dedup_count(self):
        src = REPO_ROOT / "fixtures" / "eval-fixtures" / "mini-repo"
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            shutil.copytree(src, repo)
            proc = subprocess.run(
                [str(REPO_ROOT / "bin" / "refresh_learning_state"),
                 "--repo", str(repo),
                 "--state-dir", str(repo / ".agent-learning"),
                 "--refresh-only"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("dedup_removed", proc.stdout + proc.stderr)
```

- [ ] **Step 11: Populate the mini-repo fixture files**

Build `agent-learning-compounder/fixtures/eval-fixtures/mini-repo/` with:
- `pyproject.toml` minimal stub (`[project]\nname = "mini-repo"\nversion = "0.0.0"\n`)
- `src/__init__.py` empty
- `.agent-learning/repos/<deterministic-id>/improvement-queue.jsonl` with the two near-duplicate rows seen in Step 1's test fixtures
- `.agent-learning/repos/<deterministic-id>/config.json` with `{"state_version": 1, "runtime": "codex"}`
- `.agent-learning/repos/<deterministic-id>/baseline.json` `{}`
- `.agent-learning/repos/<deterministic-id>/domain-rules.active.json` (copy from `domain-rules/generic.json`)
- `.agent-learning/repos/<deterministic-id>/skill-map.json` `{"repo": "<placeholder>", "skills": [], "duplicates": [], "invalid": [], "missing_dependencies": []}`

The exact `<deterministic-id>` must match what `bin/state_paths` computes for the mini-repo path. Compute once with `python3 -c "from state_paths import repo_id; print(repo_id('<absolute-path-to-mini-repo>'))"` and bake the result into the scaffold path. Document the bake step in the README.

- [ ] **Step 12: Run the integration test**

Run: `python3 -m unittest fixtures.tests.test_queue_dedup.RefreshWiresDedup -v`
Expected: PASS.

- [ ] **Step 13: Run the full suite**

Run: `python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3`
Expected: 118 tests pass.

- [ ] **Step 14: Commit**

```bash
git add agent-learning-compounder/bin/refresh_learning_state \
        agent-learning-compounder/fixtures/eval-fixtures/mini-repo \
        agent-learning-compounder/fixtures/tests/test_queue_dedup.py
git commit -m "feat(refresh): post-append queue dedup with in-process call"
```

### Task 2A.3: Document dedup behavior

- [ ] **Step 15: Write the reference**

Create `agent-learning-compounder/reference-lib/queue-dedup`:

```markdown
# Improvement Queue Dedup

The improvement queue accumulates candidate gate adjustments for operator review.
Without semantic dedup the same suggestion appears multiple times whenever its
wording shifts. `scripts/queue_dedup.py` collapses near-duplicates.

## Backends

- `trigram` (default, stdlib-only): character-trigram Jaccard over the `text`
  field. Threshold defaults to 0.80.
- `embed`: `sentence-transformers` (BAAI/bge-small-en-v1.5) with cosine
  similarity. Threshold defaults to 0.85. Falls back to trigram with a stderr
  notice if the dependency is missing.

## Invocation

```bash
python3 scripts/queue_dedup.py \
  --queue "<state>/repos/<repo-id>/improvement-queue.jsonl" \
  --backend trigram \
  --threshold 0.80 \
  --keep oldest
```

`--keep oldest` preserves the earliest `ts` row in each cluster (default).
`--keep newest` flips this.

`refresh_learning_state.py` invokes dedup after appending new candidates;
operators rarely run `queue_dedup` directly.

## Tuning

Trigram threshold 0.70 is aggressive; 0.85 conservative. Start at 0.80.
Embedding threshold 0.85 with bge-small-en is comparable. Sample the diff
before lowering thresholds — overly aggressive dedup hides distinct gates.
```

Symlink and commit:

```bash
ln -s ../reference-lib/queue-dedup agent-learning-compounder/references/queue-dedup.md
git add agent-learning-compounder/reference-lib/queue-dedup \
        agent-learning-compounder/references/queue-dedup.md
git commit -m "docs: improvement-queue dedup tuning guide"
```

### Phase 2A acceptance

```bash
python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3
```

Expected: 118 tests pass.

---

### Phase 2B: Gate Effectiveness Scoring (Upgrade 2)

**Goal:** Compute per-gate counterfactual evidence — how often loading a gate correlates with cleaner session outcomes — and surface low-impact gates as retirement candidates.

**Design:** Stable `gate_id = sha256(domain|category|gate)[:12]` stamped at export. `gate_loaded_ids` (Phase 1 field) records which gates a session loaded. Outcomes derive from `SessionEnd` event (`outcome: clean|correction|error`). Per gate, compute correction rate when loaded vs absent; minimum N=10 sessions per cohort before reporting.

**Files:**
- Modify: `agent-learning-compounder/bin/export_gates` — stamp `gate_id` on every gate
- Create: `agent-learning-compounder/bin/evaluate_gate_effectiveness` (+ symlinks)
- Create: `agent-learning-compounder/reference-lib/gate-effectiveness` (+ symlink)
- Modify: `agent-learning-compounder/bin/refresh_learning_state` — call effectiveness eval, append low-impact retirement proposals
- Test: `fixtures/tests/test_export_gates_id.py`
- Test: `fixtures/tests/test_evaluate_gate_effectiveness.py`
- Eval fixture: `fixtures/eval-fixtures/gate_effectiveness_events.jsonl`

### Task 2B.1: Stamp stable gate_ids on export

- [ ] **Step 1: Write the test**

Create `agent-learning-compounder/fixtures/tests/test_export_gates_id.py`:

```python
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORT_GATES = REPO_ROOT / "bin" / "export_gates"

SAMPLE_REPORT = """
# Agent Learning Report

## agent_compensation

### domain: cloudflare

- **level:** 3
- **gates:**
  - category: docs-check
    gate: Re-read current Cloudflare docs before changing wrangler config.
  - category: live-check
    gate: Run deploy verification and quote one non-secret line.
"""


class ExportGatesId(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.report = Path(self.tmp.name) / "report.md"
        self.report.write_text(SAMPLE_REPORT)
        self.output = Path(self.tmp.name) / "gates.md"

    def tearDown(self):
        self.tmp.cleanup()

    def test_each_gate_has_stable_id(self):
        subprocess.run(
            [str(EXPORT_GATES), "--report", str(self.report), "--output", str(self.output)],
            check=True,
        )
        text = self.output.read_text()
        ids = re.findall(r"gate_id:\s*([a-f0-9]{12})", text)
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)

    def test_ids_are_deterministic_across_runs(self):
        subprocess.run(
            [str(EXPORT_GATES), "--report", str(self.report), "--output", str(self.output)],
            check=True,
        )
        first = self.output.read_text()
        subprocess.run(
            [str(EXPORT_GATES), "--report", str(self.report), "--output", str(self.output)],
            check=True,
        )
        second = self.output.read_text()
        # Strip the generated_at timestamp to compare body-only.
        strip = lambda s: re.sub(r"generated_at:[^\n]+", "", s)
        self.assertEqual(strip(first), strip(second))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run; expect 2 FAIL**

Run: `python3 -m unittest fixtures.tests.test_export_gates_id -v`

- [ ] **Step 3: Modify export_gates to stamp gate_id**

In `agent-learning-compounder/bin/export_gates`, locate the function that writes each gate block. Add a helper:

```python
import hashlib

def _gate_id(domain: str, category: str, gate_text: str) -> str:
    h = hashlib.sha256()
    h.update(f"{domain}|{category}|{gate_text.strip()}".encode("utf-8"))
    return h.hexdigest()[:12]
```

In the per-gate emission code, before writing the category line, emit:

```python
out.write(f"  - gate_id: {_gate_id(domain, category, gate_text)}\n")
```

- [ ] **Step 4: Run the export tests**

Run: `python3 -m unittest fixtures.tests.test_export_gates_id -v`
Expected: 2 PASS.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3`
Expected: all tests pass. If `test_export_gates.py` (any pre-existing test) fails due to format change, update its snapshot — gate_id is now a required field in the canonical output.

- [ ] **Step 6: Commit**

```bash
git add agent-learning-compounder/bin/export_gates \
        agent-learning-compounder/fixtures/tests/test_export_gates_id.py
git commit -m "feat(gates): stable 12-char gate_id stamped on every exported gate"
```

### Task 2B.2: Build evaluate_gate_effectiveness

- [ ] **Step 7: Build the eval fixture**

Create `agent-learning-compounder/fixtures/eval-fixtures/gate_effectiveness_events.jsonl`:

```jsonl
{"schema_version":2,"ts":"2026-01-01T00:00:00Z","event":"InstructionsLoaded","correlation_id":"s1","gate_loaded_ids":["g_aaa111","g_bbb222"]}
{"schema_version":2,"ts":"2026-01-01T01:00:00Z","event":"SessionEnd","correlation_id":"s1","outcome":"clean"}
{"schema_version":2,"ts":"2026-01-02T00:00:00Z","event":"InstructionsLoaded","correlation_id":"s2","gate_loaded_ids":["g_aaa111"]}
{"schema_version":2,"ts":"2026-01-02T01:00:00Z","event":"SessionEnd","correlation_id":"s2","outcome":"clean"}
{"schema_version":2,"ts":"2026-01-03T00:00:00Z","event":"InstructionsLoaded","correlation_id":"s3","gate_loaded_ids":["g_aaa111"]}
{"schema_version":2,"ts":"2026-01-03T01:00:00Z","event":"SessionEnd","correlation_id":"s3","outcome":"correction"}
{"schema_version":2,"ts":"2026-01-04T00:00:00Z","event":"InstructionsLoaded","correlation_id":"s4","gate_loaded_ids":["g_bbb222"]}
{"schema_version":2,"ts":"2026-01-04T01:00:00Z","event":"SessionEnd","correlation_id":"s4","outcome":"correction"}
{"schema_version":2,"ts":"2026-01-05T00:00:00Z","event":"InstructionsLoaded","correlation_id":"s5","gate_loaded_ids":[]}
{"schema_version":2,"ts":"2026-01-05T01:00:00Z","event":"SessionEnd","correlation_id":"s5","outcome":"correction"}
```

Add 10 more rows so each gate cohort hits N≥10 — half clean, half correction for `g_aaa111`; mostly correction for `g_bbb222`; absent cohort mostly correction. Final fixture must produce: `g_aaa111` correlated_with_success (delta ≥ +0.20), `g_bbb222` correlated_with_failure (delta ≤ −0.10) or `needs_review` if N too small.

- [ ] **Step 8: Write the eval test**

Create `agent-learning-compounder/fixtures/tests/test_evaluate_gate_effectiveness.py`:

```python
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL = REPO_ROOT / "bin" / "evaluate_gate_effectiveness"
FIXTURE = REPO_ROOT / "fixtures" / "eval-fixtures" / "gate_effectiveness_events.jsonl"


class EvaluateGateEffectiveness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output = Path(self.tmp.name) / "effectiveness.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        proc = subprocess.run(
            [str(EVAL), "--events", str(FIXTURE), "--output", str(self.output), *args],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(self.output.read_text())

    def test_emits_one_row_per_seen_gate(self):
        result = self._run()
        gate_ids = {row["gate_id"] for row in result["gates"]}
        self.assertIn("g_aaa111", gate_ids)
        self.assertIn("g_bbb222", gate_ids)

    def test_labels_strong_signal_for_high_delta(self):
        result = self._run()
        row = next(r for r in result["gates"] if r["gate_id"] == "g_aaa111")
        self.assertIn(row["label"], {"correlated_with_success", "needs_review"})
        if row["label"] == "correlated_with_success":
            self.assertGreaterEqual(row["delta"], 0.20)

    def test_min_n_gates_needs_review(self):
        # Single-session fixture inline
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write(json.dumps({
                "schema_version": 2, "event": "InstructionsLoaded",
                "correlation_id": "x1", "gate_loaded_ids": ["g_solo"]
            }) + "\n")
            fh.write(json.dumps({
                "schema_version": 2, "event": "SessionEnd",
                "correlation_id": "x1", "outcome": "clean"
            }) + "\n")
            path = fh.name
        proc = subprocess.run(
            [str(EVAL), "--events", path, "--output", str(self.output), "--min-n", "10"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(self.output.read_text())
        row = next((r for r in result["gates"] if r["gate_id"] == "g_solo"), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["label"], "needs_review")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 9: Run; expect failures**

Run: `python3 -m unittest fixtures.tests.test_evaluate_gate_effectiveness -v`
Expected: ERROR (binary missing).

- [ ] **Step 10: Build the evaluator**

Create `agent-learning-compounder/bin/evaluate_gate_effectiveness`:

```python
#!/usr/bin/env python3
"""Compute correlation-only effectiveness signals per gate_id.

Reads hook events JSONL. Pairs InstructionsLoaded with SessionEnd via
correlation_id. For each gate_id, computes correction_rate among sessions
that loaded the gate (cohort A) and among sessions that did not (cohort B).
delta = correction_rate(B) - correction_rate(A); positive delta means
loading the gate correlates with fewer corrections.

Never reports causality. Below --min-n in either cohort, label is
needs_review.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_sessions(events_path: Path):
    """Returns dict cid -> {"gates": set[str], "outcome": str|None}."""
    sessions = defaultdict(lambda: {"gates": set(), "outcome": None})
    with events_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cid = row.get("correlation_id")
            if not cid:
                continue
            evt = row.get("event")
            if evt == "InstructionsLoaded":
                for gid in row.get("gate_loaded_ids", []) or []:
                    sessions[cid]["gates"].add(gid)
            elif evt == "SessionEnd":
                sessions[cid]["outcome"] = row.get("outcome")
    return dict(sessions)


def evaluate(sessions, min_n=10):
    """For each gate_id, compute cohort stats."""
    all_gate_ids = set()
    for s in sessions.values():
        all_gate_ids.update(s["gates"])

    rows = []
    for gid in sorted(all_gate_ids):
        loaded_outcomes = [s["outcome"] for s in sessions.values()
                           if gid in s["gates"] and s["outcome"]]
        absent_outcomes = [s["outcome"] for s in sessions.values()
                           if gid not in s["gates"] and s["outcome"]]

        def rate(outs):
            if not outs:
                return None
            return sum(1 for o in outs if o == "correction") / len(outs)

        a, b = rate(loaded_outcomes), rate(absent_outcomes)
        n_loaded, n_absent = len(loaded_outcomes), len(absent_outcomes)

        if n_loaded < min_n or n_absent < min_n or a is None or b is None:
            label = "needs_review"
            delta = None
        else:
            delta = b - a
            if delta >= 0.20:
                label = "correlated_with_success"
            elif delta <= -0.10:
                label = "correlated_with_failure"
            else:
                label = "no_signal"

        rows.append({
            "gate_id": gid,
            "n_loaded": n_loaded,
            "n_absent": n_absent,
            "correction_rate_loaded": a,
            "correction_rate_absent": b,
            "delta": delta,
            "label": label,
        })
    return {"gates": rows}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--events", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--min-n", type=int, default=10)
    return p.parse_args()


def main():
    args = parse_args()
    if not args.events.exists():
        print(f"events not found: {args.events}", file=sys.stderr)
        return 2
    sessions = load_sessions(args.events)
    result = evaluate(sessions, min_n=args.min_n)
    args.output.write_text(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 11: Add executable bit + symlinks**

```bash
chmod +x agent-learning-compounder/bin/evaluate_gate_effectiveness
ln -s evaluate_gate_effectiveness agent-learning-compounder/bin/evaluate_gate_effectiveness.py
ln -s ../bin/evaluate_gate_effectiveness agent-learning-compounder/scripts/evaluate_gate_effectiveness.py
```

- [ ] **Step 12: Run tests**

Run: `python3 -m unittest fixtures.tests.test_evaluate_gate_effectiveness -v`
Expected: 3 PASS.

- [ ] **Step 13: Commit**

```bash
git add agent-learning-compounder/bin/evaluate_gate_effectiveness* \
        agent-learning-compounder/scripts/evaluate_gate_effectiveness.py \
        agent-learning-compounder/fixtures/tests/test_evaluate_gate_effectiveness.py \
        agent-learning-compounder/fixtures/eval-fixtures/gate_effectiveness_events.jsonl
git commit -m "feat(gates): per-gate effectiveness scoring with min-N gating"
```

### Task 2B.3: Surface low-impact gates as retirement candidates

- [ ] **Step 14: Extend refresh_learning_state**

In `agent-learning-compounder/bin/refresh_learning_state`, after the effectiveness evaluator runs, append rows to `improvement-queue.jsonl` for any gate labeled `correlated_with_failure` or `no_signal` with `n_loaded >= 20`. The row shape:

```python
{
    "id": f"retire-{gate_id}-{int(time.time())}",
    "kind": "gate_retirement_candidate",
    "text": f"Retire low-impact gate {gate_id}: delta={delta:.2f} after n={n_loaded} loads.",
    "gate_id": gate_id,
    "evidence": {"n_loaded": n_loaded, "n_absent": n_absent, "delta": delta, "label": label},
    "ts": iso_now(),
}
```

The append goes through the same `fcntl.LOCK_EX` block already used in `queue_candidate_adjustments`.

- [ ] **Step 15: Add an integration test using mini-repo + extended fixture**

Extend `fixtures/eval-fixtures/mini-repo/.agent-learning/repos/<id>/hook-events.jsonl` with the gate_effectiveness fixture rows. Then in `test_evaluate_gate_effectiveness.py` add:

```python
class RefreshSurfacesRetirementCandidate(unittest.TestCase):
    def test_refresh_appends_retirement_when_gate_has_no_signal(self):
        src = REPO_ROOT / "fixtures" / "eval-fixtures" / "mini-repo"
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            shutil.copytree(src, repo)
            subprocess.run(
                [str(REPO_ROOT / "bin" / "refresh_learning_state"),
                 "--repo", str(repo),
                 "--state-dir", str(repo / ".agent-learning"),
                 "--refresh-only"],
                check=True,
            )
            queue = next((repo / ".agent-learning" / "repos").rglob("improvement-queue.jsonl"))
            rows = [json.loads(ln) for ln in queue.read_text().splitlines() if ln]
            kinds = {r.get("kind") for r in rows}
            self.assertIn("gate_retirement_candidate", kinds)
```

- [ ] **Step 16: Run integration test**

Run: `python3 -m unittest fixtures.tests.test_evaluate_gate_effectiveness -v`
Expected: PASS.

- [ ] **Step 17: Run full suite**

Run: `python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3`

- [ ] **Step 18: Commit**

```bash
git add agent-learning-compounder/bin/refresh_learning_state \
        agent-learning-compounder/fixtures/tests/test_evaluate_gate_effectiveness.py \
        agent-learning-compounder/fixtures/eval-fixtures/mini-repo
git commit -m "feat(refresh): surface low-impact gates as retirement candidates"
```

### Task 2B.4: Reference doc

- [ ] **Step 19: Write `reference-lib/gate-effectiveness`**

```markdown
# Gate Effectiveness

`bin/evaluate_gate_effectiveness` computes correlation-only signals per
`gate_id` from `hook-events.jsonl` (schema version 2 or later).

## Signals

| Label | Condition |
| --- | --- |
| `correlated_with_success` | delta ≥ 0.20, n_loaded ≥ min-N, n_absent ≥ min-N |
| `correlated_with_failure` | delta ≤ -0.10 |
| `no_signal` | -0.10 < delta < 0.20 |
| `needs_review` | either cohort below min-N |

`delta = correction_rate(absent) - correction_rate(loaded)`. Positive delta
means loading the gate correlates with fewer corrections.

## Default thresholds

| Knob | Default | Rationale |
| --- | --- | --- |
| `--min-n` | 10 | Sessions per cohort before signal is reportable. |
| success delta | 0.20 | Anything weaker is plausibly noise at small N. |
| failure delta | -0.10 | Surfaces drag earlier; retirement still requires operator approval. |

## What this is not

- Not causal. Loaded gates run alongside many other inputs.
- Not a global capability claim. Only per-gate, per-cohort.
- Not an auto-retirement signal. Low-impact gates are appended to
  `improvement-queue.jsonl` for review.
```

Symlink and commit:

```bash
ln -s ../reference-lib/gate-effectiveness agent-learning-compounder/references/gate-effectiveness.md
git add agent-learning-compounder/reference-lib/gate-effectiveness \
        agent-learning-compounder/references/gate-effectiveness.md
git commit -m "docs: gate effectiveness scoring methodology and thresholds"
```

### Phase 2 acceptance

```bash
python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3
python3 -m unittest discover -s tests 2>&1 | tail -3
python3 scripts/run_pressure_tests.py 2>&1 | tail -3
```

Expected: all tests pass; gates have `gate_id` field; low-impact retirements appear in queue when fixture loaded.

---

## Phase 3: Learning Expansion (Domain Mining + Causal Probe)

### Phase 3A: Domain-Rules Learner (Upgrade 5)

**Goal:** Mine the corpus for n-gram clusters that co-occur with session corrections; propose new domain seeds to the operator via the improvement queue.

**Design:** Stop-word-filtered bigram + trigram counting over correction-tagged session chunks. Score = (TF in correction chunks) / (TF in clean chunks + 1). Top-K with score ≥ threshold become candidate domain seeds, queued for operator approval. `--apply-domain-rule <queue-id>` writes the approved seed into `domain-rules.active.json`.

**Files:**
- Create: `agent-learning-compounder/bin/propose_domain_rules` (+ symlinks)
- Create: `agent-learning-compounder/reference-lib/domain-rules-learning` (+ symlink)
- Modify: `agent-learning-compounder/bin/refresh_learning_state` — call proposer
- Test: `agent-learning-compounder/fixtures/tests/test_propose_domain_rules.py`

### Task 3A.1: Build the proposer

- [ ] **Step 1: Test stub**

Create `agent-learning-compounder/fixtures/tests/test_propose_domain_rules.py`:

```python
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROPOSE = REPO_ROOT / "bin" / "propose_domain_rules"


class ProposeDomainRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.corpus = Path(self.tmp.name) / "corpus.txt"
        self.output = Path(self.tmp.name) / "proposals.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_high_score_term_appears_in_proposals(self):
        self.corpus.write_text(
            "[session=s1 outcome=correction] hyperdrive connection timed out hyperdrive\n"
            "[session=s2 outcome=correction] hyperdrive failed hyperdrive\n"
            "[session=s3 outcome=correction] hyperdrive query hung\n"
            "[session=s4 outcome=clean] normal request to api\n"
            "[session=s5 outcome=clean] frontend build green\n"
        )
        subprocess.run(
            [str(PROPOSE), "--corpus", str(self.corpus), "--output", str(self.output),
             "--top-k", "5", "--min-score", "2.0"],
            check=True,
        )
        result = json.loads(self.output.read_text())
        terms = [p["term"] for p in result["proposals"]]
        self.assertIn("hyperdrive", terms)

    def test_drops_stop_words(self):
        self.corpus.write_text(
            "[session=s1 outcome=correction] the the the the the the the the\n"
            "[session=s2 outcome=clean] other content\n"
        )
        subprocess.run(
            [str(PROPOSE), "--corpus", str(self.corpus), "--output", str(self.output),
             "--top-k", "5", "--min-score", "1.0"],
            check=True,
        )
        terms = [p["term"] for p in json.loads(self.output.read_text())["proposals"]]
        self.assertNotIn("the", terms)
```

- [ ] **Step 2: Implement**

Create `agent-learning-compounder/bin/propose_domain_rules`:

```python
#!/usr/bin/env python3
"""Mine corpus chunks for n-gram terms that co-occur with corrections.

Corpus format: one line per chunk, leading "[session=<id> outcome=<state>]"
header followed by chunk text. <state> is `correction` or `clean`.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
    "be", "to", "of", "in", "on", "for", "at", "by", "from", "with",
    "this", "that", "these", "those", "it", "as", "if", "then", "than",
    "into", "out", "up", "down", "over", "under", "you", "we", "they",
}

HEADER_RE = re.compile(r"^\[session=(\S+)\s+outcome=(\w+)\]\s*(.*)$")
TOKEN_RE = re.compile(r"[a-z][a-z0-9_-]{2,}")


def parse_chunks(corpus_path: Path):
    for line in corpus_path.read_text().splitlines():
        m = HEADER_RE.match(line)
        if not m:
            continue
        yield m.group(2), m.group(3).lower()


def tokens(text):
    return [t for t in TOKEN_RE.findall(text) if t not in STOP_WORDS]


def ngrams(toks, n):
    return [" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)]


def score_terms(chunks, n_min=1, n_max=2):
    correction = Counter()
    clean = Counter()
    for outcome, text in chunks:
        toks = tokens(text)
        for n in range(n_min, n_max + 1):
            grams = ngrams(toks, n)
            if outcome == "correction":
                correction.update(grams)
            elif outcome == "clean":
                clean.update(grams)
    scores = []
    for term, c in correction.items():
        score = c / (clean.get(term, 0) + 1)
        scores.append((term, c, clean.get(term, 0), score))
    return scores


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--min-score", type=float, default=2.0)
    return p.parse_args()


def main():
    args = parse_args()
    if not args.corpus.exists():
        print(f"corpus not found: {args.corpus}", file=sys.stderr)
        return 2
    chunks = list(parse_chunks(args.corpus))
    scores = score_terms(chunks)
    scores = [s for s in scores if s[3] >= args.min_score]
    scores.sort(key=lambda x: x[3], reverse=True)
    scores = scores[:args.top_k]
    args.output.write_text(json.dumps({
        "proposals": [
            {"term": term, "correction_count": cc, "clean_count": cl, "score": sc}
            for term, cc, cl, sc in scores
        ]
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: chmod + symlinks**

```bash
chmod +x agent-learning-compounder/bin/propose_domain_rules
ln -s propose_domain_rules agent-learning-compounder/bin/propose_domain_rules.py
ln -s ../bin/propose_domain_rules agent-learning-compounder/scripts/propose_domain_rules.py
```

- [ ] **Step 4: Run tests; commit**

```bash
python3 -m unittest fixtures.tests.test_propose_domain_rules -v
git add agent-learning-compounder/bin/propose_domain_rules* \
        agent-learning-compounder/scripts/propose_domain_rules.py \
        agent-learning-compounder/fixtures/tests/test_propose_domain_rules.py
git commit -m "feat(domain): mine correction-correlated terms as candidate domain seeds"
```

### Task 3A.2: Wire into refresh and queue, document

- [ ] **Step 5: Wire into refresh_learning_state**

After `extract_sessions.py` writes the corpus during refresh, invoke `propose_domain_rules` and append top-K proposals as `kind: domain_rule_candidate` rows to the improvement queue. Reuse the locked-append pattern.

- [ ] **Step 6: Document**

Create `agent-learning-compounder/reference-lib/domain-rules-learning`:

```markdown
# Domain Rules Learning

`bin/propose_domain_rules` mines the session corpus for n-grams that
correlate with session corrections. The proposer never modifies
`domain-rules.active.json` directly. It writes JSON proposals that
`refresh_learning_state.py` appends to `improvement-queue.jsonl` as
`kind: domain_rule_candidate`.

## Scoring

```
score(term) = correction_count(term) / (clean_count(term) + 1)
```

Higher score means the term appears disproportionately in
correction-tagged session chunks.

## Approval

Operators inspect queue entries and explicitly accept with:

```bash
python3 scripts/init_learning_system.py \
  --repo "$PWD" \
  --apply-domain-rule <queue-id>
```

(Add `--apply-domain-rule` argument handling to init_learning_system in a
follow-up — out of scope for this phase. For now, manual edits of
`domain-rules.active.json` are documented in the queue entry.)

## Defaults

- `--top-k 10` proposals per refresh.
- `--min-score 2.0`.
- `STOP_WORDS` list is intentionally small and conservative. Tune by
  expanding the in-script set if false positives surface.
```

Symlink, run full suite, commit:

```bash
ln -s ../reference-lib/domain-rules-learning agent-learning-compounder/references/domain-rules-learning.md
python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3
git add -A
git commit -m "feat(domain): wire proposer into refresh + reference doc"
```

### Phase 3B: Causal Probe over Correlation (Upgrade 6)

**Goal:** A/B test specific gates by deterministically skipping them in a fraction of sessions, then compare cohort outcomes. Surfaces directional causal evidence beyond pure correlation.

**Design:** A probe is configured per gate with a skip rate (default 0.10). During each session, the agent computes `hash(session_id || gate_id) % 10000 < rate * 10000` to deterministically choose skip-vs-load. The decision is recorded as `probe_decision` in the InstructionsLoaded event. Effectiveness evaluator (Phase 2B) splits by `probe_decision` to compute cohort delta.

**Files:**
- Create: `agent-learning-compounder/bin/causal_probe` (+ symlinks)
- Modify: `agent-learning-compounder/bin/export_gates` — emit `probe_status` and `probe_rate` when probe registered
- Modify: `agent-learning-compounder/bin/collect_hook_event` — accept `probe_decision` field
- Modify: `agent-learning-compounder/bin/evaluate_gate_effectiveness` — split by `probe_decision`
- Test: `fixtures/tests/test_causal_probe.py`
- State: `<state>/repos/<id>/probes.json` registers active probes

### Task 3B.1: Probes state file + CLI

- [ ] **Step 1: Tests**

Create `agent-learning-compounder/fixtures/tests/test_causal_probe.py`:

```python
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = REPO_ROOT / "bin" / "causal_probe"


class CausalProbe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.probes = Path(self.tmp.name) / "probes.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_register_writes_probe(self):
        subprocess.run([str(PROBE), "--probes", str(self.probes),
                        "register", "--gate-id", "g_aaa111", "--rate", "0.10"],
                       check=True)
        data = json.loads(self.probes.read_text())
        self.assertEqual(data["g_aaa111"]["rate"], 0.10)

    def test_decide_is_deterministic(self):
        subprocess.run([str(PROBE), "--probes", str(self.probes),
                        "register", "--gate-id", "g_aaa111", "--rate", "0.10"],
                       check=True)
        out_a = subprocess.check_output([
            str(PROBE), "--probes", str(self.probes),
            "decide", "--gate-id", "g_aaa111", "--session-id", "sess-1",
        ], text=True).strip()
        out_b = subprocess.check_output([
            str(PROBE), "--probes", str(self.probes),
            "decide", "--gate-id", "g_aaa111", "--session-id", "sess-1",
        ], text=True).strip()
        self.assertEqual(out_a, out_b)
        self.assertIn(out_a, {"load", "skip"})

    def test_skip_rate_roughly_holds_over_n(self):
        subprocess.run([str(PROBE), "--probes", str(self.probes),
                        "register", "--gate-id", "g_aaa111", "--rate", "0.30"],
                       check=True)
        decisions = []
        for i in range(1000):
            d = subprocess.check_output([
                str(PROBE), "--probes", str(self.probes),
                "decide", "--gate-id", "g_aaa111", "--session-id", f"s{i}",
            ], text=True).strip()
            decisions.append(d)
        skip_rate = decisions.count("skip") / len(decisions)
        self.assertAlmostEqual(skip_rate, 0.30, delta=0.05)

    def test_unregistered_gate_always_loads(self):
        self.probes.write_text("{}")
        out = subprocess.check_output([
            str(PROBE), "--probes", str(self.probes),
            "decide", "--gate-id", "g_zzz", "--session-id", "sess-1",
        ], text=True).strip()
        self.assertEqual(out, "load")
```

- [ ] **Step 2: Implement**

Create `agent-learning-compounder/bin/causal_probe`:

```python
#!/usr/bin/env python3
"""Register and decide A/B causal probes per gate_id."""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def load_probes(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_probes(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def decide(gate_id: str, session_id: str, rate: float) -> str:
    h = hashlib.sha256(f"{session_id}|{gate_id}".encode()).hexdigest()
    bucket = int(h[:8], 16) % 10000
    return "skip" if bucket < int(rate * 10000) else "load"


def cmd_register(args):
    data = load_probes(args.probes)
    data[args.gate_id] = {"rate": args.rate}
    save_probes(args.probes, data)
    return 0


def cmd_unregister(args):
    data = load_probes(args.probes)
    data.pop(args.gate_id, None)
    save_probes(args.probes, data)
    return 0


def cmd_decide(args):
    data = load_probes(args.probes)
    probe = data.get(args.gate_id)
    if not probe:
        print("load")
        return 0
    print(decide(args.gate_id, args.session_id, probe["rate"]))
    return 0


def cmd_list(args):
    data = load_probes(args.probes)
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--probes", required=True, type=Path)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("register")
    r.add_argument("--gate-id", required=True)
    r.add_argument("--rate", required=True, type=float)
    r.set_defaults(func=cmd_register)

    u = sub.add_parser("unregister")
    u.add_argument("--gate-id", required=True)
    u.set_defaults(func=cmd_unregister)

    d = sub.add_parser("decide")
    d.add_argument("--gate-id", required=True)
    d.add_argument("--session-id", required=True)
    d.set_defaults(func=cmd_decide)

    l = sub.add_parser("list")
    l.set_defaults(func=cmd_list)
    return p.parse_args()


def main():
    args = parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: chmod + symlinks + tests**

```bash
chmod +x agent-learning-compounder/bin/causal_probe
ln -s causal_probe agent-learning-compounder/bin/causal_probe.py
ln -s ../bin/causal_probe agent-learning-compounder/scripts/causal_probe.py
python3 -m unittest fixtures.tests.test_causal_probe -v
```

Expected: 4 PASS.

- [ ] **Step 4: Commit**

```bash
git add agent-learning-compounder/bin/causal_probe* \
        agent-learning-compounder/scripts/causal_probe.py \
        agent-learning-compounder/fixtures/tests/test_causal_probe.py
git commit -m "feat(probe): deterministic A/B skip decisions per gate_id"
```

### Task 3B.2: Surface probe_status in exports + split effectiveness

- [ ] **Step 5: Modify export_gates to read probes.json**

In `bin/export_gates`, add `--probes <path>` argument. When given and gate's `gate_id` appears in probes.json, emit:

```
  - probe_status: active
  - probe_rate: 0.10
```

below the `gate_id` line.

- [ ] **Step 6: Modify evaluate_gate_effectiveness to split cohorts by probe_decision**

In `bin/evaluate_gate_effectiveness`, when a session contains `probe_decision` for any of its gate_loaded_ids (via InstructionsLoaded event), split that gate's cohort into `loaded_under_probe` vs `skipped_under_probe` and report a separate delta as `causal_signal`. Existing correlation rows remain.

- [ ] **Step 7: Add fixture rows + extend the test**

Add 20 events to `gate_effectiveness_events.jsonl` with `probe_decision: load` and `probe_decision: skip` for `g_aaa111`. Extend `test_evaluate_gate_effectiveness.py`:

```python
def test_probe_cohort_emits_causal_signal(self):
    result = self._run()
    row = next(r for r in result["gates"] if r["gate_id"] == "g_aaa111")
    self.assertIn("causal_signal", row)
```

- [ ] **Step 8: Run and commit**

```bash
python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3
git add -A
git commit -m "feat(probe): wire probe_decision into exports and effectiveness scoring"
```

### Phase 3 acceptance

```bash
python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3
python3 -m unittest discover -s tests 2>&1 | tail -3
python3 scripts/run_pressure_tests.py 2>&1 | tail -3
```

Expected: all pass. Causal probe round-trip works on the eval fixture.

---

## Phase 4: Cross-Repo Gate Inheritance (Upgrade 3)

**Goal:** Promote a gate from one repo's approved set into a shared registry and inherit it into other repos with provenance tracking. Inherited gates that fail in the target repo are auto-demoted.

**Design:** Shared registry at `<state-root>/shared/gates/<gate-id>.json` (state-root configurable via `AGENT_LEARNING_SHARED_ROOT` or default `~/.local/state/agent-learning/shared`). Promotion writes a JSON record; inheritance copies into a target repo's gates with `derived_from: <origin-repo-id>:<gate-id>:<promoted-at>`. Demote when target repo's effectiveness scoring (Phase 2B) flags the inherited gate `correlated_with_failure` with n_loaded ≥ 20.

**Files:**
- Create: `agent-learning-compounder/bin/gates_promote` (+ symlinks)
- Create: `agent-learning-compounder/bin/gates_inherit` (+ symlinks)
- Create: `agent-learning-compounder/reference-lib/cross-repo-gates` (+ symlink)
- Modify: `agent-learning-compounder/bin/refresh_learning_state` — auto-demote
- Test: `fixtures/tests/test_gates_promote.py`
- Test: `fixtures/tests/test_gates_inherit.py`

### Task 4.1: gates_promote

- [ ] **Step 1: Test**

Create `agent-learning-compounder/fixtures/tests/test_gates_promote.py`:

```python
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMOTE = REPO_ROOT / "bin" / "gates_promote"


class GatesPromote(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gates_md = Path(self.tmp.name) / "approved-gates.md"
        self.shared = Path(self.tmp.name) / "shared"
        self.gates_md.write_text(
            "# Approved Agent Gates\n\n"
            "## cloudflare\n\n"
            "- gate_id: aaaaaaaaaaaa\n"
            "- category: docs-check\n"
            "- gate: Re-read current Cloudflare docs before changing wrangler config.\n"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_promote_writes_shared_record(self):
        subprocess.run([
            str(PROMOTE),
            "--gates", str(self.gates_md),
            "--gate-id", "aaaaaaaaaaaa",
            "--origin-repo", "repo-abc",
            "--shared-root", str(self.shared),
        ], check=True)
        record_path = self.shared / "gates" / "aaaaaaaaaaaa.json"
        self.assertTrue(record_path.exists())
        data = json.loads(record_path.read_text())
        self.assertEqual(data["origin_repo"], "repo-abc")
        self.assertEqual(data["domain"], "cloudflare")

    def test_promote_refuses_unknown_gate(self):
        proc = subprocess.run([
            str(PROMOTE),
            "--gates", str(self.gates_md),
            "--gate-id", "ffffffffffff",
            "--origin-repo", "repo-abc",
            "--shared-root", str(self.shared),
        ], capture_output=True, text=True, check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not found", proc.stderr)
```

- [ ] **Step 2: Implement gates_promote**

Create `agent-learning-compounder/bin/gates_promote`:

```python
#!/usr/bin/env python3
"""Promote a gate from a repo's approved-gates.md into the shared registry."""
import argparse
import json
import re
import sys
import time
from pathlib import Path


GATE_BLOCK_RE = re.compile(
    r"##\s+(?P<domain>\S+).*?gate_id:\s*(?P<gate_id>[a-f0-9]{12}).*?"
    r"category:\s*(?P<category>\S+).*?gate:\s*(?P<gate>.+?)(?=\n##|\n\Z|\Z)",
    re.DOTALL,
)


def find_gate(gates_md: Path, gate_id: str):
    text = gates_md.read_text()
    for m in GATE_BLOCK_RE.finditer(text):
        if m.group("gate_id") == gate_id:
            return {
                "domain": m.group("domain"),
                "gate_id": gate_id,
                "category": m.group("category"),
                "gate": m.group("gate").strip().splitlines()[0],
            }
    return None


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--gates", required=True, type=Path)
    p.add_argument("--gate-id", required=True)
    p.add_argument("--origin-repo", required=True)
    p.add_argument("--shared-root", required=True, type=Path)
    p.add_argument("--note", default="")
    return p.parse_args()


def main():
    args = parse_args()
    if not args.gates.exists():
        print(f"gates not found: {args.gates}", file=sys.stderr)
        return 2
    gate = find_gate(args.gates, args.gate_id)
    if not gate:
        print(f"gate_id not found: {args.gate_id}", file=sys.stderr)
        return 3
    record = {
        **gate,
        "origin_repo": args.origin_repo,
        "promoted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": args.note,
    }
    out_dir = args.shared_root / "gates"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{args.gate_id}.json").write_text(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: chmod + symlinks + run**

```bash
chmod +x agent-learning-compounder/bin/gates_promote
ln -s gates_promote agent-learning-compounder/bin/gates_promote.py
ln -s ../bin/gates_promote agent-learning-compounder/scripts/gates_promote.py
python3 -m unittest fixtures.tests.test_gates_promote -v
```

Expected: 2 PASS.

- [ ] **Step 4: Commit**

```bash
git add agent-learning-compounder/bin/gates_promote* \
        agent-learning-compounder/scripts/gates_promote.py \
        agent-learning-compounder/fixtures/tests/test_gates_promote.py
git commit -m "feat(federation): promote gate from repo to shared registry"
```

### Task 4.2: gates_inherit

- [ ] **Step 5: Test**

Create `agent-learning-compounder/fixtures/tests/test_gates_inherit.py`:

```python
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INHERIT = REPO_ROOT / "bin" / "gates_inherit"


class GatesInherit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.shared = Path(self.tmp.name) / "shared" / "gates"
        self.shared.mkdir(parents=True)
        self.target = Path(self.tmp.name) / "approved-gates.md"
        self.target.write_text("# Approved Agent Gates\n\n")
        (self.shared / "aaaaaaaaaaaa.json").write_text(json.dumps({
            "domain": "cloudflare",
            "gate_id": "aaaaaaaaaaaa",
            "category": "docs-check",
            "gate": "Re-read current Cloudflare docs before changing wrangler config.",
            "origin_repo": "repo-abc",
            "promoted_at": "2026-01-01T00:00:00Z",
            "note": "",
        }))

    def tearDown(self):
        self.tmp.cleanup()

    def test_inherit_appends_with_provenance(self):
        subprocess.run([
            str(INHERIT),
            "--shared-root", str(self.shared.parent),
            "--target-gates", str(self.target),
            "--gate-id", "aaaaaaaaaaaa",
        ], check=True)
        text = self.target.read_text()
        self.assertIn("aaaaaaaaaaaa", text)
        self.assertIn("derived_from: repo-abc:aaaaaaaaaaaa:2026-01-01T00:00:00Z", text)

    def test_inherit_is_idempotent(self):
        for _ in range(2):
            subprocess.run([
                str(INHERIT),
                "--shared-root", str(self.shared.parent),
                "--target-gates", str(self.target),
                "--gate-id", "aaaaaaaaaaaa",
            ], check=True)
        # gate_id should appear only once
        text = self.target.read_text()
        self.assertEqual(text.count("aaaaaaaaaaaa"), 1)
```

- [ ] **Step 6: Implement**

Create `agent-learning-compounder/bin/gates_inherit`:

```python
#!/usr/bin/env python3
"""Inherit a gate from the shared registry into a target repo's approved gates."""
import argparse
import json
import re
import sys
from pathlib import Path


def gate_already_present(target: Path, gate_id: str) -> bool:
    return gate_id in target.read_text()


def append_gate(target: Path, record: dict):
    block = (
        f"\n## {record['domain']}\n\n"
        f"- gate_id: {record['gate_id']}\n"
        f"- category: {record['category']}\n"
        f"- gate: {record['gate']}\n"
        f"- derived_from: {record['origin_repo']}:{record['gate_id']}:{record['promoted_at']}\n"
    )
    with target.open("a") as fh:
        fh.write(block)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--shared-root", required=True, type=Path)
    p.add_argument("--target-gates", required=True, type=Path)
    p.add_argument("--gate-id", required=True)
    return p.parse_args()


def main():
    args = parse_args()
    record_path = args.shared_root / "gates" / f"{args.gate_id}.json"
    if not record_path.exists():
        print(f"shared gate not found: {record_path}", file=sys.stderr)
        return 2
    if not args.target_gates.exists():
        print(f"target gates not found: {args.target_gates}", file=sys.stderr)
        return 2
    if gate_already_present(args.target_gates, args.gate_id):
        return 0
    record = json.loads(record_path.read_text())
    append_gate(args.target_gates, record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: chmod + symlinks + run**

```bash
chmod +x agent-learning-compounder/bin/gates_inherit
ln -s gates_inherit agent-learning-compounder/bin/gates_inherit.py
ln -s ../bin/gates_inherit agent-learning-compounder/scripts/gates_inherit.py
python3 -m unittest fixtures.tests.test_gates_inherit -v
```

Expected: 2 PASS.

- [ ] **Step 8: Commit**

```bash
git add agent-learning-compounder/bin/gates_inherit* \
        agent-learning-compounder/scripts/gates_inherit.py \
        agent-learning-compounder/fixtures/tests/test_gates_inherit.py
git commit -m "feat(federation): inherit shared gate into target repo with provenance"
```

### Task 4.3: Auto-demote inherited gates that underperform

- [ ] **Step 9: Add demote logic in refresh_learning_state**

After Phase 2B's effectiveness evaluator runs in refresh, iterate result["gates"]. For each gate with label `correlated_with_failure` and `n_loaded >= 20`, check whether the gate has a `derived_from:` line in `latest-approved-gates.md`. If so, append a queue row:

```python
{
    "id": f"demote-{gate_id}-{int(time.time())}",
    "kind": "inherited_gate_demote_candidate",
    "text": f"Demote inherited gate {gate_id} from {derived_from}: failure delta after n={n_loaded}.",
    "gate_id": gate_id,
    "derived_from": derived_from_str,
    "evidence": {"n_loaded": n_loaded, "delta": delta},
    "ts": iso_now(),
}
```

Demotion is operator-approved; we only queue.

- [ ] **Step 10: Test the demote path**

Add to `test_evaluate_gate_effectiveness.py`:

```python
def test_inherited_underperforming_gate_queued_for_demote(self):
    import shutil, subprocess, json, tempfile
    src = REPO_ROOT / "fixtures" / "eval-fixtures" / "mini-repo"
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        shutil.copytree(src, repo)
        gates_md = next((repo / ".agent-learning" / "repos").rglob(
            "reports/latest-approved-gates.md"))
        gates_md.write_text(
            gates_md.read_text()
            + "\n## cloudflare\n\n"
            + "- gate_id: bbbbbbbbbbbb\n"
            + "- category: live-check\n"
            + "- gate: Run deploy verification.\n"
            + "- derived_from: repo-origin:bbbbbbbbbbbb:2026-01-01T00:00:00Z\n"
        )
        events = next((repo / ".agent-learning" / "repos").rglob("hook-events.jsonl"))
        with events.open("a") as fh:
            for i in range(25):
                fh.write(json.dumps({
                    "schema_version": 2, "event": "InstructionsLoaded",
                    "correlation_id": f"d{i}", "gate_loaded_ids": ["bbbbbbbbbbbb"],
                }) + "\n")
                fh.write(json.dumps({
                    "schema_version": 2, "event": "SessionEnd",
                    "correlation_id": f"d{i}",
                    "outcome": "correction" if i % 4 != 0 else "clean",
                }) + "\n")
            for i in range(25):
                fh.write(json.dumps({
                    "schema_version": 2, "event": "InstructionsLoaded",
                    "correlation_id": f"a{i}", "gate_loaded_ids": [],
                }) + "\n")
                fh.write(json.dumps({
                    "schema_version": 2, "event": "SessionEnd",
                    "correlation_id": f"a{i}", "outcome": "clean",
                }) + "\n")
        subprocess.run([
            str(REPO_ROOT / "bin" / "refresh_learning_state"),
            "--repo", str(repo),
            "--state-dir", str(repo / ".agent-learning"),
            "--refresh-only",
        ], check=True)
        queue = next((repo / ".agent-learning" / "repos").rglob("improvement-queue.jsonl"))
        rows = [json.loads(ln) for ln in queue.read_text().splitlines() if ln]
        kinds = {r.get("kind") for r in rows}
        self.assertIn("inherited_gate_demote_candidate", kinds)
```

Implement scaffold with the existing mini-repo plus appended `derived_from` line.

- [ ] **Step 11: Run and commit**

```bash
python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3
git add -A
git commit -m "feat(federation): auto-queue demote for underperforming inherited gates"
```

### Task 4.4: Reference doc

- [ ] **Step 12: Write `reference-lib/cross-repo-gates`**

```markdown
# Cross-Repo Gate Federation

Gates promoted from one repo enter a shared registry. Other repos inherit them
with full provenance. Underperforming inherited gates are auto-queued for
demote review (not auto-removed).

## Shared registry

Default root: `~/.local/state/agent-learning/shared/`
Override via `AGENT_LEARNING_SHARED_ROOT` or `--shared-root`.

Layout:

```
shared/
  gates/
    <gate-id>.json
```

Each JSON: `{domain, gate_id, category, gate, origin_repo, promoted_at, note}`.

## Promote

```bash
python3 scripts/gates_promote.py \
  --gates "<state>/repos/<repo-id>/reports/latest-approved-gates.md" \
  --gate-id <gate-id> \
  --origin-repo <repo-id> \
  --shared-root "<shared-root>"
```

## Inherit

```bash
python3 scripts/gates_inherit.py \
  --shared-root "<shared-root>" \
  --target-gates "<state>/repos/<other-repo-id>/reports/latest-approved-gates.md" \
  --gate-id <gate-id>
```

Inheritance is idempotent.

## Demote

`refresh_learning_state` queues `inherited_gate_demote_candidate` when an
inherited gate's effectiveness label is `correlated_with_failure` and
`n_loaded >= 20` in the target repo. Operator removes the gate by editing
the target's `latest-approved-gates.md`. Removed gate_ids are noted in the
queue entry as resolved.
```

Symlink, commit:

```bash
ln -s ../reference-lib/cross-repo-gates agent-learning-compounder/references/cross-repo-gates.md
git add agent-learning-compounder/reference-lib/cross-repo-gates \
        agent-learning-compounder/references/cross-repo-gates.md
git commit -m "docs: cross-repo gate federation workflow"
```

### Phase 4 acceptance

Full test suites pass. Manual smoke: promote a gate from one mini-repo into shared, inherit into a second mini-repo, verify provenance line; run refresh against the second repo with a failure-labeled fixture, verify demote candidate in queue.

---

## Phase 5: Surface (MCP Server + Dashboard)

### Phase 5A: MCP Server Wrapping the Exports (Upgrade 4)

**Goal:** Expose `get_gates`, `report_outcome`, `propose_gate`, `get_skill_context` as MCP tools so non-Codex/Claude runtimes integrate via one adapter and feedback becomes synchronous within a session.

**Design:** Single Python process. Reads state from `AGENT_LEARNING_STATE_DIR` plus `--repo` arg. Stdio transport. Lazy-imports `mcp` SDK so package import doesn't break if SDK isn't installed.

**Files:**
- Create: `agent-learning-compounder/alc_mcp/server.py`
- Create: `agent-learning-compounder/alc_mcp/__init__.py` (empty)
- Create: `agent-learning-compounder/alc_mcp/README.md`
- Create: `agent-learning-compounder/alc_mcp/tests/test_server.py`
- Create: `agent-learning-compounder/alc_mcp/tests/__init__.py` (empty)

Note: internal package is `alc_mcp` (not `mcp`) to avoid clashing with the `mcp` SDK on import path.

### Task 5A.1: MCP server scaffolding

- [ ] **Step 1: Add the MCP dependency hint to requirements**

Create `agent-learning-compounder/requirements-optional.txt`:

```
# Optional extras for agent-learning-compounder.
# Install only the section(s) you need.

# alc_mcp/server.py
mcp>=0.9.0

# dashboard/ (Phase 5B)
fastapi>=0.110
jinja2>=3.1
uvicorn>=0.27
httpx>=0.26  # required by FastAPI TestClient

# Phase 2A optional vector backend
sentence-transformers>=2.7
```

Upstream MANIFEST.json stays untouched; optional extras are stdlib-or-skip everywhere they appear in tests.

- [ ] **Step 2: Write the test**

Create `agent-learning-compounder/alc_mcp/tests/test_server.py`:

```python
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class McpServerTools(unittest.TestCase):
    """Test the tool handlers directly (transport-independent)."""

    def setUp(self):
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest("mcp SDK not installed")
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        src = REPO_ROOT / "fixtures" / "eval-fixtures" / "mini-repo"
        shutil.copytree(src, self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_get_gates_returns_list(self):
        import sys
        sys.path.insert(0, str(REPO_ROOT))
        from alc_mcp.server import get_gates_handler  # type: ignore
        result = asyncio.run(get_gates_handler({"repo": str(self.repo)}))
        self.assertIsInstance(result, list)

    def test_propose_gate_appends_queue_row(self):
        import sys
        sys.path.insert(0, str(REPO_ROOT))
        from alc_mcp.server import propose_gate_handler  # type: ignore
        payload = {
            "repo": str(self.repo),
            "domain": "tests",
            "category": "validation-check",
            "gate": "Always run pytest -x before claiming done.",
            "evidence": "Two corrections in current session after skipping validation.",
        }
        result = asyncio.run(propose_gate_handler(payload))
        self.assertIn("queue_id", result)
        queue = next((self.repo / ".agent-learning" / "repos").rglob("improvement-queue.jsonl"))
        rows = [json.loads(ln) for ln in queue.read_text().splitlines() if ln]
        self.assertTrue(any(r.get("id") == result["queue_id"] for r in rows))
```

- [ ] **Step 3: Run; expect skip if mcp not installed, fail otherwise**

Run: `python3 -m unittest alc_mcp.tests.test_server -v`
Expected: SKIP if mcp absent; ERROR otherwise.

- [ ] **Step 4: Implement `mcp/server.py`**

```python
"""MCP server exposing agent-learning state as queryable tools.

Tools:
- get_gates(repo, scope=None) -> list[dict]
- report_outcome(repo, gate_id, outcome) -> dict
- propose_gate(repo, domain, category, gate, evidence) -> dict
- get_skill_context(repo) -> str
"""
import asyncio
import fcntl
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

try:
    from mcp.server import Server
    from mcp.types import Tool, TextContent
except ImportError as e:
    raise ImportError(
        "mcp SDK required for mcp/server.py. "
        "Install with `pip install mcp` (or include the optional extra)."
    ) from e


def _repo_state_dir(repo: Path) -> Path:
    payload = (repo / ".agent-learning.json")
    if payload.exists():
        data = json.loads(payload.read_text())
        for key in ("latest_approved_gates", "latest_skill_context"):
            p = data.get(key)
            if p:
                return Path(p).resolve().parent.parent
    return repo / ".agent-learning"


def _latest_gates_path(repo: Path) -> Path:
    payload = repo / ".agent-learning.json"
    if payload.exists():
        data = json.loads(payload.read_text())
        p = data.get("latest_approved_gates")
        if p:
            return Path(p)
    raise FileNotFoundError("latest_approved_gates pointer missing")


def _improvement_queue_path(repo: Path) -> Path:
    state = _repo_state_dir(repo)
    return next((state / "repos").rglob("improvement-queue.jsonl"))


async def get_gates_handler(args: dict) -> list[dict]:
    repo = Path(args["repo"]).resolve()
    md = _latest_gates_path(repo).read_text()
    blocks = re.split(r"\n## ", md)
    out = []
    for block in blocks[1:]:
        domain = block.splitlines()[0].strip()
        for m in re.finditer(
            r"gate_id:\s*(?P<id>[a-f0-9]{12}).*?category:\s*(?P<cat>\S+).*?gate:\s*(?P<g>.+?)(?=\n-|\Z)",
            block, re.DOTALL,
        ):
            out.append({
                "domain": domain,
                "gate_id": m.group("id"),
                "category": m.group("cat"),
                "gate": m.group("g").strip().splitlines()[0],
            })
    scope = args.get("scope")
    if scope:
        out = [g for g in out if g["domain"] == scope]
    return out


async def report_outcome_handler(args: dict) -> dict:
    """Record a runtime outcome for a gate. Writes a synthetic hook event."""
    repo = Path(args["repo"]).resolve()
    state = _repo_state_dir(repo)
    log = next((state / "repos").rglob("hook-events.jsonl"))
    row = {
        "schema_version": 2,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "ToolReportOutcome",
        "correlation_id": args.get("correlation_id", ""),
        "gate_loaded_ids": [args["gate_id"]],
        "outcome": args["outcome"],
    }
    fd = os.open(str(log), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return {"recorded": True}


async def propose_gate_handler(args: dict) -> dict:
    repo = Path(args["repo"]).resolve()
    queue = _improvement_queue_path(repo)
    h = hashlib.sha256(
        f"{args['domain']}|{args['category']}|{args['gate']}".encode()
    ).hexdigest()[:12]
    queue_id = f"proposed-{h}-{int(time.time())}"
    row = {
        "id": queue_id,
        "kind": "operator_proposed_gate",
        "domain": args["domain"],
        "category": args["category"],
        "text": args["gate"],
        "evidence": args.get("evidence", ""),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with queue.open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return {"queue_id": queue_id}


async def get_skill_context_handler(args: dict) -> str:
    repo = Path(args["repo"]).resolve()
    payload = json.loads((repo / ".agent-learning.json").read_text())
    return Path(payload["latest_skill_context"]).read_text()


def build_server() -> Server:
    server = Server("agent-learning-compounder")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(name="get_gates",
                 description="Return approved gates for a repo, optionally scoped.",
                 inputSchema={"type": "object", "required": ["repo"],
                              "properties": {"repo": {"type": "string"},
                                             "scope": {"type": "string"}}}),
            Tool(name="report_outcome",
                 description="Record a gate outcome (loaded_helpful, loaded_unhelpful, skipped).",
                 inputSchema={"type": "object", "required": ["repo", "gate_id", "outcome"],
                              "properties": {"repo": {"type": "string"},
                                             "gate_id": {"type": "string"},
                                             "outcome": {"type": "string"},
                                             "correlation_id": {"type": "string"}}}),
            Tool(name="propose_gate",
                 description="Append an operator-proposed gate to the review queue.",
                 inputSchema={"type": "object",
                              "required": ["repo", "domain", "category", "gate"],
                              "properties": {"repo": {"type": "string"},
                                             "domain": {"type": "string"},
                                             "category": {"type": "string"},
                                             "gate": {"type": "string"},
                                             "evidence": {"type": "string"}}}),
            Tool(name="get_skill_context",
                 description="Return the latest skill-context markdown for the repo.",
                 inputSchema={"type": "object", "required": ["repo"],
                              "properties": {"repo": {"type": "string"}}}),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        handlers = {
            "get_gates": get_gates_handler,
            "report_outcome": report_outcome_handler,
            "propose_gate": propose_gate_handler,
            "get_skill_context": get_skill_context_handler,
        }
        h = handlers.get(name)
        if not h:
            return [TextContent(type="text", text=json.dumps({"error": f"unknown tool {name}"}))]
        try:
            result = await h(arguments)
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]
        if isinstance(result, str):
            return [TextContent(type="text", text=result)]
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


def main():
    from mcp.server.stdio import stdio_server
    server = build_server()
    asyncio.run(stdio_server(server))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests + smoke**

```bash
pip install --user mcp 2>/dev/null || true
python3 -m unittest alc_mcp.tests.test_server -v
```

Expected: PASS if mcp installed; SKIP otherwise.

- [ ] **Step 6: Commit**

```bash
git add agent-learning-compounder/mcp \
        agent-learning-compounder/MANIFEST.json
git commit -m "feat(mcp): stdio server exposing gates, outcomes, proposals, skill context"
```

### Task 5A.2: MCP README + agent manifest hooks

- [ ] **Step 7: Write `mcp/README.md`**

```markdown
# agent-learning-compounder MCP server

Stdio MCP server exposing the durable state as queryable tools.

## Install

```bash
pip install mcp
```

## Run

```bash
python3 -m alc_mcp.server
# or, if invoked from the installed skill root:
python3 mcp/server.py
```

## Tools

- `get_gates(repo, scope=None) -> list[gate]`
- `report_outcome(repo, gate_id, outcome[, correlation_id]) -> {recorded: bool}`
- `propose_gate(repo, domain, category, gate, evidence?) -> {queue_id}`
- `get_skill_context(repo) -> str`

## Integration

For Claude Desktop / Cursor / other MCP clients, configure stdio with the
absolute path to this server entry point. Repo path is passed per call so a
single server instance can serve multiple repos.
```

- [ ] **Step 8: Mention in agents/{claude,openai}.yaml**

Append to each manifest:

```yaml
mcp:
  optional: true
  entrypoint: "python3 ${CLAUDE_PLUGIN_ROOT}/alc_mcp/server.py"
  description: "Query approved gates and propose new ones over MCP."
```

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "docs(mcp): server README and agent manifest hints"
```

### Phase 5A acceptance

`mcp` installed → all tests pass. `python3 mcp/server.py` starts a stdio server; manual MCP client call to `get_gates` returns the mini-repo's gates.

---

### Phase 5B: Operator-Facing Dashboard (Upgrade 8)

**Goal:** A single-page HTMX dashboard surfacing gate inventory, queue depth, hook event rates, probe status, and stale-gate alerts. Read-only; no auth needed (localhost-only).

**Design:** FastAPI + Jinja2 templates + HTMX, all rendered server-side. Bound to `127.0.0.1` by default. Auto-refresh via `hx-trigger="every 30s"` on each panel. Optional dep: `fastapi`, `jinja2`, `uvicorn`. Gracefully refuses to start if absent.

**Files:**
- Create: `agent-learning-compounder/bin/serve_dashboard` (+ symlinks)
- Create: `agent-learning-compounder/dashboard/templates/index.html`
- Create: `agent-learning-compounder/dashboard/templates/_gates.html` (panel partial)
- Create: `agent-learning-compounder/dashboard/templates/_queue.html`
- Create: `agent-learning-compounder/dashboard/templates/_probes.html`
- Create: `agent-learning-compounder/dashboard/static/style.css`
- Create: `agent-learning-compounder/dashboard/__init__.py` (empty)
- Test: `agent-learning-compounder/fixtures/tests/test_dashboard.py`

### Task 5B.1: Build the FastAPI app

- [ ] **Step 1: Test stub**

Create `agent-learning-compounder/fixtures/tests/test_dashboard.py`:

```python
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class Dashboard(unittest.TestCase):
    def setUp(self):
        try:
            import fastapi  # noqa: F401
        except ImportError:
            self.skipTest("fastapi not installed")
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        shutil.copytree(REPO_ROOT / "fixtures" / "eval-fixtures" / "mini-repo", self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def _client(self):
        import sys
        sys.path.insert(0, str(REPO_ROOT))
        from fastapi.testclient import TestClient
        from dashboard import build_app
        return TestClient(build_app(repo=self.repo))

    def test_index_renders(self):
        r = self._client().get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Agent Learning Compounder", r.content)

    def test_gates_partial_returns_html_table(self):
        r = self._client().get("/_gates")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"<table", r.content)

    def test_queue_partial_lists_pending(self):
        r = self._client().get("/_queue")
        self.assertEqual(r.status_code, 200)

    def test_probes_partial_lists_active(self):
        r = self._client().get("/_probes")
        self.assertEqual(r.status_code, 200)
```

- [ ] **Step 2: Create `dashboard/__init__.py`**

```python
"""Operator dashboard for agent-learning state.

Optional. Requires fastapi, jinja2, uvicorn.
"""
import json
from pathlib import Path

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
except ImportError as e:
    raise ImportError("fastapi + jinja2 required for dashboard") from e

HERE = Path(__file__).resolve().parent


def _resolve_state(repo: Path):
    payload = json.loads((repo / ".agent-learning.json").read_text())
    return {
        "gates_md": Path(payload["latest_approved_gates"]),
        "skill_context_md": Path(payload["latest_skill_context"]),
        "queue": next((repo / ".agent-learning" / "repos").rglob("improvement-queue.jsonl")),
        "probes": next(((repo / ".agent-learning" / "repos").rglob("probes.json")), None),
        "events": next(((repo / ".agent-learning" / "repos").rglob("hook-events.jsonl")), None),
    }


def build_app(repo: Path) -> "FastAPI":
    app = FastAPI(title="agent-learning-compounder dashboard")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    state = _resolve_state(repo)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse("index.html", {
            "request": request, "repo": str(repo),
        })

    @app.get("/_gates", response_class=HTMLResponse)
    async def gates(request: Request):
        return templates.TemplateResponse("_gates.html", {
            "request": request, "gates_md": state["gates_md"].read_text(),
        })

    @app.get("/_queue", response_class=HTMLResponse)
    async def queue(request: Request):
        rows = []
        if state["queue"].exists():
            rows = [json.loads(ln) for ln in state["queue"].read_text().splitlines() if ln]
        return templates.TemplateResponse("_queue.html", {
            "request": request, "rows": rows,
        })

    @app.get("/_probes", response_class=HTMLResponse)
    async def probes(request: Request):
        data = {}
        if state["probes"] and state["probes"].exists():
            data = json.loads(state["probes"].read_text())
        return templates.TemplateResponse("_probes.html", {
            "request": request, "probes": data,
        })

    return app
```

- [ ] **Step 3: Write `dashboard/templates/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>agent-learning-compounder dashboard</title>
  <script src="https://unpkg.com/htmx.org@1.9.10"></script>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <header>
    <h1>Agent Learning Compounder</h1>
    <p>Repo: <code>{{ repo }}</code></p>
  </header>
  <main>
    <section id="gates" hx-get="/_gates" hx-trigger="load, every 30s">
      <h2>Approved gates</h2>
    </section>
    <section id="queue" hx-get="/_queue" hx-trigger="load, every 30s">
      <h2>Improvement queue</h2>
    </section>
    <section id="probes" hx-get="/_probes" hx-trigger="load, every 30s">
      <h2>Active probes</h2>
    </section>
  </main>
</body>
</html>
```

- [ ] **Step 4: Write `_gates.html`**

```html
<table>
  <thead><tr><th>Domain</th><th>Category</th><th>Gate ID</th><th>Gate</th></tr></thead>
  <tbody>
  {% set lines = gates_md.splitlines() %}
  {% set ns = namespace(domain='', cat='', gid='') %}
  {% for line in lines %}
    {% if line.startswith('## ') %}{% set ns.domain = line[3:] %}{% endif %}
    {% if 'gate_id:' in line %}{% set ns.gid = line.split('gate_id:')[1].strip() %}{% endif %}
    {% if 'category:' in line %}{% set ns.cat = line.split('category:')[1].strip() %}{% endif %}
    {% if line.lstrip().startswith('- gate:') %}
      <tr>
        <td>{{ ns.domain }}</td>
        <td>{{ ns.cat }}</td>
        <td><code>{{ ns.gid }}</code></td>
        <td>{{ line.split('- gate:')[1].strip() }}</td>
      </tr>
    {% endif %}
  {% endfor %}
  </tbody>
</table>
```

- [ ] **Step 5: Write `_queue.html`**

```html
<table>
  <thead><tr><th>ID</th><th>Kind</th><th>Text</th><th>When</th></tr></thead>
  <tbody>
    {% for row in rows %}
    <tr>
      <td><code>{{ row.id }}</code></td>
      <td>{{ row.kind | default('candidate') }}</td>
      <td>{{ row.text }}</td>
      <td>{{ row.ts }}</td>
    </tr>
    {% else %}
    <tr><td colspan="4">Empty queue.</td></tr>
    {% endfor %}
  </tbody>
</table>
```

- [ ] **Step 6: Write `_probes.html`**

```html
<table>
  <thead><tr><th>Gate ID</th><th>Skip rate</th></tr></thead>
  <tbody>
    {% for gid, p in probes.items() %}
    <tr><td><code>{{ gid }}</code></td><td>{{ '%.0f%%' % (p.rate * 100) }}</td></tr>
    {% else %}
    <tr><td colspan="2">No active probes.</td></tr>
    {% endfor %}
  </tbody>
</table>
```

- [ ] **Step 7: Write minimal `static/style.css`**

```css
body { font-family: -apple-system, system-ui, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; }
header h1 { margin-bottom: 0.25rem; }
section { margin-bottom: 2.5rem; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #e3e3e3; vertical-align: top; }
code { background: #f4f4f4; padding: 0.1rem 0.35rem; border-radius: 3px; }
```

- [ ] **Step 8: Write the launcher**

Create `agent-learning-compounder/bin/serve_dashboard`:

```python
#!/usr/bin/env python3
"""Launch the operator dashboard on localhost."""
import argparse
import sys
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True, type=Path)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    return p.parse_args()


def main():
    args = parse_args()
    try:
        import uvicorn
    except ImportError:
        print("uvicorn not installed; pip install uvicorn fastapi jinja2", file=sys.stderr)
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dashboard import build_app
    app = build_app(repo=args.repo.resolve())
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 9: chmod + symlinks + run tests**

```bash
chmod +x agent-learning-compounder/bin/serve_dashboard
ln -s serve_dashboard agent-learning-compounder/bin/serve_dashboard.py
ln -s ../bin/serve_dashboard agent-learning-compounder/scripts/serve_dashboard.py
pip install --user fastapi jinja2 uvicorn httpx 2>/dev/null || true
python3 -m unittest fixtures.tests.test_dashboard -v
```

Expected: PASS (or SKIP if fastapi missing).

- [ ] **Step 10: Manual smoke**

```bash
python3 agent-learning-compounder/scripts/serve_dashboard.py --repo ~/path/to/test-repo &
sleep 1 && curl -s http://127.0.0.1:8765/ | head -5
```

Expected: HTML page header rendered.

- [ ] **Step 11: Commit**

```bash
git add agent-learning-compounder/bin/serve_dashboard* \
        agent-learning-compounder/scripts/serve_dashboard.py \
        agent-learning-compounder/dashboard \
        agent-learning-compounder/fixtures/tests/test_dashboard.py
git commit -m "feat(dashboard): localhost FastAPI+HTMX operator view"
```

### Phase 5 acceptance

```bash
python3 -m unittest discover -s fixtures/tests 2>&1 | tail -3
python3 -m unittest discover -s tests 2>&1 | tail -3
python3 scripts/run_pressure_tests.py 2>&1 | tail -3
```

Expected: all tests pass; MCP and dashboard tests skip gracefully when optional deps are absent.

---

## Cross-Phase Final Acceptance

After Phase 5 lands, run the complete verification suite:

```bash
cd ~/work/active/agent-learning-compounder/agent-learning-compounder
python3 -m unittest discover -s fixtures/tests -v 2>&1 | tail -10
python3 -m unittest discover -s tests -v 2>&1 | tail -5
python3 scripts/run_pressure_tests.py 2>&1 | tail -10
```

Expected: all green. Then do an end-to-end smoke against a real repo:

```bash
cd ~/work/active/agent-learning-compounder
python3 agent-learning-compounder/scripts/init_learning_system.py \
  --repo "$PWD" \
  --state-dir "$PWD/.agent-learning" \
  --install-repo-integration \
  --install-hooks \
  --self-test
python3 agent-learning-compounder/scripts/refresh_learning_state.py \
  --repo "$PWD" \
  --state-dir "$PWD/.agent-learning"
ls .agent-learning/repos/*/reports/
cat .agent-learning/repos/*/reports/latest-approved-gates.md | head -30
```

Expected: gates emitted with `gate_id`; queue contains gate_retirement_candidate / domain_rule_candidate rows when fixtures match; dashboard renders if optional deps present.

Then bump the package version:

- Update `MANIFEST.json` version to `2026.05.24+review7-production+plus1`.
- Update `agent-learning-compounder/reference-lib/production-signoff` with the eight-upgrade phase summary.
- Tag the release: `git tag v2026.05.24-plus1 && git log --oneline | head -20`.

---

## Risk Register

- **MCP and FastAPI as optional deps.** Tests skip cleanly without them; production behavior unchanged. Operators wanting these features install the extras.
- **Phase 1 changes a persisted format.** Existing `hook-events.jsonl` rows lack `schema_version`. Read paths default to v1 on absence. `replay_hook_events` exists for explicit migration. No automatic in-place mutation.
- **Phase 2B effectiveness numbers are correlation-only.** Phase 3B (probe) adds a directional causal signal, but only when an operator opts in by registering a probe. Default behavior remains pure correlation.
- **Phase 4 federation moves data between repos.** Promotion is operator-initiated. Inheritance is repo-scoped. Demote is queued, not auto-applied. Provenance line documents origin permanently.
- **Phase 5A MCP server runs in-process and reads state directly.** No write paths besides `propose_gate` and `report_outcome`, both append-only and locked. Stdio transport only — no network listener.
- **Phase 5B dashboard binds to 127.0.0.1.** Do not expose the port externally without adding auth.
