---
name: alc-report
description: Run the unified ALC report; flags: --analyst-only, --recommend-only, --apply <id>, --eval, --open, --no-open, --help, --repo, --state/--state-dir/--state_dir, --baseline, --corpus, --synthesize-source, --host, --port, --no-serve.
---

```bash
set -euo pipefail

python3 "${ALC_PLUGIN_ROOT}/scripts/render_unified_report.py" $ARGUMENTS
```
