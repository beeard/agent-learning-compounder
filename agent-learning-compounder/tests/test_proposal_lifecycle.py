from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
import sys
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from state_handle import StateHandle
import proposal_lifecycle


def _called_names(function: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def _function_from(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path} has no function named {name}")


class ProposalLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        self.state = StateHandle.for_repo(self.repo)
        self.state.repo_state_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_gate_proposal_builds_queue_row_event_and_record(self) -> None:
        proposal = proposal_lifecycle.build_gate_proposal(
            domain="tests",
            category="quality",
            gate="Always validate output.",
            evidence="Observed during review.",
            now="2026-05-27T12:00:00Z",
            epoch_seconds=123,
        )

        self.assertTrue(proposal.queue_id.startswith("proposed-"))
        self.assertEqual(proposal.queue_row["id"], proposal.queue_id)
        self.assertEqual(proposal.queue_row["status"], "open")
        self.assertEqual(proposal.record["proposal_kind"], "gate")
        self.assertEqual(proposal.record["status"], "queued")
        self.assertEqual(proposal.event["event"], "gate_proposed")
        self.assertEqual(proposal.event["payload"]["queue_id"], proposal.queue_id)
        self.assertEqual(proposal.event["payload"]["lifecycle"]["proposal_kind"], "gate")

    def test_apply_proposal_is_non_mutating_command_record(self) -> None:
        proposal = proposal_lifecycle.build_apply_proposal(
            patch_id="patch-1",
            audit_nonce="nonce-1",
            now="2026-05-27T12:00:00Z",
        )

        self.assertEqual(proposal.command, "bin/alc_apply --patch patch-1 --write")
        self.assertEqual(proposal.record["proposal_kind"], "apply")
        self.assertEqual(proposal.record["status"], "proposed")
        self.assertEqual(proposal.event["payload"]["audit_nonce"], "nonce-1")
        self.assertNotIn("nonce-1", proposal.command)

    def test_read_proposal_queue_handles_missing_malformed_and_status(self) -> None:
        self.assertEqual(proposal_lifecycle.read_proposal_queue(self.state), [])

        queue = self.state.repo_state_dir / "improvement-queue.jsonl"
        queue.write_text(
            "\n".join(
                [
                    json.dumps({"id": "q1", "kind": "operator_proposed_gate", "status": "open", "ts": "2"}),
                    "{broken",
                    json.dumps({"id": "q2", "kind": "operator_proposed_gate", "status": "closed", "ts": "1"}),
                ]
            ),
            encoding="utf-8",
        )

        rows = proposal_lifecycle.read_proposal_queue(self.state)
        self.assertEqual([row["queue_id"] for row in rows], ["q2", "q1"])
        self.assertEqual(rows[0]["proposal_kind"], "gate")

        open_rows = proposal_lifecycle.read_proposal_queue(self.state, status="open")
        self.assertEqual([row["queue_id"] for row in open_rows], ["q1"])

    def test_read_lifecycle_state_correlates_queue_patches_and_suggestions(self) -> None:
        (self.state.repo_state_dir / "improvement-queue.jsonl").write_text(
            json.dumps({"id": "q1", "kind": "operator_proposed_gate", "status": "open", "ts": "1"}) + "\n",
            encoding="utf-8",
        )
        patch_dir = self.state.repo_state_dir / "patches"
        patch_dir.mkdir()
        (patch_dir / "p1.json").write_text(
            json.dumps({"patch_id": "p1", "status": "pending", "recommendation_id": "r1"}),
            encoding="utf-8",
        )
        (self.state.repo_state_dir / "suggestions.json").write_text(
            json.dumps({"suggestions": [{"recommendation_id": "r2", "kind": "workflow_chain"}]}),
            encoding="utf-8",
        )

        rows = proposal_lifecycle.read_lifecycle_state(self.state)
        kinds = {(row["proposal_kind"], row["artifact_id"]) for row in rows}
        self.assertIn(("gate", "q1"), kinds)
        self.assertIn(("patch", "p1"), kinds)
        self.assertIn(("workflow_chain", "r2"), kinds)

    def test_proposal_adapters_delegate_lifecycle_identity_and_reads(self) -> None:
        alc_propose = REPO_ROOT / "bin" / "alc_propose.py"
        alc_query = REPO_ROOT / "bin" / "alc_query.py"

        self.assertIn("build_gate_proposal", _called_names(_function_from(alc_propose, "propose_gate")))
        self.assertIn("build_apply_proposal", _called_names(_function_from(alc_propose, "propose_apply")))
        self.assertIn("build_outcome_event", _called_names(_function_from(alc_propose, "report_outcome")))
        self.assertIn("read_proposal_queue", _called_names(_function_from(alc_query, "get_proposal_queue")))
        self.assertIn("read_lifecycle_state", _called_names(_function_from(alc_query, "get_proposal_lifecycle")))


if __name__ == "__main__":
    unittest.main()
