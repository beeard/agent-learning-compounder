import json
import pathlib
import subprocess
import tempfile
import unittest
import zipfile
import sys


ROOT = pathlib.Path(__file__).resolve().parents[2]
BIN = ROOT / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import release_layout

MANIFEST_PATH = None
PACKAGE_ROOT = ROOT
INSTALL_SCRIPT = None

for candidate in (ROOT.parent, ROOT):
    manifest_candidate = candidate / "MANIFEST.json"
    install_candidate = candidate / "install.sh"
    if manifest_candidate.exists():
        MANIFEST_PATH = manifest_candidate
        PACKAGE_ROOT = candidate / "agent-learning-compounder" if (candidate / "agent-learning-compounder").exists() else candidate
        if install_candidate.exists():
            INSTALL_SCRIPT = install_candidate
        break

if MANIFEST_PATH is None:
    # Fallback for project-local copies (for example, when this package is installed into a repo during bootstrap).
    PACKAGE_ROOT = ROOT


class ContractTests(unittest.TestCase):
    def test_cli_help_smoke_for_install_and_key_scripts(self):
        if MANIFEST_PATH is None:
            self.skipTest("MANIFEST not available in this runtime (bootstrap package copy)")
        key_scripts = [
            "build_repo_baseline.py",
            "init_learning_system.py",
            "collect_hook_event.py",
            "distill_learning.py",
            "install_runtime_hooks.py",
            "map_active_skills.py",
            "refresh_learning_state.py",
        ]
        for script in key_scripts:
            result = subprocess.run(
                ["python3", str(PACKAGE_ROOT / "scripts" / script), "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            combined = result.stdout + result.stderr
            self.assertIn("usage", combined.lower(), script)

        if INSTALL_SCRIPT is None:
            self.skipTest("install.sh not available in this runtime")
        install_help = subprocess.run(
            [str(INSTALL_SCRIPT), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(install_help.returncode, 0, install_help.stderr)
        combined = install_help.stdout + install_help.stderr
        self.assertIn("Usage", combined)

    def test_manifest_contract_entrypoints_and_docs_and_symlink_resolution(self):
        if MANIFEST_PATH is None:
            self.skipTest("MANIFEST not available in this runtime (bootstrap package copy)")
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        for path in manifest["entrypoints"]:
            target = PACKAGE_ROOT / path
            self.assertTrue(target.exists(), f"missing entrypoint: {path}")
            if target.is_symlink():
                self.assertTrue(target.resolve().exists(), f"broken entrypoint symlink: {path}")
        for path in manifest["required_docs"]:
            target = PACKAGE_ROOT.parent / path
            self.assertTrue(target.exists(), f"missing required doc: {path}")
            if path.startswith("agent-learning-compounder/skills/alc-core/references/") and path.endswith(".md"):
                self.assertTrue(target.is_symlink(), f"required doc should be symlink: {path}")
                self.assertEqual(target.readlink(), pathlib.Path("../../reference-lib") / target.stem)
            if target.is_symlink():
                self.assertTrue(target.resolve().exists(), f"broken doc symlink: {path}")
            if target.is_symlink():
                self.assertTrue(target.resolve().exists(), f"broken doc symlink: {path}")

    def test_package_zip_contract_excludes_cached_artifacts(self):
        if MANIFEST_PATH is None:
            self.skipTest("MANIFEST not available in this runtime (bootstrap package copy)")
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        package_name = f"{manifest['name']}-{manifest['version']}"
        source_root = MANIFEST_PATH.parent
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            zip_path = root / f"{package_name}.zip"
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for relative in release_layout.iter_release_files(source_root):
                    path = source_root / relative
                    zf.write(path, arcname=str(pathlib.Path(package_name) / relative))

            with zipfile.ZipFile(zip_path, "r") as zf:
                entries = zf.namelist()

            self.assertTrue(entries, "zip artifact should contain entries")
            self.assertTrue(
                all(entry.split("/")[0] == package_name for entry in entries),
                "package zip should contain a single top-level directory",
            )
            self.assertFalse(any("__pycache__" in entry for entry in entries))
            self.assertFalse(any(entry.endswith(".pyc") for entry in entries))
            self.assertFalse(any("/.pytest_cache/" in entry for entry in entries))
            self.assertFalse(any("/docs/dev/" in entry for entry in entries))

    def test_install_excludes_cached_artifacts_from_source_tree(self):
        if INSTALL_SCRIPT is None:
            self.skipTest("install.sh not available in this runtime")
        with tempfile.TemporaryDirectory() as tmp:
            target_root = pathlib.Path(tmp) / "skills"
            result = subprocess.run(
                [str(INSTALL_SCRIPT), "--target", str(target_root)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = target_root / "agent-learning-compounder"
            leaked = [
                path.relative_to(installed)
                for path in installed.rglob("*")
                if path.name == "__pycache__"
                or path.name == ".pytest_cache"
                or path.suffix == ".pyc"
            ]
            self.assertEqual(leaked, [])
