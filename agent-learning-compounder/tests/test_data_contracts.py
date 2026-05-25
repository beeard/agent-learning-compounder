from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import unittest

BIN = pathlib.Path(__file__).resolve().parents[1] / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import validate_artifacts


class DataContractTests(unittest.TestCase):
    def setUp(self) -> None:
        repo_root = pathlib.Path(__file__).resolve().parents[1]
        self.source_contracts = repo_root / "data-contracts"
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        shutil.copytree(self.source_contracts, self.tmp, dirs_exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_base_contract_has_core_artifacts_and_required_fields(self) -> None:
        os.environ["ALC_DATA_CONTRACTS_DIR"] = str(self.tmp)
        entries = validate_artifacts.load_contract_entries()
        ids = {entry["id"] for entry in entries}
        for artifact_id in ["corpus", "baseline", "gates", "insights", "events.jsonl", "events.sqlite"]:
            self.assertIn(artifact_id, ids)

        for entry in entries:
            for field in [
                "id",
                "path_template",
                "producer",
                "consumers",
                "surface_in_dashboard",
                "format",
                "lifecycle",
            ]:
                self.assertIn(field, entry)
            lifecycle = entry["lifecycle"]
            for field in [
                "create",
                "read",
                "update",
                "delete_or_retention",
                "owner",
                "states",
                "max_age",
                "max_count",
                "cleanup_command",
            ]:
                self.assertIn(field, lifecycle)

    def test_check_contracts_reports_orphan_file(self) -> None:
        state_dir = pathlib.Path(tempfile.mkdtemp())
        try:
            (state_dir / "corpus.json").write_text("{}", encoding="utf-8")
            (state_dir / "ghost.txt").write_text("bad", encoding="utf-8")
            os.environ["ALC_DATA_CONTRACTS_DIR"] = str(self.tmp)
            errors = validate_artifacts.check_contracts(state_dir)
            self.assertTrue(any("orphan artifact file" in err and "ghost.txt" in err for err in errors))
        finally:
            shutil.rmtree(state_dir)

    def test_check_manifest_merge_detects_duplicate_and_cycles(self) -> None:
        duplicate = self.tmp / "manifests" / "u6-dupe.json"
        duplicate.write_text(
            '{"artifacts": [{"id": "corpus", "path_template": "corpus.json", "producer": "dup", '
            '"consumers": [], "surface_in_dashboard": false, "format": "json", "lifecycle": {'
            '"create": "dup", "read": "all", "update": "dup", "delete_or_retention": "manual_cleanup",'
            '"owner": "test", "states": ["repo"], "max_age": "forever", "max_count": 1, "cleanup_command": ""}}]}'
        )

        cycle_a = self.tmp / "manifests" / "u6-a.json"
        cycle_a.write_text(
            '{"artifacts": [{"id": "artifact-a", "path_template": "artifact-a.txt", "producer": "u6", '
            '"consumers": ["artifact-b"], "surface_in_dashboard": false, "format": "text", "lifecycle": {'
            '"create": "u6", "read": "all", "update": "u6", "delete_or_retention": "manual",'
            '"owner": "test", "states": ["repo"], "max_age": "1d", "max_count": 5, "cleanup_command": ""}}]}'
        )

        cycle_b = self.tmp / "manifests" / "u6-b.json"
        cycle_b.write_text(
            '{"artifacts": [{"id": "artifact-b", "path_template": "artifact-b.txt", "producer": "u6", '
            '"consumers": ["artifact-a"], "surface_in_dashboard": false, "format": "text", "lifecycle": {'
            '"create": "u6", "read": "all", "update": "u6", "delete_or_retention": "manual",'
            '"owner": "test", "states": ["repo"], "max_age": "1d", "max_count": 5, "cleanup_command": ""}}]}'
        )

        os.environ["ALC_DATA_CONTRACTS_DIR"] = str(self.tmp)
        errors = validate_artifacts.check_manifest_merge()
        self.assertTrue(any("artifact 'corpus'" in err and "multiple manifests" in err for err in errors))
        self.assertTrue(any("producer-consumer cycle" in err for err in errors))
