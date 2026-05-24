# Source Adapters

Supported transcript sources are JSONL and JSON files with message-like events.

Known paths:

- Codex current: `~/.codex/sessions/**/*.jsonl`
- Codex JSON exports: `~/.codex/**/*.json`
- Older Codex-like personalisation flow: `~/.Codex/projects/**/*.jsonl`
- Claude Code: `~/.claude/projects/**/*.jsonl`
- Claude exports: pass the export directory explicitly with `--path`
- ChatGPT exports: pass a directory containing conversation JSON files; mapping/message trees are walked recursively.
- Hermes/Gemini JSON histories: pass the directory explicitly; generic role/content dictionaries are walked recursively.

Extraction rules:

- Use only `user` and `assistant` text-bearing messages.
- Accept string content and block arrays with `{ "type": "text", "text": "..." }`.
- Accept ChatGPT-style `{ "author": { "role": "user" }, "content": { "parts": [...] } }`.
- Match repo-local corpora by Codex `session_meta.payload.cwd`, Claude Code top-level `cwd` / `project`, or Claude's encoded project directory path.
- Repeat `--path` to combine agents in one corpus, e.g. `--path ~/.codex/sessions --path ~/.claude/projects`.
- Append compact `session_ref` markers derived from the filename; never emit full transcript paths as evidence refs.
- Ignore tool payloads by default.
- Scrub secrets before distillation, including escaped Claude tool-input payloads and UUID-like values in secret-bearing lines.
- If a quote would include a redacted token, drop that candidate.
- Use `--cwd "$PWD"` for repo-local reports so unrelated project sessions do not pollute the corpus.
