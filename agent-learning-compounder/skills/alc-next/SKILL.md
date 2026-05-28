---
name: alc-next
description: >
  Session lifecycle synthesiser. Use this skill when the user asks any
  variant of: "what's next", "what should I do", "session start",
  "starting up", "session end", "ending session", "wrap up",
  "where did I leave off", "where was I", "sum up", "summary", "recap",
  "context dump", "what was I doing", "next move", "next step",
  "pick up where I left off", "catch me up", "what do I work on",
  "hva er neste", "hva skal jeg gjøre", "hvor var jeg",
  "neste steg", "avslutt sesjon", "oppsummering".
---

# alc-next — session lifecycle synthesiser

Thin trigger skill. The MCP surface provides `get_session_signals` for raw
facts and `next_action` as the compatibility wrapper for existing callers.
Prefer prompt-owned ranking from `get_session_signals`; use `next_action`
only when a caller needs the legacy synthesized response/cache behavior.

## What this skill does

1. Detects the user's lifecycle intent from their phrasing.
2. Calls `mcp__alc__get_session_signals` with the detected intent and the
   current repo path.
3. Ranks the returned facts in prompt space using the priority order below.
4. Relays one deterministic next move with a concise rationale.

## Intent mapping

| User says                                      | intent param |
|------------------------------------------------|--------------|
| "what's next", "what should I do", "next step" | `start`      |
| "session start", "starting up", "booting up"   | `start`      |
| "session end", "ending", "wrap up", "close out"| `end`        |
| "where did I leave off", "where was I", "pick up" | `leftoff` |
| "recap", "summary", "what happened", "sum up"  | `recap`      |
| unclear / general                              | `auto`       |
| Norwegian: "hva er neste", "neste steg"        | `start`      |
| Norwegian: "hvor var jeg", "hva holdt jeg på med" | `leftoff` |
| Norwegian: "oppsummering", "avslutt"           | `end`        |

## Execution

```
Call: mcp__alc__get_session_signals
Args: { "repo": "<current repo path>", "intent": "<detected intent>" }
```

Rank the returned facts in this order:

1. Pending patches: review the first or list the queue.
2. Recent rejected verdicts: investigate the failed recommendations.
3. Four or more pending recommendations: triage with `/alc-report`.
4. Recent applies: plan or validate the next iteration.
5. Recent telemetry but no workflow items: investigate why the loop is not
   producing recommendations or queue rows.
6. Quiet state: pick one longer-horizon improvement.

Do not dump the raw JSON. State one move, the signal that caused it, and the
tool or file to inspect next. Do not ask the user to pick from a menu.

## Side effect

`get_session_signals` is read-only and does not write a cache. `next_action`
still writes `<state-root>/repos/<repo-id>/reports/latest-next-action.json`;
use it only for compatibility surfaces that need that cache.

## Notes

- If the MCP server is unavailable, say so and offer to run
  `python3 bin/alc_next_action.py` directly (not yet wired as a CLI, but
  the module is importable).
- This skill subsumes any ad-hoc "what should I do" questions that would
  otherwise require the user to know which slash command applies to their
  current state.
