from __future__ import annotations

import importlib
import os
import pathlib
import shutil
import sys
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = REPO_ROOT / "bin"


def load_writer(contract_dir: pathlib.Path):
    os.environ["ALC_DATA_CONTRACTS_DIR"] = str(contract_dir)
    if "artifact_writer" in sys.modules:
        del sys.modules["artifact_writer"]
    if str(BIN) not in sys.path:
        sys.path.insert(0, str(BIN))
    return importlib.import_module("artifact_writer")


class DummyState:
    def __init__(self, root: pathlib.Path) -> None:
        self.repo_state_dir = root


class ArtifactWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        base_contracts = REPO_ROOT / "data-contracts"
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        shutil.copytree(base_contracts, self.tmp, dirs_exist_ok=True)

        manifest_dir = self.tmp / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "u6-tests.json").write_text(
            '{"artifacts": ['
            '{"id": "unit-test-artifact", "path_template": "unit/test.json", "producer": "test", '
            '"consumers": ["reader"], "surface_in_dashboard": false, "format": "json", '
            '"max_size": 40, "lifecycle": {'
            '"create": "test", "read": "all", "update": "test", "delete_or_retention": "manual",'
            '"owner": "test", "states": ["repo"], "max_age": "30d", "max_count": 1, "cleanup_command": ""}},'
            '{"id": "unit-wildcard-artifact", "path_template": "unit/wild/*.json", "producer": "test", '
            '"consumers": ["reader"], "surface_in_dashboard": false, "format": "text", '
            '"lifecycle": {'
            '"create": "test", "read": "all", "update": "test", "delete_or_retention": "manual",'
            '"owner": "test", "states": ["repo"], "max_age": "30d", "max_count": 1, "cleanup_command": ""}}'
            ']}'
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def test_write_artifact_enforces_contracts(self) -> None:
        artifact_writer = load_writer(self.tmp)
        state = pathlib.Path(tempfile.mkdtemp())
        payload = {"hello": "world"}
        try:
            path = artifact_writer.write_artifact("unit-test-artifact", payload, DummyState(state))
            self.assertTrue(path.exists())
            self.assertIn('"hello"', path.read_text(encoding="utf-8"))
            with self.assertRaises(ValueError):
                artifact_writer.write_artifact("unit-test-artifact", {"x": "y" * 200}, DummyState(state))
        finally:
            shutil.rmtree(state)

    def test_write_artifact_rejects_unregistered_and_wildcard(self) -> None:
        artifact_writer = load_writer(self.tmp)
        state = pathlib.Path(tempfile.mkdtemp())
        try:
            with self.assertRaises(KeyError):
                artifact_writer.write_artifact("missing-artifact", {}, DummyState(state))
            with self.assertRaises(ValueError):
                artifact_writer.write_artifact("unit-wildcard-artifact", "oops", DummyState(state))
        finally:
            shutil.rmtree(state)
