# Mode 2: distill-sessions

Mine prior agent transcripts (Claude Code, Codex, Hermes, Gemini, ChatGPT, anything) for evidence of where the user needed verification, correction, or a second pass. Produces items for `memory_derived` and feeds `agent_compensation` in mode 3.

## What counts as evidence

Only two things count as evidence:

1. **A verbatim quote** from a session, up to 25 words, scrubbed for secrets. Use when the exact phrasing carries the signal (e.g. the user asked the agent to "double-check that we actually merged" — the word *actually* matters).
2. **A count** across sessions, e.g. "in 4 of the last 7 sessions involving Cloudflare deploys, the user re-asked the agent to confirm the binding was live before trusting the deploy."

Anything else — vibes, impressions, "the user seems to" — is banned. If you cannot produce a quote or a count, the observation does not belong in the report.

## Where to look

Session-log locations vary by agent. Treat these as the default search set; if the user's directory layout differs, ask once at the start of the run. `../../bin/extract_sessions.py` reads `.jsonl` and `.json` files, including Codex response items and ChatGPT-style `mapping -> message -> author/content` exports.

| Agent | Default log location |
| --- | --- |
| Claude Code | `~/.claude/projects/<encoded-path>/*.jsonl` |
| Codex CLI | `~/.codex/sessions/*.json` or `~/.codex/transcripts/` |
| Hermes | `~/.config/hermes/sessions/` |
| Gemini CLI | `~/.gemini/history/` or wherever the user's wrapper writes it |
| ChatGPT exports | A folder of `conversation.json` files |

If a directory does not exist, skip it silently; do not invent paths.

## Time-bounding

Default: last 30 days. If the user asks for a longer window, expand. Do NOT process more than ~50 sessions per run. `../../bin/extract_sessions.py` enforces this by default with `--max-sessions 50`; past that it samples oldest 10 + middle 15 + newest 25 matching transcript files and emits a `meta: sampled_sessions ...` line that the report must carry under `confirmed_current`. Use `--no-sampling` only for focused debugging, not durable memory runs.

## Scrub discipline (non-negotiable)

Every quoted fragment, without exception, passes through `../../bin/scrub_secrets.py` before it touches the report. The script is regex-based and conservative: when in doubt, it redacts. That is the correct failure mode.

Workflow per quote:

```bash
# Pipe the candidate quote through the scrubber
echo "$QUOTE" | python ../../bin/scrub_secrets.py
```

If the scrubbed output contains any `[REDACTED:*]` marker:
- Drop the quote.
- Replace with a paraphrase that contains no secret-shaped content, OR
- Convert the observation to a count (e.g. "across 3 sessions, the user shared credentials inline and asked the agent to re-issue them" — no quote needed).

The scrubber covers: GitHub tokens (`gh[pousr]_…`), OpenAI keys (`sk-…` and `sk-proj-…`), Anthropic keys (`sk-ant-…`), AWS access/secret keys, bearer tokens, JWT-shaped strings, SSH private keys, and generic `password=`/`secret=`/`token=`/`api_key=` patterns.

See `../../bin/scrub_secrets.py` for the exact pattern list.

## What to look for

Read sessions with these specific signals in mind. Each signal maps to a capability domain (defined in `references/capability-rubric.md`).

| Signal in session | Likely capability domain |
| --- | --- |
| User asks the agent to "double-check" / "are you sure" / "verify" something the agent just claimed | Whatever the agent claimed about — note the domain |
| Agent ran a destructive command and user reverted or corrected | Repo-architecture or release |
| User pastes an error and the agent's first guess is wrong | External docs or repo-specific knowledge |
| User asks "what does the AGENTS.md / CLAUDE.md / skill say about this" | Agent-workflows / repo-discoverability |
| User asks for live confirmation (curl, dashboard screenshot, log tail) | Live-verification need |
| Repeated re-asks of the same question across sessions | Memory/handoff gap |

Capture each signal as a structured observation:

```
- domain: <one of the rubric domains>
  evidence_type: quote | count
  evidence: "<≤25 word quote>" OR "<N of M sessions over <window>>"
  session_ref: <agent>:<session-id-or-date>   # do NOT include full transcript path with sensitive content
  interpretation: <one factual sentence; no personality claims>
```

The extractor appends compact `session_ref` markers to each extracted message.
Distillation strips them from quotes, counts distinct refs per domain, and may
surface the compact refs in `memory_derived` or `agent_compensation`. Do not use
full transcript paths as refs.

`interpretation` must describe what the agent should DO differently next time, not what the user IS. Banned: "user is weak in X." Allowed: "for X, the agent must confirm Y before recommending."

## Cross-session aggregation

Sort observations by domain. Within a domain, group quotes by signal type. The output of this mode is a domain-keyed dictionary of evidence-grounded observations, NOT a narrative. Mode 3 will turn this into the capability matrix.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| Paraphrasing a session as if it were a quote | Either quote verbatim (≤25 words) or count |
| Including a quote that contains a token-shaped string | Run scrub_secrets.py; on hit, drop the quote |
| Reading session content out loud back to the user | Reference by `<agent>:<session-id>` only; do not paste session content in chat |
| Writing "user keeps asking" | Convert to "in N of M sessions, the user re-asked X" |
| Claiming a pattern from 1 session | One occurrence is an anecdote, not a pattern. Require ≥2 unless the signal is unmistakable (e.g. agent ran a destructive command and was reverted). |
| Treating absence of a topic as a signal | "User never mentions X" is not evidence of anything — drop. |
