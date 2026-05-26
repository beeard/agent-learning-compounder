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

Thin trigger skill. All synthesis logic lives in `bin/alc_next_action.py`
(the `next_action` function) — tested, version-controlled, compoundable.

## What this skill does

1. Detects the user's lifecycle intent from their phrasing.
2. Calls `mcp__alc__next_action` with the detected intent and the current
   repo path.
3. Relays the synthesised headline + rationale and proposes the suggested
   action.

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
Call: mcp__alc__next_action
Args: { "repo": "<current repo path>", "intent": "<detected intent>" }
```

Relay the response as follows:

1. **Headline** — display verbatim as a bold one-liner.
2. **Rationale** — display verbatim as a short paragraph.
3. **Suggested action** — if `suggested.skill` is non-null, offer to run it:
   > "Suggested: `/<skill>` `<args>`" (or just `/<skill>` if args is null)
   > "<suggested.prompt>"
4. **Alternatives** — if present, list them as a short bullet list:
   > "Alternatives: /<skill> — <rationale>"

Do not dump the raw JSON. Do not add commentary beyond what the response
provides — the synthesiser's `rationale` field already explains the
recommendation.

## Side effect

Each call writes `<state-root>/repos/<repo-id>/reports/latest-next-action.json`.
This is intentional — the dashboard and session-start hook can read the most
recent synthesised answer without re-invoking the MCP tool.

## Notes

- If the MCP server is unavailable, say so and offer to run
  `python3 bin/alc_next_action.py` directly (not yet wired as a CLI, but
  the module is importable).
- This skill subsumes any ad-hoc "what should I do" questions that would
  otherwise require the user to know which slash command applies to their
  current state.
