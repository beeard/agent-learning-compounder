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
import { chmodSync, existsSync, readdirSync, readFileSync, statSync, symlinkSync, writeFileSync } from 'node:fs';
import { relative } from 'node:path';

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

// Restore .py module aliases stripped by npm tarball packing.
//
// In the source tree, e.g. `bin/ce_playbook.py` is a symlink to the executable
// `bin/ce_playbook`. Python's import machinery needs the `.py` suffix on disk
// to import the file as a module. npm dereferences symlinks when packing and
// then drops them entirely (it neither preserves them nor materializes them
// as file copies), so the `.py` aliases are missing from the published
// tarball — and `import ce_playbook` from `alc_init` blows up with
// ModuleNotFoundError.
//
// We materialize the missing aliases here as real file copies, scoped to
// shebanged Python executables under the three dirs that use the dual-name
// convention. Idempotent — skipped when the alias is already present (e.g. on
// the curl/GitHub tarball path, where symlinks survive intact).
function isPythonExecutable(filePath) {
  let stat;
  try { stat = statSync(filePath); } catch { return null; }
  if (!stat.isFile()) return null;
  let head;
  try { head = readFileSync(filePath, 'utf8').slice(0, 64); } catch { return null; }
  if (!head.startsWith('#!/usr/bin/env python')) return null;
  return stat;
}

// Try a relative symlink; fall back to file copy if symlinks aren't supported
// (e.g. Windows without Developer Mode). The copy fallback works for same-dir
// aliases — but breaks cross-dir aliases because the target's `os.path.realpath(__file__)`
// would no longer resolve to the bin/ directory where sibling modules live.
function aliasLinkOrCopy(aliasPath, targetPath) {
  const linkTarget = relative(dirname(aliasPath), targetPath);
  try {
    symlinkSync(linkTarget, aliasPath);
    return 'symlink';
  } catch {
    const stat = statSync(targetPath);
    writeFileSync(aliasPath, readFileSync(targetPath));
    chmodSync(aliasPath, stat.mode);
    return 'copy';
  }
}

// Same-dir restore: for each shebanged Python executable `X` in `dir`,
// ensure `X.py` exists (Python needs the .py suffix to import the file).
function restoreSameDirAliases(dir) {
  if (!existsSync(dir)) return 0;
  let entries;
  try { entries = readdirSync(dir); } catch { return 0; }
  const names = new Set(entries);
  let restored = 0;
  for (const name of entries) {
    if (name.endsWith('.py')) continue;
    const aliasName = name + '.py';
    if (names.has(aliasName)) continue;
    const filePath = resolve(dir, name);
    if (!isPythonExecutable(filePath)) continue;
    aliasLinkOrCopy(resolve(dir, aliasName), filePath);
    restored++;
  }
  return restored;
}

// Cross-dir restore: for each shebanged Python executable in `srcDir`,
// ensure `X.py` exists in `dstDir`. MUST be a symlink (not a copy) so the
// target's `os.path.realpath(__file__)` resolves to srcDir — many of these
// scripts use that to put their own sibling modules on sys.path.
function restoreCrossDirAliases(srcDir, dstDir) {
  if (!existsSync(srcDir) || !existsSync(dstDir)) return 0;
  let srcEntries, dstEntries;
  try { srcEntries = readdirSync(srcDir); } catch { return 0; }
  try { dstEntries = new Set(readdirSync(dstDir)); } catch { return 0; }
  let restored = 0;
  for (const name of srcEntries) {
    if (name.endsWith('.py')) continue;
    const aliasName = name + '.py';
    if (dstEntries.has(aliasName)) continue;
    const filePath = resolve(srcDir, name);
    if (!isPythonExecutable(filePath)) continue;
    aliasLinkOrCopy(resolve(dstDir, aliasName), filePath);
    restored++;
  }
  return restored;
}

const innerSkill = resolve(pkgRoot, 'agent-learning-compounder');
const binDir = resolve(innerSkill, 'bin');
const scriptsDir = resolve(innerSkill, 'scripts');
const innerScriptsDir = resolve(innerSkill, 'skills', 'alc-core', 'scripts');

let totalRestored = 0;
// Same-dir: bin/X → bin/X.py (Python import path)
totalRestored += restoreSameDirAliases(binDir);
// Cross-dir: bin/X → scripts/X.py (the user-facing CLI path documented in install.sh)
totalRestored += restoreCrossDirAliases(binDir, scriptsDir);
// Cross-dir: bin/X → skills/alc-core/scripts/X.py (inner skill compat path)
totalRestored += restoreCrossDirAliases(binDir, innerScriptsDir);
if (totalRestored > 0) {
  console.error(`alc-install: restored ${totalRestored} .py module aliases stripped by npm tarball.`);
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
