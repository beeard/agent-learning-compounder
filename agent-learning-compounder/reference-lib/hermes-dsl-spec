# Hermes-DSL patch operation spec

Hermes-DSL op shape used by recommender output bundles:

```json
{
  "skill_manage_op": {
    "action": "create" | "patch" | "edit" | "write_file",
    "target_type": "skill" | "agent" | "command" | "hook",
    "target": "<repo-relative path>",
    "old_string": "<exact match>",   // for patch/edit
    "new_string": "<replacement>",   // for patch/edit
    "content": "<full file body>"    // for create/edit/write_file
  },
  "preflight": {
    "allowed_roots": ["<path prefix>", "..."],
    "expected_target_sha256": "<hash>",
    "max_target_size": 12345
  },
  "revert_op": {
    "action": "patch",
    "target_type": "skill" | "agent" | "command" | "hook",
    "target": "<same as skill_manage_op.target>",
    "old_string": "<inverse of skill_manage_op.new_string>",
    "new_string": "<inverse of skill_manage_op.old_string>"
  }
}
```

Conventions for recommender generators:

- `target` must be repo-relative, not absolute.
- For `action=create`, use `target_type=agent` for recommendation kind `agent_spawn_suggestion`, with path
  `alc-agents/dev/<name>.md`.
- `revert_op` is the exact inverse patch to rollback creation or edits.
- `workflow_chain` is **never** emitted as `skill_manage_op`; its payload is written as
  `<state>/suggestions.json` for dashboard rendering.
