#!/usr/bin/env node
// alc-install — npm/npx entry point for installing agent-learning-compounder.
//
// Usage:
//   npx agent-learning-compounder                     # zero-config (auto-detect runtime, verify)
//   npx agent-learning-compounder --plugin            # install as Claude Code plugin
//   npx agent-learning-compounder --bootstrap-repo "$PWD" --verify
//
// This is a thin Node wrapper around install.sh — it forwards all arguments
// unchanged. The package ships install.sh and the inner skill tree, so the
// installer runs without network access once npx has fetched the package.

import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { existsSync, statSync } from 'node:fs';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, '..');
const installSh = resolve(pkgRoot, 'install.sh');

if (!existsSync(installSh)) {
  console.error(`alc-install: install.sh missing at ${installSh}`);
  process.exit(1);
}

const mode = statSync(installSh).mode;
if (!(mode & 0o111)) {
  console.error(`alc-install: install.sh at ${installSh} is not executable`);
  process.exit(1);
}

const child = spawnSync(installSh, process.argv.slice(2), {
  stdio: 'inherit',
  cwd: process.cwd(),
});

if (child.error) {
  console.error(`alc-install: failed to run install.sh: ${child.error.message}`);
  process.exit(1);
}

process.exit(child.status ?? 1);
