# data-contracts

`U6` splits artifact contracts into a shared `base.json` plus per-unit manifests under
`manifests/`. This avoids merge conflicts when units register new artifacts in parallel.

`base.json` contains artifacts that exist as part of Phase B foundations.

Each unit that owns new artifact IDs appends its own file:
`manifests/<unit-id>.json`.

## Manifest schema (per artifact)

- `id`
- `path_template`
- `producer`
- `consumers`
- `surface_in_dashboard`
- `format`
- `lifecycle`
  - `create`, `read`, `update`, `delete_or_retention`, `owner`, `states`, `max_age`, `max_count`, `cleanup_command`
- optional `max_size` (bytes)

`path_template` is resolved relative to the repo-specific state directory.
`*` wildcards are allowed (used by scanners and cleanup tooling), but
`artifact_writer.write_artifact(...)` requires concrete artifact paths.

## Registry merge and checks

`bin/validate_artifacts --check-manifest-merge` validates
- no duplicate IDs
- producer-consumer cycle-free graph
- compatible lifecycle declarations

`bin/validate_artifacts --check-contracts --state-dir <dir>` validates
runtime state against the merged registry and reports orphan artifact files.

`bin/validate_artifacts --check-pending-writes <writer-module>` verifies that a writer
module statically references registered artifact IDs in `write_artifact(...)` calls.

`--show-registry` prints the merged contract registry (helpful for smoke checks and
CI logs).
