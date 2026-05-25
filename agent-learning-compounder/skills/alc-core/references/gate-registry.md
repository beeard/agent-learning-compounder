# Gate Registry Export

`../../bin/export_gates.py` turns a validated agent-learning report into a compact
markdown registry that future agents can load as policy.

## Command

```bash
python3 ../../bin/export_gates.py \
  --report "$RUN_DIR/report.md" \
  --output "$RUN_DIR/gates.md" \
  --max-domains 8
```

`--max-domains` is optional. When set, the exporter keeps the first N domains in
report order and drops later domains.

## Input Contract

The input must pass `../../bin/validate_outputs.py`. The exporter reads only the
`## agent_compensation` section and supports the standard report shape:

```markdown
### domain: teams

- **level:** 3
- **gates:**
  - category: live-check
    gate: Check the live tenant before proposing Teams policy.
```

It also accepts the YAML-like single-gate shape documented in
`references/output-schema.md`.

## Output Contract

The registry is headed `# Approved Agent Gates` and includes:

- `generated_at`
- `date`
- `source_report`
- `domains`
- `gate_category`
- `gate`
- `level`, when present
- named evidence counts, such as `matching_lines` or `sessions`

The registry intentionally excludes quotes, transcript snippets,
`evidence_summary`, session references, and other raw evidence. It is intended to
be safe to load in a future session as gate/policy context, not as a report
archive.
